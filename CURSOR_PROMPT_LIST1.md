# Cursor-prompt: Pin PMS – täytä asiakkaan init-template (Lista 1)

> Kopioi alla oleva prompt sellaisenaan Cursoriin (Composer / Agent / Chat).
> Suosittelen ajamaan tehtävät yksi osio kerrallaan, ei kerralla — näin
> reviewaaminen on helpompaa ja diffit pysyvät kohtuullisina.

---

## PROMPT ALKAA

Olet työskentelemässä `pindora-pms`-projektissa. Tämä on Flask-pohjainen monitenanttinen Property Management System. Projektin lähtökohtana on asiakkaan oma "Sovelluskehityksen init-template", ja sovellus on noin 90 % siitä jo valmiina. Tehtäväsi on viedä projekti loppuun siltä osin, mikä init-templatesta vielä puuttuu tai on osittain toteutettu.

**Tärkeät pelisäännöt koko ajalle:**

- Älä riko olemassaolevaa toiminnallisuutta. Kaikki nykyiset testit (`pytest -q`) pitää mennä läpi muutostesi jälkeen.
- Kaikki uudet ominaisuudet tarvitsevat pytest-testit `tests/`-kansioon.
- Liiketoimintalogiikka kuuluu `services.py`-kerrokseen, ei routeihin.
- Kaikki kriittiset toiminnot (käyttäjäluonti, role-muutokset, varmuuskopiot, asetukset, sähköpostipohjat) **pitää** kirjoittaa audit-lokiin `audit_record(...)`-kutsulla.
- Tenant-eristys: kaikki kyselyt rajataan aina `organization_id`:n mukaan.
- Älä lisää uusia kovakoodattuja salaisuuksia. Käytä `os.getenv` / `app.config`.
- Kaikki uudet ympäristömuuttujat lisätään `.env.example`:een kommentin kera.
- Jokainen muutos pitää olla yksittäinen looginen commit, jonka viesti kuvaa "mitä ja miksi" — älä niputa kaikkia tehtäviä yhteen.
- Tee migraatio (`flask db migrate -m "..."` + tarkista käsin) jokaisesta tietokantamuutoksesta.

**Lue ensin nämä tiedostot saadaksesi kontekstin:**

- `README.md`
- `app/__init__.py`
- `app/config.py`
- `app/cli.py`
- `app/extensions.py`
- `app/users/models.py`
- `app/audit/services.py`
- `app/email/services.py` ja `app/email/seed_data.py`
- `app/backups/services.py`

Tee tehtävät seuraavassa järjestyksessä. Älä mene seuraavaan ennen kuin edellinen on testattu ja committed.

---

### Tehtävä 1 — Luo `app/users/services.py` ja siirrä käyttäjälogiikka sinne

Tällä hetkellä käyttäjälogiikkaa on hajallaan `app/cli.py`:ssä (`_create_user`) ja `app/admin/services.py`:ssä. Init-template (osio 2 + 20) edellyttää oman service-kerroksen.

- Luo `app/users/services.py`.
- Siirrä `_create_user`-funktio `cli.py`:stä sinne nimellä `create_user(...)`. Säilytä validointi, organisaation `get_or_create`, audit-lokitus, `user.id`-flush.
- Lisää `create_user`-funktion sisään automaattinen `welcome_email`-lähetys uudelle käyttäjälle (ks. tehtävä 5 — voit aluksi kutsua `send_template`a synkronisesti, taustatyö-kerros tulee myöhemmin). Lähetys saa epäonnistua hiljaa ja kirjautua varoituksena lokiin — käyttäjän luonti ei saa kaatua siihen.
- Lisää myös: `update_user_role`, `deactivate_user`, `reactivate_user`, `change_password`. Kaikki kirjoittavat audit-logiin (`role_changed`, `user.deactivated`, `user.reactivated`, `password_changed`).
- Päivitä `cli.py` ja `admin/services.py` kutsumaan näitä uusia funktioita — älä jätä duplikaattia.
- Testit: `tests/test_users_service.py` joka kattaa onnistuneen luonnin, duplikaattisähköpostin, virheellisen roolin, role-vaihdon, deaktivoinnin + audit-rivien syntymisen.

