# Pindora PMS — Promptit ChatGPT:lle (jotka ChatGPT muuttaa Cursor-ohjeiksi)

**Käyttöohje:**
1. Avaa ChatGPT (uusi keskustelu)
2. Aloita liittämällä **Prompt 0 (alustus)** — se kertoo ChatGPT:lle työnjaon ja säännöt
3. Liitä sen jälkeen yksi tehtäväprompti kerrallaan (Prompt 1, 2, 3 …) — älä kaikkia kerralla
4. ChatGPT antaa sinulle Cursor-promptin → kopioi se Cursoriin
5. Kun Cursor on valmis, tuo muutokset Claudelle tarkistettavaksi

> **Tärkeää:** Älä päästä ChatGPT:tä keksimään mitään, mitä asiakkaan init-template ei salli. Prompt 0 sitoo sen sääntöihin.

---

## PROMPT 0 — Alustus ChatGPT:lle (liitä ensin, vain kerran)

```
Olet osa kolmiosaista AI-tiimiä joka kehittää Pindora PMS -nimistä Flask-sovellusta:
- Claude tekee tarkistukset, suunnitelmat ja antaa ohjeet (raskain työ)
- Sinä (ChatGPT) muotoilet Clauden ohjeet yksityiskohtaisiksi Cursor-prompteiksi
- Cursor toteuttaa koodin Cursorin AI-ohjelmointityökalulla

Sovellusta sitoo asiakkaan init-template (22 pykälää). Yksikään muutos EI saa rikkoa templatea.

Init-templaten tärkeimmät ehdottomat säännöt joita Cursorin pitää aina noudattaa:
- Backend: Python 3 + Flask + Gunicorn + Nginx + PostgreSQL + SQLAlchemy + Alembic
- EI kovakoodattuja salaisuuksia, kaikki .env-muuttujista
- Roolit: superadmin, admin, user, api_client
- Superadminilla 2FA pakko ennen kriittisiä toimintoja
- API: /api/v1/, Bearer + X-API-Key, hashatut avaimet, JSON-rakenne {success, data, error}
- Sähköposti aina keskitetyn email service -kerroksen kautta (ei suoraan routeista)
- Kaikki kriittiset toimet kirjataan audit-lokiin (user_id, action, target_type, target_id, ip_address, user_agent, metadata, created_at)
- Multi-tenant: oikeustarkistus AINA backendissä, ei luoteta frontendiin
- CSRF, rate-limit, syötteen validointi pakollisia
- Salasanat ja API-avaimet hashattu
- Liiketoimintalogiikka service-kerroksessa, routet ohuet
- Tietokantamuutokset Alembic-migraatioilla
- Yhtenäinen virhevastausrakenne (400/401/403/404/429/500)
- Pytest-testit jokaiselle uudelle toiminnolle, coverage 80 %
- Pidä yksinkertaisena — ei ylimääräistä arkkitehtuuria

Projektirakenne (oleellisimmat moduulit):
- app/__init__.py, app/config.py, app/extensions.py, app/cli.py
- app/auth/ (routes, models, services, forms)
- app/api/ (routes, auth, schemas, services, rate_limits, models)
- app/admin/ (routes, services, forms)
- app/users/, app/organizations/, app/email/, app/backups/
- app/core/ (security, security_headers, permissions, logging, errors, utils)
- app/audit/ (models, services), app/settings/ (models, services)
- app/properties/, app/reservations/, app/guests/, app/owners/, app/billing/, app/maintenance/
- app/portal/, app/owner_portal/, app/integrations/ical/, app/integrations/pindora_lock/
- migrations/, tests/

Sinun tehtäväsi prompttia per pyyntö:
1. Lue Clauden tehtäväkuvaus
2. Tee siitä Cursorille tarkka, vaiheittainen prompt joka sisältää:
   - Tehtävän tavoite ja konteksti (mitä init-templaten kohtaa toteutetaan)
   - Konkreettiset tiedostopolut joita muokataan
   - Pseudokoodi tai funktioiden allekirjoitukset
   - Audit-lokin kutsut joita pitää lisätä
   - Testit joita pitää lisätä (pytest, tiedostonimi)
   - Mitkä env-muuttujat pitää päivittää (.env.example + config.py)
   - Migraatio jos tietokantamuutoksia (Alembic-komento)
   - Lopuksi: miten Cursor varmistaa että muutos ei riko templatea
3. Kirjoita prompti suomeksi, koska Cursor ymmärtää suomea
4. ÄLÄ keksi mitään, mitä Clauden ohjeessa ei lue
5. Älä lyhennä — Cursor tarvitsee yksityiskohtaisen ohjeen
6. Päätä jokainen prompti komentoon: "Älä toteuta mitään mikä rikkoo init-templatea. Jos jokin on epäselvä, kysy."

Vahvista että ymmärsit, niin lähetän sinulle ensimmäisen tehtävän.
```

---

## PROMPT 1 — `flask rotate-api-key` -CLI-komento (KRIITTINEN)

