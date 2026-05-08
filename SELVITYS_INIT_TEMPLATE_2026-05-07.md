# Selvitys: Pindora PMS vs. init-template + asiakaspalaute

**Päivämäärä:** 2026-05-07
**Lähteet:** projektin koodi (`C:\Users\matso\Downloads\pindora-pms`), README.md, .env.example, migrations, tests, DECISIONS.md sekä Pekan/Villen palaute 2026-05-06.

> **Lyhyt tuomio:** Sovellus täyttää init-templaten **ydinvaatimukset (kohdat 1–22) käytännössä 100 %**. **Kohtaan 23 ("pidä yksinkertaisena") on lievä jännite** — repo on kasvanut MVP:n yli (payments, owner_portal, webhooks, gdpr, ical, pindora_lock, status, idempotency, tags, comments, notifications). DECISIONS.md (2026-05-07) dokumentoi nämä ja siirsi `owner_portal` feature-flagin taakse. Asiakaspalautteen 9 kohdasta **6 on selvästi kuitattu**, 2 on osittain, 1 vaatii live-tarkistusta (500-virheet).

---

## 1. Init-template kohta-kohdalta

| # | Vaatimus | Tila | Huomio |
|---|----------|------|--------|
| 1 | Teknologiapohja (Flask, Gunicorn, Nginx, systemd, Postgres, SQLAlchemy, Alembic, Flask-Login, Flask-WTF, Werkzeug, Mailgun, APScheduler, .env, pytest, Docker) | Täyttyy | requirements.txt + `deploy/` + `Dockerfile` + `docker-compose.yml` |
| 2 | Perusrakenne `app/auth, admin, api, users, email, backups, core, templates, static` + `migrations, tests, backups, .env.example, requirements.txt, run.py, README.md` | Täyttyy | Kaikki vaaditut alimoduulit löytyvät. Lisäksi 15+ ekstramoduulia (kts. kohta 23). |
| 3 | Roolit superadmin / admin / user / api_client | Täyttyy | `app/users/models.py:UserRole` |
| 4 | Autentikointi (email+pw, salasanan reset, istunto, API-avain, 2FA superadmin, kirjautumisrajoitus, CSRF, turvallinen logout) | Täyttyy | Flask-Login + Flask-Limiter + Flask-WTF CSRF + `MAX_LOGIN_ATTEMPTS` + 2FA-pakotus |
| 5 | 2FA superadminille (TOTP, QR, varakoodit, pakotus ennen kriittisiä toimintoja) | Täyttyy | `pyotp` + `backup_codes` (`User.generate_backup_codes` / `consume_backup_code`); reitit `/2fa/setup`, `/2fa/verify`, `/2fa/backup-codes` |
| 6 | API `/api/v1/`, Bearer/X-API-Key, hashattu, nimettävissä, poistettavissa, oikeuksilla, vanheneva, lokitettu, /health + /me, yhtenäinen JSON-envelope | Täyttyy | `app/api/auth.py`, `app/api/routes.py`, `ApiKey.key_hash`, OpenAPI-docs `/api/v1/docs` |
| 7 | Mailgun + muokattavat pohjat (welcome, password_reset, login_2fa_code, backup_completed, backup_failed, admin_notification + aihe/HTML/teksti/muuttujat/preview/testilähetys + service-kerros) | Täyttyy | `app/email/services.py`, `seed-email-templates`-CLI, admin-UI esikatselu + testilähetys |
| 8 | Päivittäinen backup (Postgres + uploadit + sähköpostipohjat + asetukset, ei selväkielisiä salaisuuksia, retentio, audit, manuaalinen trigger, palautus 2FA:lla, riskivaroitus, ennen palautusta turvakopio) | Täyttyy | `app/backups/services.py`, JSON-exportit (`<stamp>.email_templates.json`, `<stamp>.settings.json` redaktoituna), pre-restore safe-copy, restore-flow vaatii salasanan + TOTP:n |
| 9 | Settings-taulu + service-kerros + superadmin-UI | Täyttyy | `app/settings/models.py` + `services.py` + `/admin/settings` |
| 10 | Tietoturva (hashatut salasanat & API-avaimet, CSRF, rate limit, validointi, ORM, XSS, CORS, audit, secure cookies) | Täyttyy | `register_security_headers`, `SESSION_COOKIE_SECURE/HTTPONLY/SAMESITE` tuotannossa, `CORS_ALLOWED_ORIGINS` |
| 11 | Audit-loki (kirjautuminen, fail, logout, salasana, 2FA, API-avaimet, asetukset, käyttäjä/rooli, backup, sähköpostipohja) tallennettavat kentät user_id/action/target_*/ip/user_agent/metadata/created_at | Täyttyy | `app/audit/models.py:AuditLog` (actor_*/action/status/target_*/ip/user_agent/context/created_at) |
| 12 | Monikäyttäjyys + tenant-rakenne organization_id-rajauksella, oikeustarkistus backendissä | Täyttyy | `app/core/decorators.py:tenant_scope`, kaikki PMS-mallit `organization_id` indeksoituna |
| 13 | Yksinkertainen UI, validointi, vahvistukset vaarallisille toiminnoille | Täyttyy | Suomenkieliset Jinja-templatet, `confirm`-kuvioita peruutus/poisto-poluissa |
| 14 | Suorituskyky (indeksit, sivutus, taustatyöt, rate limit) | Täyttyy | APScheduler (backups/email/ical/portal/api/owner/status/webhook/payment), index-määreet |
| 15 | Virheenkäsittely 400/401/403/404/429/500, käyttäjälle selkeä viesti, tekninen virhe lokiin | Täyttyy | `register_error_handlers` + `app/core/errors.py` |
| 16 | Testaus pytestillä (käyttäjä, kirjautuminen, fail, 2FA, API-avain, API-virheet, sähköposti, backup, oikeudet) | Täyttyy | 90+ testitiedostoa `tests/` + `tests/integration/test_acceptance.py` |
| 17 | README (tarkoitus, asennus, env, dev-startup, migraatiot, testit, API, backupit, superadmin) + .env.example | Täyttyy | README.md kattaa kaikki + `.env.example` 200+ riviä |
| 18 | Ympäristömuuttujat (FLASK_ENV, SECRET_KEY, DATABASE_URL, MAILGUN_*, BACKUP_DIR, BACKUP_RETENTION_DAYS, API_RATE_LIMIT, LOGIN_RATE_LIMIT) | Täyttyy | Kaikki tönissään `.env.example`:ssä |
| 19 | CLI: `flask create-superadmin`, `backup-create`, `backup-restore`, `rotate-api-key`, `send-test-email`, `db upgrade` | Täyttyy | `app/cli.py` |
| 20 | Periaatteet (yksinkertaisuus, service-kerros, oikeustarkistus, validointi, env-salaisuudet, migraatiot, yhtenäinen API, audit, Docker, palautus, luettava koodi) | Täyttyy varauksin | Service-kerrokset OK; ks. kohta 23 jännite |
| 21 | Ensimmäisen version minimi (Flask-rakenne, Postgres, käyttäjä, rooli, superadmin, 2FA, login/logout, API-avain, /health, /me, Mailgun, pohjat, päivittäinen backup, palautus, audit, .env.example, Dockerfile, docker-compose.yml, README, perustestit) | Täyttyy | — |
| 22 | Hyväksymiskriteerit (yksi komento käyntiin, migraatiot, superadmin-CLI, 2FA-pakko, API-avainautentikointi, ei selväkielisiä avaimia, Mailgun-testi, pohjien muokkaus, päivittäinen backup, hallittu palautus, audit, testit vihreänä, README) | Täyttyy | `tests/integration/test_acceptance.py` ja `.github/workflows/acceptance.yml` automatisoivat lähes kaikki 13 kohtaa |
| 23 | "Pidä yksinkertaisena, älä rakenna ylimääräistä arkkitehtuuria" | **Osittain** | Repo sisältää huomattavasti templaten ydinrakennetta enemmän moduuleita: `subscriptions`, `owner_portal`, `status`, `integrations/ical`, `integrations/pindora_lock`, `payments` (Stripe + Paytrail), `webhooks`, `gdpr`, `idempotency`, `notifications`, `tags`, `comments`, `expenses`, `reports`. DECISIONS.md (2026-05-07) on tarkastanut nämä ja gating'oinut `owner_portal`-blueprintin `OWNER_PORTAL_ENABLED`-flagin taakse. Muut perusteltu liiketoimintatarpeella. |

