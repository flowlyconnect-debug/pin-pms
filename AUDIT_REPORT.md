# Pindora PMS — Auditointiraportti vs. Init-template

**Päivä:** 3.5.2026
**Tarkastaja:** Claude (raskaiden tarkistusten tekijä)
**Verrattava ohje:** Asiakkaan Sovelluskehityksen init-template (22 pykälää)
**Työnjako:** Cursor koodaa → ChatGPT keskustelee/ohjeistaa → Claude tarkistaa/korjaa/ohjeistaa muille tekoälyille

> Tämä raportti perustuu lähdekoodin lukemiseen, EI ajavan järjestelmän testaamiseen. Kaikki "OK" -merkinnät tarkoittavat: tiedostosta löytyi templaten mukainen toteutus. Toimivuus pitää vielä varmistaa testeillä ja ajamalla.

---

## 1. MIKÄ ON HYVÄÄ (säilytä — älä riko)

Projektin perusta on yllättävän vahva ja noudattaa templatea suurelta osin:

- **Backend-pino oikea:** Python 3 + Flask + Gunicorn + Nginx + PostgreSQL + SQLAlchemy + Alembic/Flask-Migrate. Dockerfile ja docker-compose.yml olemassa. (Pykälä 1 ✅)
- **Moduulirakenne** vastaa templatea: `app/auth`, `app/admin`, `app/api`, `app/users`, `app/email`, `app/backups`, `app/core`, `app/settings`, `app/audit`, `app/organizations`, `migrations/`, `tests/`, `templates/`, `static/`. (Pykälä 2 ✅)
- **Roolit** ovat templaten mukaiset: `superadmin`, `admin`, `user`, `api_client` (`app/users/models.py` UserRole-enum). (Pykälä 3 ✅)
- **Auth:**
  - Flask-Login hallintaan, API-avain API-käyttöön (`app/api/auth.py`)
  - Salasanat hashattu Werkzeugilla (`generate_password_hash` `app/users/models.py`)
  - Salasanan resetointi sähköpostilla (`PASSWORD_RESET_TTL = 1 h` `app/auth/models.py`)
  - Login rate-limit (`app/auth/routes.py` rivi ~95)
  - CSRF Flask-WTF:llä (`csrf.init_app`) (Pykälä 4 ✅)
- **2FA superadminille:** TOTP (pyotp) + varakoodit + QR-koodi käyttöönotossa + `enforce_superadmin_2fa()` before_request -hook (`app/__init__.py` rivit ~341–371). 2FA-pakotus toimii ennen kriittisiä toimintoja. (Pykälä 5 ✅)
- **API:**
  - Polku `/api/v1/` käytössä
  - `Authorization: Bearer` JA `X-API-Key` molemmat tuettu (`app/api/auth.py` rivit 29–37)
  - API-avaimet **hashattu** SHA-256:lla tietokannassa (`app/api/models.py`)
  - Avaimet ovat nimettäviä, deaktivoitavissa, vanheutuvia, organisaatio-rajattuja
  - API-käyttö lokitetaan (`record_api_key_usage`)
  - **/api/v1/health** ja **/api/v1/me** olemassa
  - Yhtenäinen JSON-rakenne: `json_ok` / `json_error` (`app/api/schemas.py`)
  - Rate-limit per API-key (`app/extensions.py`) (Pykälä 6 ✅)
- **Mailgun:**
  - `MAILGUN_API_KEY/DOMAIN/FROM_EMAIL/FROM_NAME` ympäristömuuttujina (`config.py`, `.env.example`)
  - Sandboxed Jinja-renderöinti pohjille (`SandboxedEnvironment` `app/email/services.py`)
  - Keskitetty email service -kerros (`send_template()` ei kutsuta routeista suoraan)
  - Pohjat olemassa: `welcome_email`, `password_reset`, `login_2fa_code`, `backup_completed`, `backup_failed`, `admin_notification` (+PMS-spesifit reservation/invoice)
  - Esikatselu ja testilähetys admin UI:ssä (Pykälä 7 ✅)