```
Tehtävä Cursorille: Lisää `flask rotate-api-key` CLI-komento.

Tausta: Init-templaten pykälä 19 vaatii komennon `flask rotate-api-key`. Se puuttuu tällä hetkellä tiedostosta app/cli.py. Tämä rikkoo templatea ja estää hyväksynnän.

Tekninen kuvaus:
- Lisää uusi click-komento tiedostoon app/cli.py
- Komento ottaa vaadittuna parametrina --key-id <int> ja vapaaehtoisena --reason <str>
- Toiminta:
  1. Hae APIKey-objekti tietokannasta key_id:llä (app/api/models.py)
  2. Jos avainta ei löydy → tulosta virhe ja exit code 1
  3. Tallenna vanha avain: aseta is_active=False ja rotated_at=datetime.utcnow()
  4. Luo uusi APIKey samalla name, scopes, organization_id, expires_at -arvoilla
  5. Hashaa uuden avaimen plain-text-arvo (käytä samaa hashausta kuin avainten luonnissa)
  6. Tulosta uusi plain-text-avain konsoliin VAIN kerran (kuten avaimen luonnissa)
  7. Kirjaa audit-lokiin: action="api_key.rotated", target_type="api_key", target_id=<vanha key_id>, metadata={"new_key_id": <uusi>, "reason": reason}
  8. Käytä app/audit/services.py audit_record-funktiota

Tiedostot joita muokataan:
- app/cli.py (uusi komento)
- (mahdollisesti) app/api/services.py jos sinne tarvitaan rotate_api_key()-helper

Testit:
- tests/test_cli.py — uusi testi test_rotate_api_key_command:
  - Luo APIKey, aja komento Click runnerilla
  - Varmista: vanha avain on is_active=False
  - Varmista: uusi avain on luotu samalla name+scope+org
  - Varmista: audit-loki sisältää api_key.rotated -tapahtuman
  - Varmista: jos --key-id ei löydy → exit code != 0

ÄLÄ:
- Älä tulosta hashia konsoliin — vain plain-text-avain (joka saadaan luonnista)
- Älä unohda audit-lokia
- Älä riko olemassa olevia api_key-toimintoja
- Älä koskaan tallenna plain-text-avainta tietokantaan

Aja lopuksi: pytest tests/test_cli.py -v
Varmista: pytest --cov=app.cli kattaa uuden funktion
```

---

## PROMPT 2 — API-scope-tarkistuksen pakottaminen (KRIITTINEN)

```
Tehtävä Cursorille: Pakota API-scope-tarkistus jokaiselle /api/v1/* -endpointille.

Tausta: Init-templaten pykälä 6 vaatii että API-avaimet voidaan rajoittaa oikeuksilla (scopes). Tällä hetkellä @scope_required("...") -dekoraattori on olemassa (app/api/auth.py) mutta sen käyttö on vapaaehtoista. Endpointit jotka unohtuvat dekoroida sallivat minkä tahansa avaimen → tämä rikkoo templatea.

Vaihe 1: Endpointtien inventaario
- Lue app/api/routes.py kokonaan
- Listaa kaikki @bp.route(...) -endpointit
- Merkitse kunkin viereen: onko @scope_required("...")? Jos on, mikä scope?

Vaihe 2: Lisää puuttuvat scopet
- Käytä luonnollisia scope-nimiä: "<resurssi>:<toiminto>" (esim. "reservations:read", "reservations:write", "invoices:read", "invoices:write", "guests:read", "properties:read")
- Jokaiselle endpointille (paitsi /health ja /me) lisää @scope_required(...) -dekoraattori sopivalla scopella
- Varmista että ALLOWED_API_KEY_SCOPES (app/api/models.py) sisältää kaikki käytetyt scopet

Vaihe 3: Globaali turvaverkko
- Lisää app/api/__init__.py blueprintille before_request-hook joka:
  - Sallii /api/v1/health ja /api/v1/me ilman scope-tarkistusta
  - Vaatii että kaikilla muilla endpointeilla on g.api_key (jos ei → 401)
  - Vaatii että endpointin function-objektilla on attribute "_required_scope" (asetetaan @scope_required dekoraattorissa) — jos ei ole → 500 + lokita virheilmoitus "endpoint missing @scope_required"
- Päivitä @scope_required-dekoraattori asettamaan func._required_scope = scope

Vaihe 4: Testit
- tests/test_api_scopes.py: laajenna olemassa oleva tiedosto
- Jokaiselle uudelle scope-vaatimukselle lisää testi:
  - Avain ilman scopea → 403 Forbidden
  - Avain väärällä scopella → 403 Forbidden
  - Avain oikealla scopella → 200 OK
- Lisää meta-testi joka varmistaa että jokaisella /api/v1/* -reitillä on _required_scope tai se on whitelisted

Tiedostot joita muokataan:
- app/api/routes.py (lisää @scope_required jokaiselle endpointille)
- app/api/auth.py (päivitä @scope_required asettamaan _required_scope-attribuutti)
- app/api/__init__.py (before_request-hook globaaliksi turvaverkoksi)
- app/api/models.py (laajenna ALLOWED_API_KEY_SCOPES jos uusia scopeja)
- tests/test_api_scopes.py (uudet testit)

ÄLÄ:
- Älä muuta /health ja /me -endpointeja (ne ovat ainoat ilman scopea)
- Älä lisää scopeja jotka eivät ole listalla — laajenna ALLOWED_API_KEY_SCOPES jos tarpeen
- Älä riko tenant-isolaatiota (g.api_key.organization_id pitää aina käyttää datan rajaamiseen)
- Älä tee globaaliksi turvaverkoksi try/except joka piilottaa virheet — heitä 500 selkeällä virheilmoituksella

Aja lopuksi: pytest tests/test_api_scopes.py -v
Varmista: pytest -v menee kokonaan läpi
```

---

## PROMPT 3 — Audit-lokin kattavuuden tarkistus ja täydennys (KRIITTINEN)