---

### Tehtävä 2 — Luo `app/admin/forms.py` ja kytke se admin-näkymiin

Init-template (osio 2) listaa `auth/forms.py`:n lisäksi vastaavat formit admin-puolelle, mutta nyt admin-routet käyttävät raakaa `request.form`-arvoja ilman Flask-WTF-validointia.

- Luo `app/admin/forms.py` ja vie sinne FlaskForm-luokat ainakin näille:
  - `UserCreateForm`, `UserEditForm` (rooli, organization, is_active)
  - `OrganizationForm`
  - `ApiKeyForm` (name, scopes, expires_at)
  - `EmailTemplateForm` (subject, body_text, body_html)
  - `SettingForm` (key, value, type, description, is_secret)
- Käytä WTForms-validaattoreita (`DataRequired`, `Email`, `Length`, `Optional`, `NumberRange`).
- Päivitä kaikki `app/admin/routes.py`-näkymät käyttämään näitä formeja sekä GET- että POST-puolella (CSRF tulee Flask-WTF:ltä). Templatet (`admin_user_form.html`, `admin_organization_form.html` jne.) saa pitää, mutta päivitä input-kentät käyttämään formin renderöintiä.
- Testit: lisää `tests/test_admin_forms.py` joka tarkistaa että puuttuva pakollinen kenttä → 400/uudelleenrender ja ettei CSRF-tokenitön POST mene läpi.

---

### Tehtävä 3 — Eriytä varmuuskopioreitit `app/backups/routes.py`:ksi

Init-template (osio 2) odottaa omaa `backups/routes.py`:tä. Nyt reitit ovat `app/admin/routes.py`:n sisällä.

- Luo `app/backups/routes.py` ja siirrä sinne kaikki `/admin/backups`-alkuiset reitit (lista, create, download, restore-confirm, restore-execute).
- Pidä url-prefix `/admin/backups` (ei riko olemassa olevia linkkejä). Käytä blueprintia `backups_admin_bp` ja rekisteröi se `app/__init__.py`:n `register_blueprints`-funktiossa **admin_bp:n alle** tai itsenäisesti `/admin/backups`-prefixillä — kunhan reitit pysyvät samoina.
- Säilytä superadmin-tarkistus, 2FA-tarkistus, password-confirm restoreen, audit-lokitus.
- Tarkista, että `tests/test_backup.py` ja `tests/test_backup_retention.py` menevät edelleen läpi muuttamatta itse testejä.

---

### Tehtävä 4 — Luo `app/email/templates.py` renderöinnille

Init-template (osio 2 + 7) listaa `email/templates.py`:n. Nyt renderöinti on osa `email/services.py`:tä.

- Luo `app/email/templates.py` joka altistaa funktiot:
  - `render_template_for(key: str, context: dict) -> RenderedEmail` (palauttaa subject, html, text)
  - `available_variables_for(key: str) -> list[str]`
  - `validate_context(key: str, context: dict) -> list[str]` (palauttaa puuttuvat muuttujat)
- Siirrä Jinja-renderöinti sinne `email/services.py`:stä. `services.py` jää vastaamaan vain Mailgun-lähetyksestä ja kutsuu `templates.py`:tä.
- Lisää `validate_context`-tarkistus admin-UI:n preview-/test-send -näkymiin, jotta superadmin saa selkeän virheviestin puuttuvasta muuttujasta sen sijaan että render kaatuu.
- Testit: `tests/test_email_templates.py` — render onnistuu kaikilla seed-pohjilla, puuttuva muuttuja antaa selkeän virheen.

---

### Tehtävä 5 — Sähköpostien taustatyö (osa 1: jonotaulukko)

Init-template (osio 14) sanoo: "sähköpostit lähetetään taustatyönä". Nyt `send_template` blokkaa requestin Mailgun-call:n ajan.

- Luo malli `app/email/models.py`:n yhteyteen `OutgoingEmail`:
  - `id, to, template_key, context_json, subject_snapshot, status (pending/sent/failed), attempts, last_error, scheduled_at, sent_at, created_at`