- **Varmuuskopiot:**
  - APScheduler-pohjainen päivittäinen ajo (`app/backups/scheduler.py`)
  - `pg_dump` + gzip (`app/backups/services.py`)
  - PostgreSQL + uploads-tarball + asetukset
  - Säilytys 14–30 päivää (`BACKUP_RETENTION_DAYS`)
  - Manuaalinen käynnistys CLI:stä JA admin UI:sta
  - Palautus vaatii **superadmin-salasanan + 2FA-koodin**
  - Pre-restore turvakopio nykytilasta
  - Ilmoitus superadminille onnistumisesta/virheestä (Pykälä 8 ✅)
- **Settings-taulu** templaten mukainen: `id, key, value, type, description, is_secret, updated_by, updated_at` + keskitetty service (`app/settings/`). (Pykälä 9 ✅)
- **Tietoturva:**
  - Salasanat ja API-avaimet hashattu
  - CSRF, rate-limit, ORM, XSS-suojaus (Jinja auto-escape)
  - CORS rajattu (default tyhjä → kielto, `app/__init__.py` rivi ~99)
  - Security-headerit: CSP, X-Frame-Options, HSTS, Referrer-Policy (`app/core/security_headers.py`)
  - `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE` ProductionConfigissa (Pykälä 10 ✅)
- **Audit-loki:** AuditLog-malli kentät `user_id, action, target_type, target_id, ip_address, user_agent, metadata, created_at` (`app/audit/models.py`). Ei muokattavissa UI:sta. Kattaa kirjautumiset, 2FA, API-avaimet, asetukset, käyttäjät, varmuuskopiot. (Pykälä 11 ✅)
- **Multi-tenant:** `organizations` + `users.organization_id` + tenant-isolation API-tasolla (`g.api_key.organization_id`). Erillinen `tests/test_tenant_isolation.py`. (Pykälä 12 ✅)
- **Virheenkäsittely:** 400/401/403/404/429/500 keskitetysti (`app/core/errors.py`). (Pykälä 15 ✅)
- **Testaus:** pytest + 80 % coverage gate (`pytest.ini`). Olemassa: `test_2fa.py`, `test_backup.py`, `test_api_auth.py`, `test_tenant_isolation.py` ym. (Pykälä 16 ✅)
- **Dokumentaatio:** README.md ja `.env.example` olemassa. (Pykälä 17 ✅)
- **CLI-komennot olemassa:** `flask create-superadmin`, `flask backup-create`, `flask backup-restore`, `flask send-test-email`, `flask db upgrade` (`app/cli.py`).
- **Service-kerros:** Liiketoimintalogiikka on services-tiedostoissa, routet ovat ohuet. (Pykälä 20 ✅)

---

## 2. MIKÄ EI TOIMI / PUUTTUU INIT-TEMPLATESTA (kriittiset)

Nämä rikkovat asiakkaan ohjeet — pitää korjata ennen hyväksyntää.

### 2.1 `flask rotate-api-key` -CLI-komento PUUTTUU
- **Templaten kohta:** Pykälä 19 ("Komentorivityökalut")
- **Vaadittu:** `flask rotate-api-key`
- **Tila:** ❌ EI LÖYDY tiedostosta `app/cli.py`
- **Toimenpide:** Lisää `app/cli.py`-tiedostoon komento joka:
  1. Ottaa `--key-id` parametrin
  2. Mitätöi vanhan avaimen (asettaa `is_active=False` ja `rotated_at=now()`)
  3. Luo uuden avaimen samalla nimellä, scopella, organisaatiolla
  4. Kirjaa `audit_record(action="api_key.rotated", target_id=key_id)`
  5. Tulostaa uuden plain-text-avaimen vain kerran (kuten luonnissa)
- **Vastuu:** Cursor (koodi) — Claude antaa ohjeen, ChatGPT ei tarvita