```
Tehtävä Cursorille: Varmista että kaikki init-templaten pykälän 11 vaatimat audit-tapahtumat kirjautuvat AINA.

Tausta: Init-templaten pykälä 11 listaa pakolliset audit-lokitapahtumat. Tarkistettavat (eivät välttämättä kirjaudu kaikilla poluilla):
- onnistunut kirjautuminen
- epäonnistunut kirjautuminen
- uloskirjautuminen
- salasanan vaihto
- 2FA käyttöönotto
- API-avaimen luonti
- API-avaimen poisto
- API-avaimen rotaatio (uusi)
- asetusten muutos (jokainen settings.set())
- käyttäjän luonti
- käyttäjän poisto
- roolin muutos
- varmuuskopion luonti
- varmuuskopion palautus
- sähköpostipohjan muutos

Vaihe 1: Inventaario
- Hae projektista kaikki audit_record-kutsut: grep -rn "audit_record\|AuditLog" app/
- Tee taulukko: tapahtuma → tiedosto → onnistuvatko KAIKKI polut (success+failure) lokitukseen?

Vaihe 2: Lisää puuttuvat
- Logout (app/auth/routes.py): lisää audit-kirjaus jokaiseen logout-poluun (action="auth.logout")
- Failed login (app/auth/services.py): varmista että action="auth.login_failed" kirjautuu AINA kun salasana on väärä, käyttäjä ei löydy, tai 2FA epäonnistuu
- Settings (app/settings/services.py): SettingsService.set() pitää AINA kirjata action="settings.update", target_id=<setting_key>, metadata={"old_value_redacted": <bool>, "new_value_redacted": <bool>} — jos is_secret=True, ÄLÄ tallenna arvoa metadataan
- Email template (app/email/services.py tai app/admin/routes.py jossa pohjia muokataan): action="email_template.update", target_id=<template_key>
- Käyttäjän roolin muutos (app/admin/services.py tai vastaava): action="user.role_changed", metadata={"old_role": "...", "new_role": "..."}

Vaihe 3: Audit-lokin sisällön validointi
- Tarkista että jokaisen audit_record-kutsu sisältää: user_id, action, target_type, target_id, ip_address, user_agent, metadata
- Jos jotkin puuttuvat (esim. ip_address) → korjaa kutsut käyttämään request-kontekstia (request.remote_addr, request.user_agent.string)
- Tee app/audit/services.py:hen audit_record()-helper joka hoitaa nämä automaattisesti requestista jos ne puuttuvat

Vaihe 4: Testit
- tests/test_audit.py: laajenna
- Jokaiselle pykälän 11 tapahtumalle yksi testi:
  - Suorita toimi (esim. login epäonnistuu)
  - Tarkista että AuditLog-taulussa on uusi rivi oikealla actionilla, user_id:llä, ip_addressilla, user_agentilla

Tiedostot:
- app/auth/routes.py (logout)
- app/auth/services.py (failed login)
- app/settings/services.py (settings.update)
- app/email/services.py tai routes (email_template.update)
- app/admin/services.py (user.role_changed, user.created, user.deleted)
- app/audit/services.py (helper-funktio)
- tests/test_audit.py

ÄLÄ:
- Älä tallenna salasanoja, tokeneita, plain-text API-avaimia tai is_secret=True -arvoja audit-lokin metadataan
- Älä tee audit-loki-kirjauksia routeissa — kutsu aina audit_record() service-kerroksesta
- Älä riko olemassa olevia testejä

Aja lopuksi: pytest tests/test_audit.py -v
Tarkista vielä: grep -n "audit_record\|AuditLog" app/**/*.py — varmista että jokainen pykälän 11 tapahtuma löytyy
```

---

## PROMPT 4 — Salaisuuksien skannaus ja ei-kovakoodattu-validointi (KRIITTINEN)

```
Tehtävä Cursorille: Varmista että koodissa ei ole kovakoodattuja salaisuuksia.

Tausta: Init-template kieltää absoluuttisesti kovakoodatut salaisuudet, API-avaimet, salasanat ja tuotantokonfiguraation. Kaikki pitää tulla .env-muuttujista.

Vaihe 1: Skannaus
Aja seuraavat komennot ja listaa löydökset:
1. git grep -nE "(api[_-]?key|secret|password|token|bearer)\\s*[:=]\\s*['\"][A-Za-z0-9_\\-]{8,}" -- ":!*.md" ":!.env.example" ":!tests/"
2. git grep -nE "https?://[^\\s]+:[^\\s]+@" — perustelaajalle ei salasanoja URL:eissa
3. git grep -nE "DATABASE_URL\\s*=\\s*['\"]postgresql://[^'\"]+@" — ei kovakoodattua DB-yhteyttä
4. git grep -nE "(sk_live|pk_live|whsec_)" — Stripe-avaimet
5. git grep -n "AKIA[A-Z0-9]\\{16\\}" — AWS-avaimet

Vaihe 2: Tarkista config.py
- app/config.py — käy läpi jokainen DefaultConfig/DevelopmentConfig/ProductionConfig kenttä
- Jokaisen pitää joko olla:
  - os.getenv("KEY") (puuttuessa None tai default joka ei ole salaisuus)
  - hardcodettu vain ei-salaisia oletusarvoja (esim. retention_days=30)
- ProductionConfigissa: SECRET_KEY, DATABASE_URL, MAILGUN_API_KEY ym. PITÄÄ heittää RuntimeError jos puuttuvat
- DevelopmentConfigissa: salli "dev-only-insecure-..." -placeholderit, mutta merkitse ne selvästi

Vaihe 3: .env.example tarkistus
- .env.example pitää sisältää KAIKKI vaaditut muuttujat (init-template pykälä 18):
  FLASK_ENV, SECRET_KEY, DATABASE_URL, MAILGUN_API_KEY, MAILGUN_DOMAIN, MAILGUN_FROM_EMAIL, MAILGUN_FROM_NAME, BACKUP_DIR, BACKUP_RETENTION_DAYS, API_RATE_LIMIT, LOGIN_RATE_LIMIT
- Kaikki arvot tyhjiä tai placeholdereita ("replace-me", "your-key-here") — EI oikeita arvoja
- Lisää kommentit kunkin yläpuolelle

Vaihe 4: Lokien sisältö
- Tarkista app/core/logging.py — onko maskaussuodatin (filter) joka piilottaa kentät: password, token, api_key, secret, authorization, x-api-key
- Jos ei → lisää RedactingFilter logging.Filter -aliluokkana ja kytke kaikkiin handler-objekteihin
- Testaa: tests/test_logging.py — varmista että logger.info("password=secret123") tuottaa "password=***"

Vaihe 5: Pre-commit hook (suositus)
- Lisää .pre-commit-config.yaml jos puuttuu, käytä detect-secrets tai gitleaks
- README.md:hen ohjeet pre-commit-asennukseen

Tiedostot:
- app/config.py (validointi)
- .env.example (täydellisyys)
- app/core/logging.py (maskaus)
- tests/test_logging.py (uusi)
- .pre-commit-config.yaml (uusi, suositus)
- README.md (asennusohje)

ÄLÄ:
- Älä poista DevelopmentConfigin "dev-only-insecure-..." -placeholderia (se on tarkoitus, RuntimeError prodissa estää käytön)
- Älä lisää oikeita arvoja .env.exampleen
- Älä jätä yhtään kovakoodattua avainta tai salasanaa

Aja lopuksi:
1. Toista vaiheen 1 grep-komennot — pitää palauttaa tyhjä
2. pytest tests/test_logging.py -v
3. flask run dev-tilassa — pitää käynnistyä (ei pakottavaa SECRET_KEYä)
4. FLASK_ENV=production flask run ilman SECRET_KEYtä — pitää heittää RuntimeError
```