- Tee migraatio.
- Refaktoroi `email/services.py` niin, että `send_template(...)` oletuksena **vain rivittää** sähköpostin tähän tauluun (status=pending) ja palauttaa heti `True`. Pidä rinnalla `send_template_sync(...)` tilanteille, joissa pitää olla synkroninen vahvistus (esim. `flask send-test-email`).
- Lisää `app/email/scheduler.py` joka APSchedulerilla pollaa pending-rivit (esim. 30 sekunnin välein) ja yrittää lähettää. Onnistunut → `status=sent, sent_at=now`. Epäonnistuneessa: `attempts += 1, last_error=...`. Yli 5 epäonnistunutta yritystä → `status=failed`.
- Käynnistä scheduler `app/__init__.py`:ssä `_maybe_start_backup_scheduler` -tyyliin, samalla guardilla (ei testeissä, ei CLI:ssä). Lisää env-muuttuja `EMAIL_SCHEDULER_ENABLED=1` `.env.example`:een.
- Testit: `tests/test_email_queue.py` — uusi rivi syntyy pendingiksi, scheduler-cycle muuttaa sen sentiksi mockatulla Mailgunilla, retry-logiikka toimii, max-attempts → failed.

---

### Tehtävä 6 — Sähköpostipohjien kattavuus

Init-template (osio 7) vaatii vähintään: `welcome_email`, `password_reset`, `login_2fa_code`, `backup_completed`, `backup_failed`, `admin_notification`.

- Käy läpi `app/email/seed_data.py` ja varmista että kaikki kuusi avainta löytyvät täydellä subject + body_text + body_html + available_variables -datalla.
- `login_2fa_code` toimii varakanavana, kun TOTP-laite on kateissa: lisää `auth/services.py`:hin funktio `send_email_2fa_code(user)` joka generoi 6-numeroisen koodin, hashaa ja tallentaa sen `TwoFactorEmailCode`-tauluun (luo malli + migraatio: `id, user_id, code_hash, expires_at, used_at, created_at`), expiraatio 10 min.
- Lisää `/2fa/email-code`-reitti joka pyytää koodin, ja `/2fa/verify` hyväksyy myös tämän koodin (TOTP / backup code / email code).
- Audit: `2fa.email_code_sent`, `2fa.email_code_used`.
- Testit: `tests/test_2fa_email_code.py`.

---

### Tehtävä 7 — Settings-taulun täyttäminen templaten mukaisesti

Init-template (osio 9) edellyttää sarakkeet: `id, key, value, type, description, is_secret, updated_by, updated_at`.

- Tarkista `app/settings/models.py`. Jos puuttuu `is_secret` tai `updated_by` (FK users.id, nullable), lisää ne. Tee migraatio.
- Päivitä `settings/services.py`:n `set_value(...)` ottamaan `actor_user_id`-argumentti ja tallentamaan se `updated_by`:hin. Audit-rivi `setting.updated`.
- Päivitä admin-UI: `is_secret=true` -arvojen `value` näkyy maskattuna (`••••••`) listauksessa ja editorin paljastusnappi vaatii tuoreen 2FA-koodin.
- Settings-arvot eivät saa päätyä lokeihin: lisää `app/core/logging.py`:hin filtteri joka redactaa `is_secret`-arvot, jos niitä yritetään lokittaa kontekstissa.
- Backup-vienti: jos backup tekee selväkielisen settings-dumpin (tarkista `backups/services.py`), `is_secret`-arvot pitää korvata `***`-merkinnällä dumpissa.
- Testit: `tests/test_settings_secrets.py`.

---

### Tehtävä 8 — Audit-lokin kattavuuden täydennys

Init-template (osio 11) listaa lokitettavat tapahtumat. Käy läpi koodi ja varmista, että jokainen näistä laukaisee `audit_record`-kutsun:

- `login`, `login_failed`, `logout` — `auth/services.py`
- `password_changed` — `users/services.py` (tehtävä 1)
- `2fa_enabled`, `2fa_disabled` — `auth/services.py`
- `apikey.created`, `apikey.deleted`, `apikey.rotated` — `cli.py` ja admin
- `setting.updated` — `settings/services.py` (tehtävä 7)
- `user.created`, `user.deleted`, `role_changed` — `users/services.py`
- `backup.created`, `backup.restored` — `backups/services.py`
- `email_template.updated` — admin