### 2.2 API-scope-tarkistus EI ole pakollinen kaikilla endpointeilla
- **Templaten kohta:** Pykälä 6 ("API-avain… voidaan rajoittaa oikeuksilla")
- **Vaadittu:** Jokaisen API-endpointin pitää tarkistaa, onko avaimella oikea scope
- **Tila:** ⚠️ OSITTAIN — `@scope_required("...")` -dekoraattori on olemassa (`app/api/auth.py`), mutta se on vapaaehtoinen. Endpointit jotka unohtuvat dekoroida sallivat minkä tahansa avaimen.
- **Toimenpide:** 
  1. Käy läpi KAIKKI `app/api/routes.py`-endpointit (paitsi `/health` ja `/me`)
  2. Lisää jokaiselle eksplisiittinen `@scope_required("alue:read|write")`
  3. Päivitä `tests/test_api_scopes.py` siten että jokaiselle endpointille on testi joka varmistaa että väärällä scopella saa 403
  4. Harkitse: lisää `app/api/__init__.py`-blueprintille global before_request -tarkistus joka pakottaa scopen jokaiselle endpointille (whitelist `/health` ja `/me`)
- **Vastuu:** Cursor (koodi) + Claude (tarkistuslista endpointeista) — ChatGPT voi auttaa scope-nimien suunnittelussa

### 2.3 JWT-tuki PUUTTUU (template mainitsee "API-avain/JWT")
- **Templaten kohta:** Pykälä 4 ("Autentikointi: Flask-Login hallintakäyttöön ja API-avain/JWT API-käyttöön")
- **Tila:** ⚠️ Vain API-avain on toteutettu. JWT puuttuu.
- **Tulkinta:** Template käyttää sanaa "tai" (kauttaviiva), joten API-avain ehkä riittää. **TARKISTETTAVA ASIAKKAALTA.**
- **Toimenpide:**
  - Vaihtoehto A: Kysy asiakkaalta, riittääkö API-avain
  - Vaihtoehto B: Lisää JWT Bearer-headerin sisarena (PyJWT) lyhytaikaiseen autentikointiin (esim. mobiili-/SPA-käyttö)
- **Vastuu:** ChatGPT kysyy asiakkaalta → jos JWT vaaditaan, Cursor toteuttaa Clauden suunnitelman pohjalta

### 2.4 Coverage-gate ei ole varmasti läpäisty
- **Templaten kohta:** Pykälä 22 ("testit menevät läpi")
- **Tila:** ⚠️ `pytest.ini`:ssä on `--cov-fail-under=80`, mutta ei voida varmistaa lukematta että kaikki testit menevät vihreänä läpi.
- **Toimenpide:** Aja `pytest -v` ja `pytest --cov=app`. Korjaa epäonnistuvat testit. Lisää testit puuttuville flow-kohteille (rotate-api-key, scope-enforcement, GDPR-poisto, jne.).
- **Vastuu:** Cursor ajaa + korjaa, Claude tarkistaa että kattavuus on aito (ei vain testaa hyvyyttä)

---

## 3. MITÄ PITÄÄ MUOKATA / KORJATA (template-tarkistuksia)

Nämä eivät ole kriittisiä rikkomuksia, mutta tarkistettavia kohtia:

1. **Tarkista että `SECRET_KEY` on **pakollinen** ProductionConfigissa.** Tarkistettu: `app/config.py` heittää RuntimeErrorin, jos puuttuu prodissa. ✅ Tämä on OK, ei vaadi muutosta — mutta varmista että dev-default ei pääse pakettiin.
2. **Audit-lokin täydellisyys:** Tarkista että nämä toimet kirjautuvat (template pykälä 11):
   - kirjautuminen ✅
   - epäonnistunut kirjautuminen — **tarkistettava** kirjautuuko `auth.login_failed` AINA
   - uloskirjautuminen — **tarkistettava**
   - salasanan vaihto ✅
   - 2FA käyttöönotto ✅
   - API-avaimen luonti/poisto ✅
   - asetusten muutos — **tarkistettava** että `settings.update` audit-tapahtuma syntyy aina kun `SettingsService.set()` muuttaa arvoa
   - käyttäjän luonti/poisto/roolin muutos ✅
   - varmuuskopion luonti/palautus ✅
   - sähköpostipohjan muutos — **tarkistettava** kirjautuuko `email_template.update`