---

## PROMPT 5 — ALV-käsittely laskuihin (TÄRKEÄ, laillisuus EU:ssa)

```
Tehtävä Cursorille: Lisää ALV-käsittely Invoice-malliin.

Tausta: Asiakkaan PMS-projekti laskuttaa, mutta Invoice-mallista puuttuu ALV-käsittely. Tämä ei ole laillinen EU:ssa. Toteuta init-templatea noudattaen.

Vaihe 1: Migraatio
- Aja: flask db migrate -m "add_vat_to_invoices"
- Lisää Invoice-malliin (app/billing/models.py):
  - vat_rate: db.Numeric(5,2), nullable=False, default=24.00
  - vat_amount: db.Numeric(12,2), nullable=False, default=0.00
  - subtotal_excl_vat: db.Numeric(12,2), nullable=False, default=0.00
  - total_incl_vat: db.Numeric(12,2), nullable=False, default=0.00
- Tarkista olemassa oleva Invoice.total — selvitä onko se "incl_vat" vai "excl_vat" → migraatio päivittää vanhojen rivien arvot oletetusti (esim. olemassa olevat rivit: subtotal_excl_vat = total / 1.24, vat_amount = total - subtotal, vat_rate = 24.00, total_incl_vat = total)
- Aja: flask db upgrade

Vaihe 2: Default ALV asetuksissa
- Lisää settings-tauluun seed-arvo (app/settings/seed_data.py):
  - key: "billing.default_vat_rate", value: "24.00", type: "decimal", description: "Oletus-ALV-kanta laskuille (%)", is_secret: False
- SettingsService.get() palauttaa tämän jos invoice ei eksplisiittisesti aseta vat_ratea

Vaihe 3: Service-kerros
- app/billing/services.py InvoiceService.create() ja .update():
  - Ottaa subtotal_excl_vat:n ja vat_raten parametreina
  - Laskee: vat_amount = round(subtotal_excl_vat * vat_rate / 100, 2)
  - Laskee: total_incl_vat = subtotal_excl_vat + vat_amount
  - Tallentaa kaikki neljä kenttää
- Varmista että legacy-koodi joka käyttää Invoice.total siirtyy käyttämään total_incl_vat (etsi: grep -rn "invoice.total\\|Invoice.total" app/)

Vaihe 4: API-skemat
- app/api/schemas.py — lisää InvoiceSchema-kentät: vat_rate, vat_amount, subtotal_excl_vat, total_incl_vat
- API-vastaus näyttää nyt erottelun

Vaihe 5: PDF/sähköposti-pohjat
- Päivitä invoice_created -sähköpostipohja näyttämään ALV erikseen
- Templates/admin/invoices/*.html — näyttämään ALV-sarakkeet

Vaihe 6: Testit
- tests/test_billing.py — uudet testit:
  - test_invoice_calculates_vat_correctly: subtotal=100, vat_rate=24 → vat_amount=24, total=124
  - test_invoice_uses_default_vat_when_not_specified: lue asetuksista
  - test_invoice_zero_vat: vat_rate=0 → vat_amount=0
  - test_legacy_invoice_migration: olemassa oleva rivi näyttää oikein

Tiedostot:
- app/billing/models.py (uudet kentät)
- app/billing/services.py (laskenta)
- app/settings/seed_data.py (default ALV)
- app/api/schemas.py (API-skema)
- migrations/versions/*.py (auto-generoitu)
- templates/admin/invoices/*.html (UI)
- app/email/seed_data.py (sähköpostipohja)
- tests/test_billing.py (testit)

ÄLÄ:
- Älä poista Invoice.total — tee siitä @hybrid_property joka palauttaa total_incl_vat (taaksepäin yhteensopivuus)
- Älä luota frontendin laskemaan ALV:hen — backend laskee aina
- Älä unohda audit-lokia: action="invoice.created" tai "invoice.updated" pitää sisältää metadata={"vat_rate": x, "total": y}

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_billing.py -v
3. Manuaalitesti: luo lasku admin-UI:sta, varmista että ALV näkyy
```

