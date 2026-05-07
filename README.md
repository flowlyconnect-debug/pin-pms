# Pin PMS

[![CI](https://github.com/example/pindora-pms/actions/workflows/ci.yml/badge.svg)](https://github.com/example/pindora-pms/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/example/pindora-pms/branch/main/graph/badge.svg)](https://codecov.io/gh/example/pindora-pms)

Production-ready Flask backend for a multi-tenant Property Management System
(PMS), including API auth, admin UI, audit logging, email templates/Mailgun,
database backups, and automated tests.

## Application purpose

This project provides the core operational platform for PMS use cases:

- tenant-scoped organizations, users, properties, units, reservations
- **leases** (draft → active → ended/cancelled) and **invoices** (draft/open → paid/overdue/cancelled) with per-organization invoice numbers
- **maintenance requests** (work orders): statuses `new` → `in_progress` / `waiting` → `resolved` or `cancelled`, priorities `low` / `normal` / `high` / `urgent`, scoped to property/unit/guest/reservation
- role-based access control (`superadmin`, `admin`, `user`, `api_client`)
- mandatory TOTP 2FA for `superadmin` actions
- server-rendered admin pages and API endpoints under `/api/v1`
- audit trail for critical security and PMS events
- Mailgun-backed template email delivery
- scheduled/manual backups with guarded restore

## Tarkoitus — tukipaketit

### `app/subscriptions/`

**Tarkoitus:** `SubscriptionPlan`-malli ja organisaation käyttäjien tilaus-/rajapaketointi (esim. API rate limit -metadata `limits_json`-kentässä). Ei erillistä blueprintia; taulu ja ORM käytössä käyttäjä–tilaus -suhteessa.

### `app/status/`

**Tarkoitus:** Julkisen tilasivun ja valmiustarkistusten (`StatusComponent`, `StatusCheck`, `StatusIncident`) datamallit ja palvelu; synteettiset tarkistukset voidaan ajastaa APSchedulerilla (`app/status/scheduler.py`). Käytössä mm. `/api/v1/health/ready` ja superadmin-näkymät.

### `app/owner_portal/`

**Tarkoitus:** Omistajille tarkoitettu kirjautumispinta (`/owner`) ja omistajakohtaiset listaukset (esim. kiinteistöiden varaukset). Säilytetty Pakkaus 8:n owner statements -työn alla olevaa jatkokehitystä varten.

## Tech stack

- Python 3.12+
- Flask + Flask-Login + Flask-WTF CSRF + Flask-Cors
- SQLAlchemy + Flask-Migrate (Alembic)
- PostgreSQL 16
- Flask-Limiter
- APScheduler
- Gunicorn (production) + Nginx + systemd (see `deploy/`)
- pytest
- Docker / Docker Compose

## Installation

```bash
git clone <repo-url> pindora-pms
cd pindora-pms
cp .env.example .env
```

Set strong values in `.env` before production use (`SECRET_KEY`,
`POSTGRES_PASSWORD`, `DATABASE_URL`, Mailgun credentials).

The authoritative list of keys is **[`.env.example`](.env.example)** — copy it
to `.env` and adjust for your environment.

## Quick start

```bash
git clone <repo-url> pindora-pms
cd pindora-pms
cp .env.example .env
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask create-superadmin
```

Then open `http://localhost:5000`, complete superadmin 2FA when prompted, and
use `/admin` for management UI. The Compose file forces the `web` service to use
the bundled Postgres host `db` and clears a host-only `DATABASE_URL` so one
`docker compose up` works with a copied `.env`.

## Environment variables

`.env.example` includes all required runtime variables and safe placeholders
only (no secrets). Key variables:

- Flask/runtime: `FLASK_ENV`, `FLASK_DEBUG`, `FLASK_APP`, `SECRET_KEY`,
  `SESSION_LIFETIME_MINUTES`
- Database: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`,
  `POSTGRES_HOST`, `POSTGRES_PORT`, `DATABASE_URL`
- Auth/security: `LOGIN_RATE_LIMIT`, `MAX_LOGIN_ATTEMPTS`, `API_RATE_LIMIT`,
  `PASSWORD_MIN_LENGTH`
- Mailgun/Email:
  `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_FROM_EMAIL`,
  `MAILGUN_FROM_NAME`, `MAILGUN_BASE_URL`, `MAIL_DEV_LOG_ONLY`,
  `EMAIL_SCHEDULER_ENABLED`
- Backups:
  `BACKUP_DIR`, `UPLOADS_DIR`, `BACKUP_RETENTION_DAYS`,
  `BACKUP_SCHEDULE_CRON`, `BACKUP_SCHEDULER_ENABLED`, `BACKUP_NOTIFY_EMAIL`
- Off-site backups (optional, S3-compatible):
  `BACKUP_S3_ENABLED`, `BACKUP_S3_ENDPOINT_URL`, `BACKUP_S3_BUCKET`,
  `BACKUP_S3_ACCESS_KEY`, `BACKUP_S3_SECRET_KEY`, `BACKUP_S3_PREFIX`
- Billing scheduler (optional): `INVOICE_OVERDUE_SCHEDULER_ENABLED`,
  `INVOICE_OVERDUE_SCHEDULE_CRON` (five-field cron, default 06:30 UTC daily)
- API usage retention: `API_USAGE_RETENTION_DAYS` (default 90)
- CORS: `CORS_ALLOWED_ORIGINS` (comma-separated, empty = same-origin only)
- Pindora lock integration: `PINDORA_LOCK_BASE_URL`,
  `PINDORA_LOCK_API_KEY`, `PINDORA_LOCK_WEBHOOK_SECRET`,
  `PINDORA_LOCK_TIMEOUT_SECONDS`
- Generic webhook signing + idempotency:
  `WEBHOOK_INBOUND_HMAC_SECRET`, `WEBHOOK_OUTBOUND_HMAC_SECRET`,
  `IDEMPOTENCY_KEY_TTL_SECONDS`
- Check-in document encryption (optional): `CHECKIN_FERNET_KEY`
- iCal calendar sync: `ICAL_FEED_SECRET`, `ICAL_HTTP_TIMEOUT_SECONDS`,
  `ICAL_SYNC_ENABLED`, `ICAL_SYNC_INTERVAL_MINUTES`

## Maksuintegraatio

Sovellus tukee hostattuja maksusivuja (PCI-DSS SAQ-A):

- Stripe Checkout kansainvalisille korteille
- Paytrail Payment Page suomalaisille verkkopankeille, MobilePaylle ja kotimaisille korteille

Tarkeat ymparistomuuttujat:

- Stripe: `STRIPE_ENABLED`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`
- Paytrail: `PAYTRAIL_ENABLED`, `PAYTRAIL_MERCHANT_ID`, `PAYTRAIL_SECRET_KEY`, `PAYTRAIL_API_BASE`
- Payment flow: `PAYMENT_RETURN_URL`, `PAYMENT_CALLBACK_URL`

Inbound webhook URL:t:

- `/api/v1/webhooks/stripe`
- `/api/v1/webhooks/paytrail`

Testitilat:

- Stripe CLI: `stripe listen --forward-to localhost:5000/api/v1/webhooks/stripe`
- Paytrail testitunnukset: `PAYTRAIL_MERCHANT_ID=375917`, `PAYTRAIL_SECRET_KEY=SAIPPUAKAUPPIAS`

Turvallisuus:

- App ei kasittele eika tallenna korttinumeroa, CVV:ta tai expirya.
- Maksut ohjataan aina providerien hostatuille maksusivuille.

## Maksuintegraation manuaalitesti

Stripe testimoodi:

1. `export STRIPE_SECRET_KEY=sk_test_...`
2. `stripe listen --forward-to localhost:5000/api/v1/webhooks/stripe`
3. `flask payments-test-stripe --invoice-id <id>`
4. Maksa testikortilla: `4242 4242 4242 4242` (mika tahansa CVV, tuleva expiry)
5. Tarkista: webhook, `Payment.status=succeeded`, invoice paid, audit-loki, `payment_received` email queue.

Paytrail testimoodi:

1. `export PAYTRAIL_MERCHANT_ID=375917`
2. `export PAYTRAIL_SECRET_KEY=SAIPPUAKAUPPIAS`
3. `flask payments-test-paytrail --invoice-id <id>`
4. Valitse `Nordea Demo`
5. Vahvista maksu
6. Tarkista: callback tuli, `Payment.status=succeeded`, audit-loki.

Varoitus: Paytrailin testisecrettia ei saa kayttaa production-konfiguraatiossa.

## Docker startup

First-time bring-up (after `cp .env.example .env`):

```bash
docker compose up --build -d
docker compose exec web flask db upgrade
docker compose exec web flask create-superadmin
docker compose exec web flask seed-email-templates
```

Subsequent restarts only need `docker compose up -d` — migrations and seeds
are idempotent but optional once the database is in shape.

App health (Windows PowerShell: use `curl.exe` if `curl` is aliased to
`Invoke-WebRequest`):

```bash
curl.exe -s http://localhost:5000/api/v1/health
```

## Local development startup (without Docker)

Prereqs: local PostgreSQL, Python virtualenv, matching `.env`.

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows PowerShell
pip install -r requirements.txt
flask db upgrade
flask run --debug
```

## Database migrations

Apply:

```bash
flask db upgrade
```

Create migration:

```bash
flask db migrate -m "your message"
flask db upgrade
```

## Create superadmin

```bash
flask create-superadmin
```

Seed demo PMS data:

```bash
flask seed-demo-data
```

On first login, superadmin must complete TOTP setup and verification before
admin actions are allowed.

## Running tests

Unit tests (default):

```bash
pytest -v
```

Integration / acceptance tests (Docker Compose, isolated stack):

```bash
pytest tests/integration/ -v
```

Acceptance tests spin up the stack from scratch with `docker compose up -d --build`,
wait for `db` + `web` health, run migrations, create a superadmin, and verify
API health/auth, superadmin 2FA guard, API-key hashing, email CLI, email template
editing, backup create/restore, audit login event, plus README acceptance headings.
The test session always tears down with `docker compose down -v`.

Requirements: Docker + Docker Compose available on the host running tests.

Coverage can be run explicitly when needed, for example:

```bash
pytest -v --cov=app --cov-report=term --cov-report=xml
```

Inside Docker:

```bash
docker compose exec web python -m pytest -v
```

## Code quality tooling

- Type checking: `mypy app/` (gradual strict rollout tracked in `docs/typing_progress.md`)
- Linting: `ruff check app/ tests/`
- Formatting: `black --check app/ tests/`

### Pre-commit (ruff, black, gitleaks)

Install once per clone and wire Git hooks:

```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

`gitleaks` scans commits for accidental secrets; allowlists for `tests/` and
`.env.example` live in `.gitleaks.toml`.

Docker:

```bash
docker compose exec web python -m pytest -v
```

## API documentation

Interactive API docs are available at:

- `GET /api/v1/docs` (Swagger UI)
- `GET /api/v1/openapi.json` (raw OpenAPI spec)

The OpenAPI spec is generated automatically from Flask routes under `/api/v1`,
so endpoint additions/changes appear in docs without maintaining a manual list.

All API responses use a uniform envelope:

- success: `{ "success": true, "data": ..., "error": null }`
- error: `{ "success": false, "data": null, "error": { "code": "...", "message": "..." } }`

Authentication:

- `Authorization: Bearer pms_<key>` or `X-API-Key: pms_<key>`
- API keys are stored hashed in DB (`key_hash`), plaintext shown only once at creation

Notes:

- tenant isolation is enforced by `organization_id`
- list endpoints support `page` and `per_page` and return `meta`
- reservation validation enforces date ordering and overlap prevention
- lease and invoice services enforce `organization_id`, unit/guest/reservation
  ownership, and non-negative amounts; invoice numbers are unique per tenant
  (`BIL-<org_id>-<invoice_id>`)

## CLI commands

Mark open invoices overdue (same logic as the optional scheduled job):

```bash
flask invoices-mark-overdue
```

Scope to one tenant:

```bash
flask invoices-mark-overdue --organization-id 1
```

After pulling new email template keys, run:

```bash
flask seed-email-templates
```

Delete expired auth/portal token rows:

```bash
flask cleanup-expired-tokens
```

Vacuum audit logs and keep only the newest N days:

```bash
flask vacuum-audit-logs --keep-days 90
```

## Backup usage

Create backup:

- Admin UI: `/admin/backups`
- CLI: `flask backup-create`

Backups capture the full PostgreSQL database (including email templates and
settings, which are stored as DB tables). When `UPLOADS_DIR` exists and is
non-empty, a sibling `<stamp>.uploads.tar.gz` is produced alongside the
SQL dump and tracked in the `backups.uploads_filename` column.

In addition to the gzipped SQL dump, every successful backup writes two
human-readable JSON exports next to it under `BACKUP_DIR` (init template §8):

- `<stamp>.email_templates.json` — every row of the `email_templates` table
  serialised by `key` (subject, both bodies, available variables, description,
  `updated_at`). Tracked on `backups.email_templates_filename`.
- `<stamp>.settings.json` — every row of the `settings` table. **Rows with
  `is_secret=true` have their `value` replaced by the literal string
  `"<redacted>"`** so secret values never travel as plaintext through the
  export. Tracked on `backups.settings_filename`.

The exports are intended for audit/inspection and selective restore — the
canonical source of truth remains the SQL dump.

Download / restore:

- Admin UI: `/admin/backups` → "Download" or "Restore…" links
- Restore flow asks for the operator's password + a fresh TOTP code, takes a
  pre-restore safe-copy, then loads the dump in a single transaction
- CLI: `flask backup-restore --filename <backup.sql.gz>`
- If a paired uploads tarball exists it is extracted automatically into
  `UPLOADS_DIR`

Selective JSON-export restore (off by default):

- Admin UI restore form has a separate checkbox "Palauta myös sähköpostipohjat
  ja järjestelmäasetukset JSON-exporteista". CLI: pass
  `--restore-json-exports` to `flask backup-restore`.
- Upserts by `key` against `email_templates` and `settings`. **Existing
  values are overwritten** — this option ships with a visible warning in the
  admin UI.
- Settings rows whose JSON value is `"<redacted>"` are **never** written
  back: an existing DB secret is preserved as-is, and a missing secret row
  is skipped (counted in the `backup.restore_json_exports` audit context as
  `skipped_redacted_missing`). Operators must rotate secrets through the
  normal settings flow.
- Every JSON-export restore writes a separate `backup.restore_json_exports`
  audit row including the upsert summary (`created` / `updated` /
  `redacted_preserved` / `skipped_redacted_missing`).

Retention:

- `BACKUP_RETENTION_DAYS` (default 30) controls how long files live
- pruning runs automatically after every successful backup and removes the
  paired uploads tarball plus both JSON exports alongside the SQL dump
- pre-restore safe-copies are exempt from pruning

## Mailgun setup

Set:

- `MAILGUN_API_KEY`
- `MAILGUN_DOMAIN`
- `MAILGUN_FROM_EMAIL`
- `MAILGUN_FROM_NAME`
- `MAILGUN_BASE_URL` (`https://api.mailgun.net/v3` or EU endpoint)

Verify:

```bash
flask send-test-email --to you@example.com --template admin_notification
```

Admin-paneelin testilahetys:

- Avaa `Sahkopostipohjat` (`/admin/email-templates`)
- Valitse pohja ja paina `Laheta testi`
- Syota vastaanottajan sahkoposti ja laheta lomake

## Admin UI usage

Main admin pages:

- `/admin/properties`
- `/admin/reservations`
- `/admin/leases` — list, create, view, edit; activate, end, cancel (with confirmations where needed)
- `/admin/invoices` — list, create, view; mark paid; cancel; “Mark overdue” for the current organization
- `/admin/calendar`
- `/admin/reports`
- `/admin/audit`
- `/admin/users` (superadmin only)
- `/admin/organizations` (superadmin only)
- `/admin/api-keys` (superadmin only)
- `/admin/email-templates` (superadmin only) — Muokkaa, Esikatsele, Laheta testi
- `/admin/backups` (superadmin only) — list / create / download / restore
- `/admin/settings` (superadmin only)

Access:

- `admin` and `superadmin` can access PMS management UI
- superadmin must pass 2FA guard for the management pages
- tenant scope remains enforced for PMS data

## Auth flows

- `/login` — email + password
- `/logout`
- `/forgot-password` — emails a one-time reset link via Mailgun
- `/reset-password/<token>` — sets a new password (12+ chars)
- `/2fa/setup` — TOTP enrolment (superadmin)
- `/2fa/backup-codes` — view / regenerate one-time recovery codes
- `/2fa/verify` — accepts either a TOTP code or a single-use recovery code

## Production deploy

Reference Nginx + systemd templates live in `deploy/`. Copy them to the
host, point them at the project's virtualenv, and adjust hostnames /
TLS paths. See `deploy/README.md` for step-by-step instructions.

Render start command (runs migrations before serving traffic):

```bash
python safe_migrate.py && gunicorn --bind 0.0.0.0:$PORT --workers 3 --access-logfile - --error-logfile - run:app
```

## Deployment checklist

- [ ] Set a strong production `SECRET_KEY`
- [ ] Run with production config (`FLASK_ENV=production`, `FLASK_DEBUG=0`)
- [ ] Confirm cookie hardening:
  `SESSION_COOKIE_SECURE=true`, `SESSION_COOKIE_HTTPONLY=true`,
  `SESSION_COOKIE_SAMESITE=Lax`
- [ ] Apply migrations before app start (`flask db upgrade`)
- [ ] Create superadmin (`flask create-superadmin`)
- [ ] Complete superadmin 2FA enrollment + verification
- [ ] Configure and verify Mailgun (`flask send-test-email`)
- [ ] Verify backup creation/restore paths
- [ ] Run test suite before deploy (`pytest -v`)

## Manual testing (operators)

After bring-up, verify manually:

- **Login** — email/password; superadmin is redirected to 2FA setup or verify.
- **2FA** — superadmin cannot use `/admin` (except auth/static/health) until
  TOTP is enrolled and verified (`app/__init__.py` guard).
- **API** — `curl.exe -H "Authorization: Bearer pms_<key>" http://localhost:5000/api/v1/me`
  returns `200` with JSON envelope.
- **Audit** — perform an action (e.g. login) and confirm rows in `audit_log`
  (via `/admin/audit` or SQL).
- **Backup** — `flask backup-create` or `/admin/backups`; file under `BACKUP_DIR`.
- **Email** — `flask send-test-email` and/or admin email template test send.

## Acceptance criteria (init template §22)

Use this list as a release checklist (verify in your environment before sign-off):

1. **Single-command stack** — `docker compose up --build -d`; `web` reaches healthy DB; `GET /api/v1/health` returns `200`.
2. **Migrations** — `docker compose exec web flask db upgrade` completes without errors on a fresh volume.
3. **Superadmin CLI** — `docker compose exec web flask create-superadmin` creates an active user.
4. **Superadmin 2FA** — cannot use management UI until TOTP is set and verified (see Manual testing).
5. **API key auth** — `GET /api/v1/me` with `Authorization: Bearer …` returns `200`.
6. **API key storage** — `api_keys` rows contain `key_hash` only (no plaintext key column).
7. **Mailgun test** — `flask send-test-email` succeeds (or `MAIL_DEV_LOG_ONLY=1` logs without error).
8. **Email templates** — edit in `/admin/email-templates`; change persists and affects sends.
9. **Scheduled backup** — APScheduler job when `BACKUP_SCHEDULER_ENABLED=1` (cron `BACKUP_SCHEDULE_CRON`); or `flask backup-create` writes under `BACKUP_DIR`.
10. **Restore** — `flask backup-restore` (or admin flow) with confirmation; pre-restore safe-copy behaviour as documented.
11. **Audit log** — critical actions create `audit_log` rows (IP, user agent, context where applicable).
12. **Automated tests** — `pytest -v` (or in Docker: `docker compose exec web python -m pytest -v`) all green; coverage gate per `pytest.ini` / `.coveragerc`.
13. **README** — this document covers purpose, install, [`.env.example`](.env.example), Docker and local run, migrations, tests, API docs link, backups, superadmin CLI, and the checklist above (init §17 / §22 alignment).

Additional quality items exercised in CI/tests: security headers, CORS default
deny, tenant isolation on API, settings audit redaction, backup safe-copy
coverage.

## License

Proprietary (unless your project includes a separate `LICENSE` file).