Lisää `tests/test_audit_coverage.py` joka käy läpi jokaisen näistä toiminnoista pyhän pikatestin avulla ja varmistaa että audit-rivi syntyy oikealla `action`-koodilla.

Lisää myös tarkistus, ettei `/admin/audit`-näkymässä ole edit/delete-painikkeita templatessa.

---

### Tehtävä 9 — API-avaimen `last_used_at` ja käyttöloki

Init-template (osio 6) sanoo: "niiden käyttö lokitetaan".

- Tarkista `app/api/auth.py` (`require_api_key`-decorator). Jokainen onnistunut tunnistus päivittää `api_key.last_used_at = datetime.now(timezone.utc)` ja kirjaa rivin uuteen `ApiKeyUsage`-tauluun: `id, api_key_id, endpoint, status_code, ip, user_agent, created_at`.
- Päivitys + insertti pitää olla halpa — älä committaa joka pyyntöä, vaan `db.session.add()` + commit on OK koska Flask-SQLAlchemy committaa requestin lopussa.
- Tarjoa admin-UI:ssä `/admin/api-keys/<id>/usage` joka näyttää viimeiset 100 käyttöriviä.
- Vanhojen rivien automaattinen pruning: lisää APScheduler-job joka poistaa yli 90 vrk vanhat `ApiKeyUsage`-rivit (env: `API_USAGE_RETENTION_DAYS=90`).
- Testit: `tests/test_api_key_usage.py`.

---

### Tehtävä 10 — Off-site backup -tuki (S3-yhteensopiva)

Init-template (osio 8) puhuu varmuuskopioiden hallinnasta. Pelkkä levytallennus ei ole tuotantokelpoinen.

- Lisää valinnainen S3-tyyppinen vienti (boto3, mikä tahansa S3-yhteensopiva endpoint: AWS S3, Backblaze B2, Wasabi, MinIO).
- Env-muuttujat `.env.example`:een:
  - `BACKUP_S3_ENABLED=0`
  - `BACKUP_S3_ENDPOINT_URL=`
  - `BACKUP_S3_BUCKET=`
  - `BACKUP_S3_ACCESS_KEY=`
  - `BACKUP_S3_SECRET_KEY=`
  - `BACKUP_S3_PREFIX=pindora-pms/`
- `backups/services.py`:n `create_backup(...)`-onnistumisen jälkeen, jos S3 on enabled: lataa sql.gz ja uploads.tar.gz S3:een, talleta `s3_uri` `Backup`-malliin (uusi sarake, migraatio).
- Älä poista paikallista kopiota — off-site on lisäys, ei korvaaja.
- Audit: `backup.uploaded_offsite`.
- Testit: `tests/test_backup_offsite.py` boto3-mockilla (`moto`-kirjasto sopii).

---

### Tehtävä 11 — Salasanapolitiikka

Init-template (osio 4 + 10) — vahva hash on jo (Werkzeug). Lisää:

- `app/core/security.py`:hin `validate_password_strength(password: str) -> list[str]` joka palauttaa virhelistan: vähintään 12 merkkiä, vähintään yksi kirjain ja yksi numero.
- Käytä sitä `auth/forms.py`:n rekisteröinti-/reset-formeissa ja `users/services.create_user`/`change_password`-funktioissa.
- Env-muuttuja `PASSWORD_MIN_LENGTH=12` `.env.example`:een (oletus 12).
- Testit: `tests/test_password_policy.py`.

---

### Tehtävä 12 — Brute-force-suoja per käyttäjä, ei vain per IP

Init-template (osio 4 + 10) — Flask-Limiter on per IP. Lisää lukko per email.