---

## PROMPT 6 — GDPR-CLI-komennot (TÄRKEÄ, laillisuus EU:ssa)

```
Tehtävä Cursorille: Lisää GDPR-komennot käyttäjien tietojen viemiselle, anonymisoinnille ja poistolle.

Tausta: GDPR (EU 2016/679) vaatii että käyttäjät saavat datansa, voivat anonymisoida ja poistaa sen. Toteutus init-templaten sääntöjen mukaan: service-kerros, audit-loki, oikeustarkistus.

Vaihe 1: Uusi moduuli
Luo app/gdpr/__init__.py ja app/gdpr/services.py.

Vaihe 2: Service-kerros (app/gdpr/services.py)
Kolme funktiota:

a) export_user_data(user_id) -> dict
- Etsi käyttäjä user_id:llä
- Kerää JSON-rakenne joka sisältää:
  - users: oma profiili (paitsi password_hash, totp_secret, backup_codes)
  - reservations: omat varaukset
  - invoices: omat laskut
  - guests: omat vieraat (jos käyttäjä on omistaja)
  - audit_log: omat audit-tapahtumat
- Palauta dict
- Audit: action="gdpr.export", target_type="user", target_id=user_id

b) anonymize_user_data(user_id) -> None
- Etsi käyttäjä
- Korvaa PII anonymisoiduilla arvoilla:
  - email = f"anonymized-{user_id}@deleted.local"
  - first_name = "Anonyymi"
  - last_name = "Käyttäjä"
  - phone = None
  - address = None
- Säilytä user_id ja organization_id (tilastoja varten)
- is_active = False
- Aseta anonymized_at = now()
- Audit: action="gdpr.anonymize", target_type="user", target_id=user_id
- ÄLÄ poista varauksia, laskuja tai audit-lokia (lailliset säilytysvaatimukset)

c) delete_user_data(user_id) -> None
- Vain superadmin saa kutsua
- Anonymisoi ensin (kutsuu anonymize_user_data)
- Poista user-rivi (cascade hoitaa loput jos suhteet ovat oikein)
- Audit: action="gdpr.delete", target_type="user", target_id=user_id (kirjaa ENNEN poistoa)
- Säilytä audit-loki — se ei ole PII-data lain mukaan kun anonymisoitu

Vaihe 3: User-malliin lisäys
- app/users/models.py — lisää sarake anonymized_at: db.DateTime, nullable=True
- Migraatio: flask db migrate -m "add_anonymized_at_to_users"

Vaihe 4: CLI-komennot (app/cli.py)
Kolme komentoa:

@cli.command("gdpr-export-user")
@click.option("--email", required=True)
@click.option("--output", default=None, help="Tiedosto johon JSON tallennetaan")
def gdpr_export_user(email, output):
    # hakee käyttäjän, kutsuu export_user_data, tallentaa tai tulostaa

@cli.command("gdpr-anonymize-user")
@click.option("--email", required=True)
@click.confirmation_option(prompt="Haluatko varmasti anonymisoida käyttäjän?")
def gdpr_anonymize_user(email):
    # hakee, kutsuu anonymize_user_data

@cli.command("gdpr-delete-user")
@click.option("--email", required=True)
@click.confirmation_option(prompt="POISTO ON LOPULLINEN. Haluatko varmasti?")
def gdpr_delete_user(email):
    # hakee, kutsuu delete_user_data

Vaihe 5: Admin-UI (vapaaehtoinen mutta suositeltu)
- app/admin/routes.py — uusi reitti /admin/gdpr/<user_id>
- Vain superadmin (tarkista permissions)
- Painikkeet: "Vie data" (lataa JSON), "Anonymisoi", "Poista"
- 2FA-vahvistus poistolle (kuten backup-restoressa)

Vaihe 6: Testit (tests/test_gdpr.py)
- test_export_user_data_returns_complete_json
- test_export_does_not_leak_password_hash
- test_export_does_not_leak_totp_secret
- test_anonymize_replaces_pii
- test_anonymize_preserves_invoices_and_audit_log
- test_delete_calls_anonymize_first
- test_delete_creates_audit_log_before_deletion
- test_cli_gdpr_commands_work

Tiedostot:
- app/gdpr/__init__.py (uusi)
- app/gdpr/services.py (uusi)
- app/users/models.py (anonymized_at)
- app/cli.py (kolme komentoa)
- app/admin/routes.py (UI vapaaehtoinen)
- migrations/versions/*.py (auto)
- tests/test_gdpr.py (uusi)

ÄLÄ:
- Älä poista audit-lokia GDPR-poistossa (lain mukaan se ei ole PII anonymisoinnin jälkeen)
- Älä unohda tarkistaa että vain superadmin saa kutsua delete-funktiota
- Älä vuoda password_hash, totp_secret, backup_codes, api_key_hash export-JSONiin
- Älä unohda audit-lokia kaikista kolmesta toimesta

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_gdpr.py -v
3. Manuaalitesti CLI:llä testikäyttäjällä
```

---

## PROMPT 7 — PDF-laskut/kuitit (TÄRKEÄ)