3. **Sähköpostipohjien muuttujadokumentaatio:** Tarkista että jokaisessa pohjassa on dokumentoidut muuttujat (esim. `{{ user_name }}`) ja superadmin näkee ne UI:ssa.
4. **2FA-varakoodit:** Tarkista että varakoodit ovat one-time-use (käytön jälkeen ei toimi uudestaan). `app/users/models.py` rivit 91–94.
5. **Kovakoodatut salaisuudet:** `git grep -n "password\|secret\|api[_-]key"` — ei pidä löytyä mitään konkreettisia arvoja koodista. **Aja Cursorilla**.
6. **Lokit eivät saa vuotaa salaisuuksia:** Tarkista että `app/core/logging.py` tai vastaava maskaa salasanat, tokenit ja API-avaimet automaattisesti.
7. **Validoi että routeissa ei ole raskasta logiikkaa:** Pikatarkastus näytti että suuret routet (esim. login) delegoivat servicelle. Käy kuitenkin läpi `app/admin/routes.py` ja `app/api/routes.py` — jos joku route tekee suoraan tietokantakyselyitä yli 1–2 rivin verran, siirrä service-kerrokseen. (Pykälä 20)
8. **Frontend-rajoitukseen ei saa luottaa:** Tarkista että jokainen admin-toiminto (ei vain UI-piilotus) tarkistaa roolin backendissa. `require_admin_pms_access`-dekoraattori käytössä `app/admin/routes.py` — varmista että se on JOKAISEN admin-routen päällä.

---

## 4. MITÄ PITÄÄ LISÄTÄ AMMATTITASOA VARTEN (PMS-laajennukset)

> **Tärkeää:** Nämä lisäykset EIVÄT saa rikkoa init-templatea. Jokainen lisäys tehdään template-säännöillä: service-kerros, audit-loki, oikeustarkistus, tenant-isolation, validointi, env-konfig.

PMS-projekti on jo melko laaja (sisältää `app/properties`, `app/reservations`, `app/guests`, `app/owners`, `app/billing`, `app/maintenance`, `app/portal`, `app/owner_portal`, `app/integrations/ical`, `app/integrations/pindora_lock`, `app/reports`, `app/status`, `app/subscriptions`). **Mitä silti puuttuu PMS-tasolle:**

### 4.1 Maksuintegraatio (Stripe / Visma Pay)
- Uusi moduuli `app/payments/` (services, models, routes, webhooks)
- Webhook endpoint `/api/v1/payments/webhook/<provider>` (varmenne signature)
- `Payment`-malli linkitettynä `Invoice`-malliin
- Audit-loki: `payment.received`, `payment.failed`, `payment.refunded`
- Env-muuttujat: `STRIPE_API_KEY`, `STRIPE_WEBHOOK_SECRET`, `VISMAPAY_*`
- **Tärkeää:** Avaimet vain envistä, ei koodissa.

### 4.2 ALV-käsittely laskuissa
- `Invoice`-malliin: `vat_rate` (esim. 24.00), `vat_amount`, `total_excl_vat`, `total_incl_vat`
- Asetuksissa default-VAT (`SettingsService.get("billing.default_vat_rate")`)
- Migraatio Alembicilla
- **Pakollinen EU-laskutuksessa.**

### 4.3 PDF-kuitti / -lasku
- Uusi `app/receipts/` tai `app/invoices/pdf.py`
- Käyttää reportlabia (jos jo riippuvuuksissa) tai WeasyPrintiä
- Lataus: `GET /admin/invoices/<id>/pdf`
- API-versio: `GET /api/v1/invoices/<id>/pdf` (scope `invoices:read`)

### 4.4 GDPR-toiminnot
- CLI: `flask gdpr-export-user --email <email>` → JSON-vienti kaikesta käyttäjän datasta
- CLI: `flask gdpr-anonymize-user --email <email>` → korvaa PII null/anonymisoidulla, säilyttää tilastot
- CLI: `flask gdpr-delete-user --email <email>` → poistaa kaikki yhdistettävyydet (cascade)
- Audit-loki: `gdpr.export`, `gdpr.anonymize`, `gdpr.delete`
- Admin-UI: erillinen "GDPR"-sivu superadminille
- **Vaaditaan EU-tietosuojassa.**