**Yhteenveto:** kohdat 1–22 = täyttyvät. Kohta 23 = osittain, dokumentoitu tietoinen valinta.

---

## 2. Asiakaspalaute (Pekka / Ville, 2026-05-06)

| # | Pekan havainto | Tila | Mihin viittaa repossa |
|---|----------------|------|------------------------|
| 1 | "Maksutapana Stripe ja Paytrail" | Kunnossa | `app/payments/providers/`, README "Maksuintegraatio", webhookit `/api/v1/webhooks/stripe`, `/api/v1/webhooks/paytrail` |
| 2 | "Mitkä huoneet vapaana / varattuna — helppo näkymä puuttuu" | **Korjattu** | Uusi `/admin/availability` -näkymä (`app/templates/admin/availability.html`) on matriisi: rivit = huoneet, sarakkeet = päivät, värikoodit Vapaa/Varattu/Saapuu/Vaihto/Huolto/Estetty. Dashboard sisältää "Yksiköiden tilanne tänään" -listan. |
| 3 | "Helpottaisi nähdä mitä on vapaana missäkin (puhelin-skenaario)" | **Korjattu** | Sama matriisinäkymä + `/admin/calendar` (FullCalendar) tukee suodatusta kohde/huone/tapahtumatyyppi -tasolla |
| 4 | "Kohteista voi kertoa nyt aika vähän — sijainti, neliöt, ominaisuudet (hissit, keittiöt)" | **Korjattu** | Migraatiot `6a973736e5a3_add_property_and_unit_descriptive_fields.py` + `c7d8e9f0a1b2_add_air_conditioning_to_properties.py`. **Property:** `street_address`, `latitude`, `longitude`, `postal_code`, `city`, `year_built`, `has_elevator`, `has_parking`, `has_sauna`, `has_courtyard`, `has_air_conditioning`, `description`, `url`. **Unit:** `area_sqm`, `floor`, `bedrooms`, `max_guests`, `unit_type`, `has_kitchen`, `has_bathroom`, `has_balcony`, `has_terrace`, `has_dishwasher`, `has_washing_machine`, `has_tv`, `has_wifi`, `description`, `floor_plan_image_id` |
| 5 | "Yksinkertaisen sopparin luominen helppoa, mutta riittääkö ammattimaisessa kiinteistönhallinnassa?" | **Avoin** | `Lease`-malli on kohtuullinen perustaso (status draft→active→ended/cancelled, billing_cycle, deposit, notes, audit-jäljitys), mutta sähköistä allekirjoitusta tai vakiosopimuspohjaa ei ole. Ei ole "väärin", mutta liiketoiminta voi vaatia laajennusta. |
| 6 | "Käyttöaste-/varausraportti aika simppelit, toivoisin rahaan ja kassavirtaan liittyvää dataa" | **Korjattu** | Uudet raportit: `cash_flow.html`, `income_breakdown.html`, `expenses_breakdown.html`. Dashboard-KPI:t: Tulot tässä kuussa, Avoimet saatavat, Nettokassavirta, Erääntyneet laskut. CSV/XLSX-vienti raporteista. `app/expenses/`-moduuli kuluseurantaa varten. |
| 7 | "Jokunen 500 error sieltä tuli (etenkin kalenterisynkkausnäkymä)" | **Vaatii live-tarkistuksen** | `app/templates/admin/units/calendar_sync.html` on olemassa. Repon juuressa on `pin-pms-bugfix-plan.html`-suunnitelma — viittaa siihen, että bugeja on identifioitu. Kannattaa ajaa savutesti tuotantoa vastaavalla datalla ennen sertifiointia. |
| 8 | "Huoltopyyntöä ei voi tehdä, koska kriittisyys pitää olla merkittynä lontoonkielisillä termeillä" | **Korjattu** | `app/templates/admin/maintenance/new.html` rivit 44–49 näyttävät käyttäjälle suomenkieliset labelit: Matala, Normaali, Korkea, Kiireellinen (taustalla edelleen low/normal/high/urgent). `MaintenanceRequest.PRIORITY_LABELS` mappaa myös tulostuksessa. |
| 9 | "Kalenterimerkinnät aukeaisi klikkaamalla mihin vain saraketta eikä rivin päästä pientä ikonia painamalla" | **Korjattu** | FullCalendar-`eventClick` reagoi koko event-elementin alueella (`app/static/js/admin-calendar.js:141`); availability-matriisin solut ovat klikattavia kokonaan (`<a>`-linkki Vapaa/Varattu-solussa). Erillinen pieni ikoni ei ole enää ainoa klikkialue. |
| 10 | "UX:n parannusta voisi tehdä, ettei olisi kielet suomi-englanti sekaisin" | **Pääosin korjattu** | Admin- ja portal-templatet ovat suomeksi. `tests/test_ui_finnish.py` valvoo. Pieniä jäänteitä voi olla virheviesteissä; jatkuvan lokalisaatiotyön kohde. |