```
Tehtävä Cursorille: Lisää Invoice → PDF -generointi.

Tausta: PMS-asiakkaat tarvitsevat PDF-laskuja ja kuitteja. reportlab on todennäköisesti jo riippuvuuksissa.

Vaihe 1: Tarkista riippuvuudet
- requirements.txt — onko reportlab tai weasyprint? Jos ei, lisää reportlab>=4.0
- pip install -r requirements.txt

Vaihe 2: Service (app/billing/pdf.py — uusi tiedosto)
Funktio: generate_invoice_pdf(invoice_id) -> bytes
- Hae Invoice + Reservation + Guest + Property + Organization
- Käytä reportlab Platypus (SimpleDocTemplate) tai HTML→PDF (jos weasyprint)
- Sisältö:
  - Yläosa: Organization-tiedot (nimi, osoite, Y-tunnus, sähköposti, puhelin) — hae settingsistä
  - Otsikko: "LASKU" / "KUITTI"
  - Laskun numero, päiväys, eräpäivä
  - Asiakkaan tiedot (Guest)
  - Rivit: kuvaus, määrä, à-hinta, alv-%, summa
  - Yhteenveto: subtotal_excl_vat, vat_amount, total_incl_vat
  - Maksuohjeet (IBAN, viite) — settingsistä
  - Alaosa: Y-tunnus, ALV-tunnus
- Palauta PDF byte-jonona

Vaihe 3: Reitit
- app/admin/routes.py: GET /admin/invoices/<int:invoice_id>/pdf
  - Vaatii admin-roolin
  - Tarkistaa että invoice.organization_id == current_user.organization_id (paitsi superadmin näkee kaikki)
  - Palauttaa send_file(BytesIO(pdf_bytes), mimetype="application/pdf", as_attachment=True, download_name=f"lasku-{invoice.number}.pdf")
- app/api/routes.py: GET /api/v1/invoices/<int:invoice_id>/pdf
  - @scope_required("invoices:read")
  - Sama tarkistus tenant-isolaatiosta

Vaihe 4: Audit-loki
- Joka kerta kun PDF generoidaan: action="invoice.pdf_downloaded", target_type="invoice", target_id=invoice_id

Vaihe 5: Testit (tests/test_invoice_pdf.py)
- test_generate_pdf_returns_bytes
- test_pdf_contains_invoice_number
- test_pdf_contains_vat_breakdown
- test_admin_route_requires_login
- test_admin_route_tenant_isolation (admin toisessa orgissa → 403)
- test_api_route_requires_scope
- test_audit_log_created_on_download

Tiedostot:
- requirements.txt (reportlab jos puuttuu)
- app/billing/pdf.py (uusi, service)
- app/admin/routes.py (UI-reitti)
- app/api/routes.py (API-reitti)
- tests/test_invoice_pdf.py (uusi)

ÄLÄ:
- Älä generoi PDF:ää routessa — kaikki logiikka servicessä
- Älä unohda tenant-isolaatiota
- Älä unohda scope-vaatimusta API-puolella
- Älä cachee PDF:ää tiedostojärjestelmään pysyvästi (luo aina lennossa, helpompi GDPR-mielessä)

Aja lopuksi:
1. pytest tests/test_invoice_pdf.py -v
2. Manuaalitesti: luo lasku, lataa PDF admin-UI:sta, avaa
3. Tarkista että PDF näyttää oikein ja sisältää kaikki tiedot
```

---

## PROMPT 8 — Stripe-maksuintegraatio (TÄRKEÄ)

```
Tehtävä Cursorille: Lisää Stripe-maksuintegraatio Invoice-malliin.

Tausta: PMS-asiakkaat tarvitsevat verkkomaksun. Stripe ensin (Visma Pay myöhemmin samalla rakenteella).

Vaihe 1: Riippuvuus
- requirements.txt: lisää stripe>=8.0

Vaihe 2: Env-muuttujat
- .env.example — lisää:
  STRIPE_SECRET_KEY=
  STRIPE_PUBLISHABLE_KEY=
  STRIPE_WEBHOOK_SECRET=
  STRIPE_ENABLED=false
- app/config.py — lisää vastaavat config-kentät, ProductionConfig vaatii kun STRIPE_ENABLED=true

Vaihe 3: Uusi moduuli (app/payments/)
Tiedostot:
- app/payments/__init__.py
- app/payments/models.py — Payment-malli:
  - id, organization_id, invoice_id (FK), provider ("stripe"), provider_payment_id, amount, currency, status (pending/succeeded/failed/refunded), created_at, updated_at, metadata (JSON)
- app/payments/services.py:
  - create_stripe_checkout_session(invoice_id) -> stripe Session
  - handle_stripe_webhook(payload, signature) -> None
  - mark_invoice_paid(payment) -> None
- app/payments/routes.py:
  - POST /api/v1/payments/stripe/checkout — luo checkout-istunnon (vaatii @scope_required("payments:create"))
  - POST /api/v1/payments/webhook/stripe — webhook-vastaanotto, ÄLÄ vaadi API-avainta vaan VARMENNA stripe-allekirjoitus

Vaihe 4: Webhook-logiikka
- Käytä stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
- Käsittele tapahtumat:
  - checkout.session.completed → mark_invoice_paid
  - payment_intent.payment_failed → log + audit
  - charge.refunded → update Payment.status="refunded"
- Audit: action="payment.received" / "payment.failed" / "payment.refunded"
- Idempotenssi: tarkista että provider_payment_id ei ole jo käsitelty

Vaihe 5: Migraatio
- flask db migrate -m "add_payments_table"
- flask db upgrade

Vaihe 6: Invoice-mallin päivitys
- Lisää Invoice.payment_status (unpaid/partial/paid/refunded) — laskettu kentästä payments-suhteesta
- Lisää Invoice.payments backref

Vaihe 7: Testit (tests/test_payments.py)
- test_checkout_session_creation_requires_scope
- test_webhook_rejects_invalid_signature
- test_webhook_marks_invoice_paid_on_success
- test_webhook_is_idempotent
- test_audit_log_for_payment_events
- test_stripe_disabled_returns_503

Vaihe 8: Admin-UI
- Invoice-näkymässä "Lähetä maksulinkki" -painike (jos STRIPE_ENABLED)
- Maksun status näkyviin
- Vain admin/superadmin näkee

Tiedostot:
- requirements.txt (stripe)
- .env.example (avaimet)
- app/config.py (config)
- app/payments/__init__.py, models.py, services.py, routes.py (uudet)
- app/billing/models.py (payment_status)
- app/admin/routes.py (UI-laajennus)
- migrations/versions/*.py (auto)
- tests/test_payments.py (uusi)

ÄLÄ:
- Älä koskaan kovakoodaa Stripe-avaimia
- Älä luota webhookin payloadiin ilman allekirjoituksen varmennusta
- Älä unohda idempotenssia (Stripe lähettää webhookit useita kertoja)
- Älä unohda audit-lokia
- Älä tee suoraa maksuprosessointia ilman Stripe Checkoutia (PCI-vaatimukset)

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_payments.py -v
3. Stripe CLI test: stripe listen --forward-to localhost:5000/api/v1/payments/webhook/stripe
4. Stripe-testikorttilla maksu testitilassa
```