### 4.5 Siivouskalenteri (cleaning)
- Uusi `app/cleaning/` (CleaningTask-malli, scheduler joka generoi tehtävät reservation.checkout-päivien mukaan)
- Henkilöstön roolit (cleaner) → uusi rooli `UserRole.cleaner`? Tai tag käyttäjälle? **Suunnittelu Claude/ChatGPT.**
- Mobiili-friendly view (cleaner-portaali)

### 4.6 Hinnoittelusäännöt (dynamic pricing)
- `PricingRule`-malli: kausi, viikonpäivä, minimi-yöt, hinta-alennus, vähimmäishinta
- Service joka laskee `Reservation.total_price` syntyhetkellä
- Override iCal-importin yhteydessä? **Suunnittelu.**

### 4.7 Raportoinnin syveneminen
- Tulot per kohde / per kuukausi / per kanava
- Käyttöaste (occupancy %) per kohde / per kuukausi
- ADR (Average Daily Rate) ja RevPAR
- Ladattava XLSX/CSV/PDF
- Service-kerros: `app/reports/services.py` jo olemassa, laajenna.

### 4.8 Monikielisyys (i18n)
- Flask-Babel
- Kielet vähintään: fi, en, sv (Suomen markkinat)
- Käyttäjäkohtainen kieliasetus `users.locale`
- Sähköpostipohjat per kieli (laajennus EmailTemplate-malliin: `locale`-sarake)

### 4.9 Channel manager -laajennus (Booking.com, Airbnb)
- iCal-tuki on jo (`app/integrations/ical`)
- LISÄYS: kaksisuuntainen API-integraatio (Booking.com Connectivity API tai Channex/Hostaway-välipalvelu)
- **Suunnittelu Claude:** Tämä on iso ja vaatii erillisen design-dokumentin

### 4.10 Webhook-järjestelmä asiakkaille
- `Webhook`-malli (URL, events[], secret)
- Service joka lähettää signed webhook-tapahtumat (esim. `reservation.created`)
- Retry-logiikka epäonnistumisille
- **PMS-integraatioiden vakio-ominaisuus.**

### 4.11 Saavutettavuus (a11y) ja UI-paranoinnit
- ARIA-labelit, näppäimistönavigointi, kontrastit
- Mobiilinäkymät (ainakin admin-paneelin tärkeimmät sivut)

### 4.12 Monitoring & alerting (tuotanto)
- Sentry-integraatio (env-muuttuja `SENTRY_DSN`)
- Health-endpoint laajennettuna: tarkistaa DB, Mailgun-tavoitettavuus, taustatöiden tila
- Status-sivu (jo olemassa `app/status/`) — varmista että kattaa tärkeimmät riippuvuudet

---

## 5. PRIORISOITU TODO — toimeksianto Cursorille ja ChatGPT:lle

> **Käyttöohje:** Kopioi tämä lista ChatGPT:lle ja pyydä se tekemään detalji-ohjeet Cursorille per tehtävä. Cursor toteuttaa, Claude tarkistaa.

### VÄLITTÖMÄT (tee ennen hyväksyntää, init-template-rikkomukset)

1. **Lisää `flask rotate-api-key` -CLI-komento** → `app/cli.py`
   - Vaiheet: katso §2.1
   - Vastuu: **Cursor**
   - Aika: 1–2 h

2. **Pakota API-scope-tarkistus jokaiselle endpointille** → `app/api/routes.py`
   - Vaiheet: katso §2.2
   - Vastuu: **Cursor** (Claude antaa ennen sitä endpoint-listan)
   - Aika: 3–4 h

3. **Aja kaikki testit ja korjaa epäonnistuvat** → `tests/`
   - Komento: `pytest -v --cov=app --cov-fail-under=80`
   - Vastuu: **Cursor** (Claude käy yli kun valmis)
   - Aika: 2–4 h