- Lisää malli `LoginAttempt`: `id, email, ip, success, created_at` tai vaihtoehtoisesti laske kentät suoraan `User`-mallista (`failed_login_count`, `locked_until`).
- `auth/services.py`:n login-flow:hon: jos saman emailin viimeiseltä 15 minuutilta on yli `MAX_LOGIN_ATTEMPTS` epäonnistunutta yritystä → estä kirjautuminen 30 minuutiksi vaikka salasana olisi oikea ja palauta neutraali virhe ("Invalid credentials").
- Onnistunut kirjautuminen nollaa laskurin.
- Env-muuttuja `MAX_LOGIN_ATTEMPTS=5` `.env.example`:een.
- Testit: `tests/test_login_lockout.py`.

---

### Tehtävä 13 — OpenAPI / Swagger-UI

Ei pakollinen init-templatessa, mutta osio 17 puhuu API-dokumentaatiosta. README:n manuaalinen lista vanhentuu välittömästi.

- Lisää `flask-smorest` tai `apispec` riippuvuus.
- Generoi OpenAPI-spec automaattisesti `/api/v1/`-routeista.
- Serveroi Swagger-UI osoitteessa `/api/v1/docs`.
- Suojaa `/api/v1/docs` joko julkiseksi (suositus, koska se on pelkkää dokumentaatiota) tai admin-loginin taakse — valitse perustellusti.
- Päivitä `README.md` osoittamaan Swagger-osoitteeseen ja poista manuaalinen endpoint-lista.

---

### Tehtävä 14 — `.env.example`-täydennys ja CLI-lisät

Lisää `.env.example`:een puuttuvat:

```
SESSION_LIFETIME_MINUTES=120
PASSWORD_MIN_LENGTH=12
MAX_LOGIN_ATTEMPTS=5
EMAIL_SCHEDULER_ENABLED=1
API_USAGE_RETENTION_DAYS=90
BACKUP_S3_ENABLED=0
BACKUP_S3_ENDPOINT_URL=
BACKUP_S3_BUCKET=
BACKUP_S3_ACCESS_KEY=
BACKUP_S3_SECRET_KEY=
BACKUP_S3_PREFIX=pindora-pms/
# DATABASE_URL=  # vaihtoehto POSTGRES_*-muuttujille (template osio 18)
```

Lue jokainen muuttuja oikeassa configissa (`app/config.py`) ja käytä koodissa.

Lisää CLI-komennot:

- `flask cleanup-expired-tokens` — poistaa vanhentuneet `PasswordResetToken`-, `TwoFactorEmailCode`- ja `PortalMagicLinkToken`-rivit.
- `flask vacuum-audit-logs --keep-days N` — leikkaa audit-rivejä N päivää vanhempaa.

Päivitä README:n CLI-osio.

---

### Tehtävä 15 — Loppuvarmistus

Tämä ajetaan vasta, kun tehtävät 1–14 on tehty.

- Aja `pytest -q` — kaikki testit menevät läpi.
- Aja `flask db upgrade` puhtaalle tietokannalle — kaikki migraatiot toimivat.
- `docker compose up --build -d` käynnistyy puhtaasta projektista.
- `flask create-superadmin`, `flask send-test-email`, `flask backup-create`, `flask backup-restore` toimivat manuaalisesti testattuna.
- Päivitä `README.md`:n Acceptance-checklist näyttämään uusien lisäysten tila.
- Tee yhteenveto-commit `docs: README and acceptance checklist for init-template`.

## PROMPT LOPPUU

---

## Vinkkejä Cursor-käyttöön

- Cursor Composer toimii parhaiten yhdellä tehtävällä kerrallaan. Avaa
  Composer, liimaa **vain yhden tehtävän osio** kerrallaan (esim. "Tehtävä 1"
  edellä), ja anna sen tehdä se loppuun ennen seuraavan aloittamista.
- Jos haluat antaa koko prompt-tekstin kerralla agent-tilassa: lisää
  alkuun rivi `Tee tehtävät 1–15 yksi kerrallaan, committaa jokainen
  erikseen, ja pysähdy testaamaan ennen seuraavaa.`
- Pidä `pytest -q` auki erillisessä terminaalissa ja aja se jokaisen
  tehtävän jälkeen.
- Jos Cursor ehdottaa rakenteellisia muutoksia muualle (esim. uudelleenni-
  meämisiä), torju ne ellei tehtävä sitä vaadi — muutosten kontrolli säilyy
  paremmin.