---

## PROMPT 9 — Pikatarkistus: route-handlerit ohuet, logiikka servicessä (TÄRKEÄ)

```
Tehtävä Cursorille: Tarkista että routet eivät sisällä raskasta liiketoimintalogiikkaa.

Tausta: Init-templaten pykälä 20 sanoo: "Routeissa ei saa olla raskasta liiketoimintalogiikkaa." Käy läpi kaikki routet.

Vaihe 1: Skannaus
- Tiedostot: app/auth/routes.py, app/admin/routes.py, app/api/routes.py, app/backups/routes.py, app/portal/routes.py, app/owner_portal/routes.py
- Jokaisesta routesta:
  - Laske rivit (def-rivien välistä, ilman dekoraattoreita ja docstringeja)
  - Jos route on yli 20 riviä TAI sisältää db.session.add/db.session.commit/raakoja db-kyselyitä → siirrä logiikka service-kerrokseen
  - Routen pitäisi olla: hae input → kutsu service → muotoile response

Vaihe 2: Refaktorointi
- Jokainen löytyvä raskas route:
  - Luo vastaava service-funktio (esim. app/admin/services.py UserService.create_user_with_invitation())
  - Routessa jää: parse form/json → kutsu service → return response/redirect
  - Service tekee: validointi (pl. WTF), tietokannan kutsu, audit-loki, sähköposti

Vaihe 3: Decorator-järjestys
Varmista että kaikkien admin-routejen päällä on:
@bp.route(...)
@login_required
@require_admin_pms_access  # tai vastaava
def view():

API-routejen päällä:
@bp.route(...)
@require_api_key  # tai vastaava (tämä asettaa g.api_key)
@scope_required("...")
def view():

Vaihe 4: Testit
- Tarkista että olemassa olevat testit menevät edelleen läpi (refaktorointi ei saa muuttaa toiminnallisuutta)
- Lisää service-funktioille suorat unit-testit (tests/test_<module>_services.py)

Tiedostot:
- Mahdollisesti useat (riippuu skannauksen tuloksista)
- Lähinnä: app/auth/routes.py + services.py, app/admin/routes.py + services.py, app/api/routes.py + services.py

ÄLÄ:
- Älä muuta API-vastausten muotoa (taaksepäin yhteensopivuus)
- Älä unohda siirtää audit-lokia mukana
- Älä riko olemassa olevia testejä

Aja lopuksi:
1. pytest -v (kaikki menee läpi)
2. Tee uusi grep: grep -n "db.session.add\\|db.session.commit\\|db.session.delete" app/*/routes.py — ei pitäisi enää löytyä mitään
```

---

## PROMPT 10 — Testaus & coverage (KRIITTINEN ennen hyväksyntää)

```
Tehtävä Cursorille: Aja kaikki testit, korjaa epäonnistuvat ja varmista 80 % coverage.

Tausta: Init-template pykälä 22: "testit menevät läpi". pytest.ini sisältää --cov-fail-under=80.

Vaihe 1: Aja testit
pytest -v --cov=app --cov-report=term-missing

Vaihe 2: Korjaa epäonnistuvat
- Käy läpi jokainen FAIL/ERROR
- Päätä: onko testi väärä vai koodi väärä?
- Jos koodi väärä: korjaa koodi ÄLÄKÄ heikennä testiä
- Jos testi väärä: korjaa testi mutta ymmärrä miksi se oli väärin

Vaihe 3: Coverage alle 80 %
- Katso missing-rivit
- Lisää testit kriittisille puuttuville haaroille:
  - Erityisesti: virheenkäsittely, oikeustarkistus, audit-lokin kirjautuminen
  - Älä testaa "vain päästäksesi prosenttiin" — testaa toiminnallisuutta

Vaihe 4: Init-template pykälän 16 vaaditut testit
Varmista että nämä testit ovat olemassa ja menevät läpi:
- käyttäjän luonti
- onnistunut kirjautuminen
- epäonnistunut kirjautuminen
- superadmin 2FA -vaatimus
- API-avain-autentikointi
- API:n virhevastaukset
- sähköpostipohjan renderöinti
- varmuuskopion luonti
- oikeustarkistukset

Vaihe 5: Lopullinen ajo
pytest -v --cov=app --cov-fail-under=80
- Pitää näyttää: passed, ei failed, coverage ≥ 80 %

Tiedostot:
- tests/* (uudet ja korjatut testit)
- mahdollisesti koodi-tiedostot jos virheitä korjataan

ÄLÄ:
- Älä laita testejä pytest.skip-tilaan vain läpäisyn vuoksi
- Älä laske coverage-vaatimusta alle 80 %
- Älä mockkaa testejä siten että ne menevät aina läpi (esim. mockkaa db.session — testaa oikealla SQLite-tiedostokannalla)

Aja lopuksi:
1. pytest -v --cov=app --cov-fail-under=80
2. Listaa testit jotka oli lisätty/korjattu
```