4. **Tarkista audit-loki: kirjautuvatko KAIKKI vaaditut tapahtumat** → useat tiedostot
   - Vaiheet: §3 kohta 2
   - Vastuu: **Claude tarkistaa logiikan** + Cursor lisää puuttuvat audit-kutsut
   - Aika: 1–2 h

5. **Käy läpi `git grep` salaisuuksien varalta** → koko repo
   - Komento: `git grep -nE "(api[_-]?key|secret|password|token)\s*=\s*['\"][A-Za-z0-9]{8,}"`
   - Vastuu: **Cursor**
   - Aika: 30 min

6. **Kysy asiakkaalta: riittääkö API-avain vai tarvitaanko JWT?**
   - Vastuu: **ChatGPT** (kysymyksen muotoilu) → asiakas vastaa → Cursor toteuttaa jos JWT vaaditaan
   - Aika: kysely 5 min, JWT-toteutus 4–6 h jos tarpeellinen

### TÄRKEÄT (tee 1–2 viikon sisällä — laillisuus + perustoiminnallisuus)

7. **ALV-käsittely laskuihin** → `app/billing/models.py`, migraatio
   - Vaiheet: §4.2
   - Vastuu: **Cursor** + **kirjanpitäjä konsultoi**
   - Aika: 2–3 h

8. **GDPR-CLI-komennot** → uusi `app/gdpr/`
   - Vaiheet: §4.4
   - Vastuu: **Claude suunnittelu** + **Cursor toteutus**
   - Aika: 4–6 h

9. **PDF-laskut/kuitit** → uusi `app/receipts/` tai `app/invoices/pdf.py`
   - Vaiheet: §4.3
   - Vastuu: **Cursor**
   - Aika: 3–5 h

10. **Maksuintegraatio (Stripe ensin)** → uusi `app/payments/`
    - Vaiheet: §4.1
    - Vastuu: **Claude design-dokumentti** + **Cursor toteutus** + **ChatGPT testikäyttöön ohje**
    - Aika: 8–12 h

### PMS-LAAJENNUKSET (kuukauden sisällä — ammattitason saavuttaminen)

11. **Siivouskalenteri** → uusi `app/cleaning/` — §4.5 — **Cursor + Claude design** — 6–8 h
12. **Hinnoittelusäännöt** → §4.6 — **Claude design + Cursor** — 8–10 h
13. **Raportoinnin laajennus** → `app/reports/` — §4.7 — **Cursor** — 6–10 h
14. **Monikielisyys (Flask-Babel)** → koko UI — §4.8 — **Cursor + kääntäjä** — 10–15 h
15. **Webhookit asiakkaille** → uusi `app/webhooks/` — §4.10 — **Cursor + Claude design** — 6–8 h
16. **Sentry + monitoring** → §4.12 — **Cursor** — 2–3 h
17. **Channel manager -kaksisuuntainen** → §4.9 — **Claude iso design-dokumentti ensin**, sitten Cursor — 20+ h

---

## 6. TÄRKEIN MUISTUTUS

> Asiakkaan ohje pykälä 23: **"Pidä sovellus yksinkertaisena. Älä rakenna ylimääräistä arkkitehtuuria, jos sille ei ole vielä tarvetta. Tee ensin turvallinen, selkeä ja toimiva pohja."**

Älä siis aloita PMS-laajennuksia (kohta 4) ennen kuin **kaikki kohdan 2 kriittiset rikkomukset on korjattu** ja **kaikki testit menevät läpi**. Asiakkaan ohjeet ovat ehdottomat — yksikään lisäys ei ole hyvä, jos se rikkoo ne.

**Työnjako muistuksena:**
- **Cursor:** Kirjoita ja muokkaa koodi tarkasti Clauden ohjeen mukaan
- **ChatGPT:** Keskustele, muotoile, kysy asiakkaalta, anna step-by-step -ohjeet
- **Claude:** Tarkista, korjaa logiikka, suunnittele isot muutokset, kirjoita tekoäly-ohjeet, varmista että init-templatea noudatetaan 100 %
