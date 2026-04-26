# Pindora PMS

Production-ready Flask backend for a multi-tenant Property Management System
(PMS), including API auth, admin UI, audit logging, email templates/Mailgun,
database backups, and automated tests.

## Application purpose

This project provides the core operational platform for PMS use cases:

- tenant-scoped organizations, users, properties, units, reservations
- role-based access control (`superadmin`, `admin`, `user`, `api_client`)
- mandatory TOTP 2FA for `superadmin` actions
- server-rendered admin pages and API endpoints under `/api/v1`
- audit trail for critical security and PMS events
- Mailgun-backed template email delivery
- scheduled/manual backups with guarded restore

## Tech stack

- Python 3.12+
- Flask + Flask-Login + Flask-WTF CSRF
- SQLAlchemy + Flask-Migrate (Alembic)
- PostgreSQL 16
- Flask-Limiter
- APScheduler
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

## Environment variables

`.env.example` includes all required runtime variables and safe placeholders
only (no secrets). Key variables:

- Flask/runtime: `FLASK_ENV`, `FLASK_DEBUG`, `FLASK_APP`, `SECRET_KEY`
- Database: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `DATABASE_URL`
- Rate limits: `LOGIN_RATE_LIMIT`, `API_RATE_LIMIT`
- Mailgun/Email:
  `MAILGUN_API_KEY`, `MAILGUN_DOMAIN`, `MAILGUN_FROM_EMAIL`,
  `MAILGUN_FROM_NAME`, `MAILGUN_BASE_URL`,
  `MAIL_FROM`, `MAIL_FROM_NAME`, `MAIL_DEV_LOG_ONLY`
- Backups:
  `BACKUP_DIR`, `BACKUP_RETENTION_DAYS`, `BACKUP_SCHEDULE_CRON`,
  `BACKUP_SCHEDULER_ENABLED`, `BACKUP_NOTIFY_EMAIL`

> Note: the app currently reads `MAIL_FROM` / `MAIL_FROM_NAME`; the
> `MAILGUN_FROM_*` entries are kept in `.env.example` for deployment parity.

## Docker startup

```bash
docker compose up --build -d
docker compose exec web flask db upgrade
```

App health:

```bash
curl -s http://localhost:5000/api/v1/health
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

```bash
pytest -q
```

Docker:

```bash
docker compose exec web pytest -q
```

## API documentation

All API responses use a uniform envelope:

- success: `{ "success": true, "data": ..., "error": null }`
- error: `{ "success": false, "data": null, "error": { "code": "...", "message": "..." } }`

Authentication:

- `Authorization: Bearer pms_<key>` or `X-API-Key: pms_<key>`
- API keys are stored hashed in DB (`key_hash`), plaintext shown only once at creation

Core endpoints:

- `GET /api/v1/health`
- `GET /api/v1/me`

PMS endpoints:

- `GET /api/v1/properties`
- `POST /api/v1/properties`
- `GET /api/v1/properties/<id>`
- `GET /api/v1/properties/<id>/units`
- `POST /api/v1/properties/<id>/units`
- `GET /api/v1/reservations`
- `POST /api/v1/reservations`
- `GET /api/v1/reservations/<id>`
- `PATCH /api/v1/reservations/<id>/cancel`

Notes:

- tenant isolation is enforced by `organization_id`
- list endpoints support `page` and `per_page` and return `meta`
- reservation validation enforces date ordering and overlap prevention

## Backup usage

Create backup:

- Admin UI: `/admin/backups`
- CLI: `flask backup-create`

Restore backup:

- Admin UI restore flow (password + 2FA confirmation)
- CLI: `flask backup-restore --filename <backup.sql.gz>`

Retention:

- configure `BACKUP_RETENTION_DAYS` in environment
- keep `BACKUP_DIR` on durable storage

## Mailgun setup

Set:

- `MAILGUN_API_KEY`
- `MAILGUN_DOMAIN`
- `MAILGUN_BASE_URL` (`https://api.mailgun.net/v3` or EU endpoint)
- from identity (`MAIL_FROM` / `MAIL_FROM_NAME`; aliases present in `.env.example`)

Verify:

```bash
flask send-test-email --to you@example.com --template admin_notification
```

## Admin UI usage

Main admin pages:

- `/admin/properties`
- `/admin/reservations`
- `/admin/audit`
- `/admin/email-templates`
- `/admin/backups`
- `/admin/settings`

Access:

- `admin` and `superadmin` can access PMS management UI
- superadmin must pass 2FA guard
- tenant scope remains enforced for PMS data

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
- [ ] Run test suite before deploy (`pytest -q`)

## Acceptance checklist

- [x] App starts with one command (`docker compose up --build -d`)
- [x] Migrations work (`flask db upgrade`)
- [x] Superadmin can be created from CLI
- [x] Superadmin requires 2FA for admin actions
- [x] API works with API key auth
- [x] API key is stored hashed
- [x] Mailgun test email command exists and works
- [x] Email templates are editable in admin UI
- [x] Daily backup scheduler exists
- [x] Backup restore flow exists
- [x] Audit log stores critical events
- [x] Tests pass
- [x] README explains deployment

## License

Proprietary (unless your project includes a separate `LICENSE` file).