---

## PROMPT 11 — Lopullinen tarkistuslista ja README-päivitys (HYVÄKSYNTÄ)

```
Tehtävä Cursorille: Käy hyväksymiskriteerit (pykälä 22) läpi yksi kerrallaan, korjaa puutteet, päivitä README.

Tausta: Init-templaten pykälä 22 listaa hyväksymiskriteerit. Sovellus voidaan hyväksyä vasta kun kaikki täyttyvät.

Vaihe 1: Käy läpi kriteerit
Tee taulukko, merkitse kunkin osalta status (✅/⚠️/❌) + perustelu + korjaus:

1. sovellus käynnistyy yhdellä komennolla → testaa: docker-compose up
2. tietokantamigraatiot toimivat → flask db upgrade
3. superadmin voidaan luoda komentoriviltä → flask create-superadmin
4. superadmin ei voi käyttää kriittisiä toimintoja ilman 2FA:ta → manuaalitesti
5. API toimii API-avaimella → curl -H "Authorization: Bearer <key>" /api/v1/me
6. API-avain ei tallennu selväkielisenä → SELECT * FROM api_keys → vain hash
7. Mailgun-testiviesti lähtee → flask send-test-email
8. sähköpostipohjia voi muokata → admin-UI manuaalitesti
9. päivittäinen backup toimii → varmista APScheduler-job (tai aja flask backup-create)
10. backup voidaan palauttaa hallitusti → flask backup-restore (testiympäristössä)
11. audit-loki tallentaa kriittiset tapahtumat → SELECT * FROM audit_log
12. testit menevät läpi → pytest -v
13. README kertoo miten sovellus otetaan käyttöön → lue README

Vaihe 2: Korjaa puutteet
- Jokaiselle ⚠️/❌-kriteerille tee minimikorjaus

Vaihe 3: Päivitä README.md
Init-template pykälä 17 vaatii että README sisältää:
- Sovelluksen tarkoitus
- Asennusohje
- Ympäristömuuttujat (linkki .env.exampleen)
- Kehitysympäristön käynnistys
- Tietokantamigraatiot
- Testien ajo
- API-dokumentaatio (linkki /api/v1/docs jos olemassa, muuten OpenAPI/Swagger)
- Varmuuskopioiden käyttö
- Superadminin luonti
- Hyväksymiskriteerien tarkistus

Lisää README:hen:
- "Quick start" (3 komentoa: clone, docker-compose up, flask create-superadmin)
- "Manual testing" (lyhyt lista käsin tarkistettavia asioita)

Vaihe 4: Versionhallinta
- git status — listaa kaikki muutetut/uudet tiedostot
- Tee commit järkevillä viesteillä
- Tee tag v1.0.0 jos kaikki kriteerit täyttyvät

Tiedostot:
- README.md (päivitys)
- mahdollisesti useita koodi-tiedostoja korjauksiin

ÄLÄ:
- Älä merkitse kriteeriä ✅ jos et ole oikeasti testannut sitä
- Älä jätä TODO-kommentteja koodiin

Lopputulos:
- Lähetä Claudelle taulukko kaikkien 13 kriteerin tilasta
- Liitä mukaan: "pytest -v" -ajo täysin vihreänä
- Liitä mukaan: päivitetty README.md
```

---

## TYÖSKENTELYJÄRJESTYS (suositus)

Älä tee kaikkia samaan aikaan. Tee tässä järjestyksessä:

1. **Prompt 0** — alustus ChatGPT:lle
2. **Prompt 1** — rotate-api-key (nopein, KRIITTINEN)
3. **Prompt 2** — API-scope (KRIITTINEN, vie eniten aikaa kriittisistä)
4. **Prompt 3** — audit-loki (KRIITTINEN)
5. **Prompt 4** — salaisuuksien skannaus (KRIITTINEN, nopea)
6. **Prompt 9** — route-handlerien tarkistus (TÄRKEÄ refaktorointi)
7. **Prompt 10** — testit menevät läpi (KRIITTINEN ennen hyväksyntää)
8. **Prompt 11** — hyväksymiskriteerit + README (HYVÄKSYNTÄ)

Vasta tämän jälkeen PMS-laajennukset:

9. **Prompt 5** — ALV (TÄRKEÄ, laillisuus)
10. **Prompt 6** — GDPR (TÄRKEÄ, laillisuus)
11. **Prompt 7** — PDF-laskut (TÄRKEÄ)
12. **Prompt 8** — Stripe (TÄRKEÄ)

> Muista: Cursorin pitää pysyä jokaisessa vaiheessa init-templaten säännöissä. Jos joku Cursor-ehdotus rikkoo sääntöjä → palauta Claudelle tarkistettavaksi ennen toteutusta.