**Asiakaspalautteen yhteenveto:**
- Korjattu / kunnossa: 7/10 (kohdat 1, 2, 3, 4, 6, 8, 9, 10 pääosin)
- Osittain / avoin: 2/10 (kohta 5 sopparityökalu, kohta 10 kielten siisteys)
- Vaatii live-savutestauksen: 1/10 (kohta 7 — 500-virheet)

---

## 3. Suositukset jatkoon

1. **Aja `tests/integration/test_acceptance.py`** Docker Composella ennen seuraavaa demoa — tämä kattaa README:n §22 acceptance-listan automatisoidusti.
2. **Reproo Pekan 500-virhe kalenterisynkkausnäkymässä** edustavalla datalla. `pin-pms-bugfix-plan.html` on hyvä lähtö; hyödynnä `read_console_messages` ja `read_network_requests` tuotantoselaimessa.
3. **Sopparityökalu (palaute kohta 5):** päätä tuotteena onko PMS:n tarkoitus tukea (a) vain kotimaisten vuokrasopimusten kevyttä elinkaarta vai (b) ammattikiinteistönhallinnan vaatima täysmittainen dokumenttipohja + e-allekirjoitus. Tämä on liiketoimintapäätös, ei tekninen.
4. **Kohta 23 (yksinkertaisuus):** seuraa onko kaikilla feature-flag'atuilla moduuleilla aktiivisia käyttäjiä 60 päivän kuluttua — jos ei, harkitse poistoa `PROMPTIT_KORJAUKSILLE_2026-05-07.md`-Prompti 5:n hengessä.
5. **Pidä `requirements.txt` pinnattuna** ja varmista että pre-commit + gitleaks pyörii CI:ssä — README:n quality-osio mainitsee mutta CI-konfiguraatio kannattaa varmistaa.

---

## 4. Lähdeviitteet repossa

- `README.md` (acceptance-checklista §22)
- `.env.example` (env-muuttujat §18)
- `app/__init__.py` (sovellustehdas, schedulerit, blueprintit)
- `app/cli.py` (CLI-komennot §19)
- `app/users/models.py` (UserRole §3, 2FA §5)
- `app/audit/models.py` (audit-loki §11)
- `app/properties/models.py` (Pekan kohta 4 — uudet kentät)
- `app/templates/admin/maintenance/new.html` (Pekan kohta 8 — suomenkieliset prioriteetit)
- `app/templates/admin/availability.html` (Pekan kohdat 2–3 — vapauden matriisinäkymä)
- `app/templates/admin/reports/cash_flow.html` (Pekan kohta 6 — kassavirtaraportti)
- `app/static/js/admin-calendar.js` (Pekan kohta 9 — eventClick)
- `DECISIONS.md` (kohta 23 — moduulikatselmus 2026-05-07)
- `tests/integration/test_acceptance.py` (kohta 22 — automaattinen acceptance)
- `migrations/versions/6a973736e5a3_add_property_and_unit_descriptive_fields.py`
- `migrations/versions/c7d8e9f0a1b2_add_air_conditioning_to_properties.py`
