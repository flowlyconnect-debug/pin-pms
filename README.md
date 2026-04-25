# Pindora PMS

A secure SaaS base for a Property Management System built on Flask. The
codebase implements every requirement from the project brief: multi-tenant
users with role-based access, mandatory TOTP 2FA for superadmins, a public
API authenticated by per-tenant API keys, editable email templates over
Mailgun, scheduled and manual database backups with a guarded restore flow,
a centralised settings table, an audit log for every privileged action, and
a pytest suite covering the spec's minimum nine test areas.

The repository is the framework — PMS-specific business models (rooms,
bookings, pricing) are intentionally out of scope and live in a separate
codebase that builds on top of this foundation.

---

## Table of contents

1. [Purpose](#1-purpose)
2. [Installation](#2-installation)
3. [Environment variables](#3-environment-variables)
4. [Running the dev environment](#4-running-the-dev-environment)
5. [Database migrations](#5-database-migrations)
6. [Running the tests](#6-running-the-tests)
7. [API documentation](#7-api-documentation)
8. [Working with backups](#8-working-with-backups)
9. [Creating the first superadmin](#9-creating-the-first-superadmin)

---

## 1. Purpose

Pindora PMS provides the production-ready primitives every multi-tenant PMS
needs:

- **Users + organizations** with roles (`superadmin`, `admin`, `user`,
  `api_client`).
- **Authentication**: session-based login for the web UI, API-key auth for
  the REST API, mandatory TOTP 2FA for superadmins.
- **Public API** at `/api/v1/*` with a uniform JSON envelope
  (`{success, data, error}`) and per-key rate limiting.
- **Editable email templates** stored in the database, rendered through a
  sandboxed Jinja, and delivered via Mailgun (with a dev-mode log fallback).
- **Database backups**: `pg_dump --clean --if-exists` on a schedule,
  manually triggerable from `/admin/backups`, with a guarded restore flow
  (warning → password → 2FA → safe-copy → load → audit).
- **Settings table** behind a single service layer — no module reads or
  writes settings directly.
- **Audit log** for every privileged action: logins, 2FA events, API key
  creation/rotation, backup create/restore, settings updates, email
  template changes.
- **CSRF, rate limiting, branded error pages, secure cookie defaults** wired
  in by default.

Deliberately out of scope: PMS-specific business logic, multi-region
deployments, and observability stacks beyond the audit log.

## 2. Installation

### Prerequisites

- Docker Desktop (or any Docker engine) with Docker Compose v2.
- Roughly 1 GB of free disk space for the Postgres image and backup volume.

### Clone and configure

```bash
git clone <repo-url> pindora-pms
cd pindora-pms
cp .env.example .env
```

Edit `.env` and set strong values for **at minimum**:

| Variable            | Why                                                   |
| ------------------- | ----------------------------------------------------- |
| `SECRET_KEY`        | Signs Flask sessions and CSRF tokens.                 |
| `POSTGRES_PASSWORD` | Postgres superuser password.                          |
| `DATABASE_URL`      | Update the password segment to match the line above.  |

The remaining variables ship with safe defaults for local development. See
[§3](#3-environment-variables) for the full list.

### Build and start

```bash
docker compose up --build -d
docker compose exec web flask db upgrade
```

The first command builds the `web` image (installs Python deps + the
`postgresql-client` binary needed by `pg_dump`) and starts both `web` and
`db` containers. The second runs every Alembic migration in order so the
database schema matches the application code.

Visit <http://localhost:5000/api/v1/health> — you should get
`{"success": true, "data": {"status": "ok"}, "error": null}`.

## 3. Environment variables

All configuration goes through environment variables. `app/config.py`
defines `BaseConfig`, `DevelopmentConfig`, `ProductionConfig`, and
`TestConfig`; each reads from `os.getenv` so any value can be overridden
without a code change.

`.env.example` is the source of truth — copy it and fill in the secrets.

| Variable                   | Default                              | Notes                                                                              |
| -------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------- |
| `FLASK_ENV`                | `development`                        | `development` or `production`.                                                     |
| `FLASK_DEBUG`              | `1`                                  | Toggles the Werkzeug debugger. Must be off in production.                          |
| `FLASK_APP`                | `run.py`                             | Used by `flask` CLI commands.                                                      |
| `SECRET_KEY`               | _(unset)_                            | Required in production. Sign Flask sessions / CSRF tokens.                         |
| `POSTGRES_DB`              | `pindora`                            | Application database name.                                                         |
| `POSTGRES_USER`            | `postgres`                           | Postgres user.                                                                     |
| `POSTGRES_PASSWORD`        | _(must change)_                      | Postgres password.                                                                 |
| `DATABASE_URL`             | _(see example)_                      | Full SQLAlchemy URL. Must match the user/password above.                           |
| `LOGIN_RATE_LIMIT`         | `5/minute`                           | Per-IP throttle on `POST /login`. Brief §18.                                       |
| `API_RATE_LIMIT`           | `100/hour`                           | Per-API-key throttle on `/api/v1/*`. Brief §18.                                    |
| `MAILGUN_API_KEY`          | _(empty)_                            | Mailgun API key. Empty + `MAIL_DEV_LOG_ONLY=1` skips real sending.                 |
| `MAILGUN_DOMAIN`           | _(empty)_                            | Mailgun sending domain.                                                            |
| `MAILGUN_BASE_URL`         | `https://api.mailgun.net/v3`         | Override for EU region (`https://api.eu.mailgun.net/v3`).                          |
| `MAIL_FROM`                | `noreply@example.com`                | `From:` address.                                                                   |
| `MAIL_FROM_NAME`           | `Pindora PMS`                        | `From:` display name.                                                              |
| `MAIL_DEV_LOG_ONLY`        | `0`                                  | When `1`, emails are logged to stdout instead of sent. Production must keep `0`.   |
| `BACKUP_DIR`               | `/var/backups/pindora`               | Where dumps land (Docker volume).                                                  |
| `BACKUP_SCHEDULE_CRON`     | `0 3 * * *`                          | APScheduler 5-field cron.                                                          |
| `BACKUP_SCHEDULER_ENABLED` | `1`                                  | Set `0` to disable automatic backups (manual triggers still work).                 |
| `BACKUP_NOTIFY_EMAIL`      | _(empty)_                            | Receives `backup_completed` / `backup_failed` notifications. Empty = skip emails.  |

## 4. Running the dev environment

The standard loop is:

```bash
docker compose up --build -d         # first time / after Dockerfile or requirements changes
docker compose up -d                 # subsequent starts (uses cached image)
docker compose logs -f web           # tail the Flask debug log
docker compose down                  # stop without losing data
docker compose down -v               # stop and wipe the postgres + backups volumes
```

`docker-compose.yml` overrides the production entrypoint to use Flask's
auto-reloading dev server (`flask run --debug`), so editing any file under
`app/` is picked up on the next request — no manual restart needed.

The `web` container mounts the project root as a volume, so log output
appears in the host's `docker compose logs` stream and you can edit code
in your IDE without rebuilding.

### Useful one-off commands

```bash
# Open an interactive Python shell with the Flask app context loaded.
docker compose exec web flask shell

# Open a psql prompt inside the db container.
docker compose exec db psql -U postgres -d pindora

# Check the alembic head matches the code.
docker compose exec web flask db current
```

## 5. Database migrations

Schema changes are managed by **Flask-Migrate** (Alembic).

### Apply migrations

```bash
docker compose exec web flask db upgrade
```

This is idempotent — running it on an up-to-date database is a no-op. Run
it after every `git pull` and as part of every deploy.

### Inspect state

```bash
docker compose exec web flask db current   # current revision
docker compose exec web flask db history   # full migration list
```

### Author a new migration

```bash
docker compose exec web flask db migrate -m "add bookings table"
```

Review the generated file under `migrations/versions/` before committing —
Alembic's autogenerate is good but not infallible (e.g. column type changes
and indexes often need hand edits). Then:

```bash
docker compose exec web flask db upgrade
```

### Roll back

```bash
docker compose exec web flask db downgrade -1
```

Use sparingly; downgrade scripts often drop data and are not exercised in
CI.

## 6. Running the tests

The test suite lives under `tests/` and uses **pytest**. It connects to a
separate `pindora_test` Postgres database that `tests/conftest.py` creates
automatically on the first run.

```bash
# All tests, quiet output.
docker compose exec web pytest -q

# Verbose with full tracebacks.
docker compose exec web pytest -v --tb=long

# A single file.
docker compose exec web pytest tests/test_api_auth.py

# A single test.
docker compose exec web pytest tests/test_login.py::test_login_failure_with_wrong_password_returns_form_with_error
```

The suite covers the nine test areas required by spec §16:

| Spec area                        | File                          |
| -------------------------------- | ----------------------------- |
| Käyttäjän luonti                 | `tests/test_users.py`         |
| Kirjautuminen                    | `tests/test_login.py`         |
| Epäonnistunut kirjautuminen      | `tests/test_login.py`         |
| Superadmin 2FA -vaatimus         | `tests/test_2fa.py`           |
| API-avainautentikointi           | `tests/test_api_auth.py`      |
| API:n virhevastaukset            | `tests/test_api_errors.py`    |
| Sähköpostipohjan renderöinti     | `tests/test_email.py`         |
| Varmuuskopion luonti             | `tests/test_backup.py`        |
| Oikeustarkistukset               | `tests/test_permissions.py`   |

`TestConfig` disables rate limiting, CSRF, and the backup scheduler so
tests can hammer endpoints and POST forms without harness noise. Test data
is wiped between functions by the autouse `db_isolation` fixture so test
ordering does not leak state.

## 7. API documentation

The public API lives under `/api/v1/*`. Every response, success or error,
follows the same envelope:

```jsonc
// success
{ "success": true,  "data": { /* … */ }, "error": null }

// failure
{ "success": false, "data": null,        "error": { "code": "<snake>", "message": "<human>" } }
```

### Authentication

API requests are authenticated by an opaque, high-entropy key issued via
the `flask create-api-key` CLI (see [§9](#9-creating-the-first-superadmin)
for context). Both header forms are accepted:

```http
Authorization: Bearer pms_<key>
X-API-Key: pms_<key>
```

`/health` is the only public route — every other endpoint returns `401`
without a valid key. Inactive, expired, or rotated keys also return `401`.

### Rate limiting

Every `/api/v1/*` route is throttled at `API_RATE_LIMIT` (default
`100/hour`) per API key (per-IP when unauthenticated). When exceeded, the
response is `429` plus the standard envelope and `Retry-After` /
`X-RateLimit-*` headers.

### Endpoints

| Method | Path             | Auth | Description                                  |
| ------ | ---------------- | ---- | -------------------------------------------- |
| `GET`  | `/api/v1/health` | none | Liveness probe.                              |
| `GET`  | `/api/v1/me`     | key  | Return the calling key's user + organization.|

`GET /api/v1/me` example:

```bash
curl -s http://localhost:5000/api/v1/me \
  -H "Authorization: Bearer pms_<key>"
```

```jsonc
{
  "success": true,
  "data": {
    "api_key": {
      "id": 1,
      "name": "Production integration",
      "prefix": "pms_AbCdEfGh",
      "scopes": [],
      "expires_at": null,
      "last_used_at": "2026-04-25T16:23:53.107904+00:00"
    },
    "organization": { "id": 1, "name": "Acme Hotels" },
    "user": { "id": 4, "email": "ops@acme.example", "role": "api_client" }
  },
  "error": null
}
```

### Error codes

Every HTTP error from `/api/v1/*` returns the JSON envelope. Common codes:

| HTTP | `error.code`            | When                                         |
| ---- | ----------------------- | -------------------------------------------- |
| 400  | `bad_request`           | Malformed request body.                      |
| 401  | `unauthorized`          | Missing / invalid / expired API key.         |
| 403  | `forbidden`             | Authenticated but lacking the right scope.   |
| 404  | `not_found`             | No such route or resource.                   |
| 405  | `method_not_allowed`    | Wrong HTTP verb.                             |
| 429  | `too_many_requests`     | Rate limit exceeded.                         |
| 500  | `internal_server_error` | Unhandled bug. Audit log will have details.  |

## 8. Working with backups

Backups are gzipped `pg_dump --clean --if-exists` outputs that land in
`BACKUP_DIR` (a Docker volume). Every attempt — successful, failed,
scheduled, manual, or "pre-restore safe-copy" — is recorded in the
`backups` table.

### Scheduled backups

`BACKUP_SCHEDULE_CRON` (default `0 3 * * *` = 03:00 UTC daily) drives an
APScheduler `BackgroundScheduler` started inside the long-running web
process. A Postgres advisory lock guarantees that only one Gunicorn worker
performs the dump per tick.

### Manual backup

From the admin UI:

1. Sign in as superadmin → complete 2FA verification.
2. Open `/admin/backups`.
3. Click **Create backup now**.

From the CLI:

```bash
docker compose exec web flask backup-create
```

Both record a `backup.created` audit row and (if `BACKUP_NOTIFY_EMAIL` is
set) email the `backup_completed` template to that address.

### Restore from a backup

The restore flow is destructive — it overwrites the current database with
the contents of the chosen file. Brief §8 mandates four guards before any
data is touched:

1. **Warning** — a red, full-page warning explains what will happen.
2. **Password** — the operator re-enters their own password.
3. **2FA** — a fresh TOTP code from their authenticator.
4. **Safe-copy** — the current state is dumped to a new
   `pre_restore`-tagged backup before the load.

Then `psql --single-transaction -v ON_ERROR_STOP=1` loads the chosen file.
Failure rolls the entire restore back; success commits. Either way, an
audit row is written (`backup.restored` or `backup.restored.failed`) and
every active superadmin receives an `admin_notification` email.

From the admin UI:

1. `/admin/backups` → click **Restore…** on the row.
2. Re-enter password + a fresh 2FA code.
3. Click **Yes, restore from this backup**.

From the CLI (skips the password / 2FA challenge — the operator already has
shell access to the host, which is equivalent in trust):

```bash
docker compose exec web flask backup-restore \
  --filename pindora-20260425T030000Z.sql.gz
```

Pass `--no-confirm` to skip the interactive prompt (useful for automated
disaster-recovery drills).

### Reverting a botched restore

Every restore writes a `pre_restore`-tagged safe-copy to `BACKUP_DIR`
before destroying the current state. To revert, run a second restore and
pick the latest `pre_restore` row.

## 9. Creating the first superadmin

A fresh database has no users. Bootstrap one with:

```bash
docker compose exec web flask create-superadmin
```

Click prompts for:

- **Email** — login identifier.
- **Password** — entered twice; hashed with Werkzeug.
- **Organization name** — created if it doesn't already exist.

On the first sign-in the user is forced through `/2fa/setup` to enrol a
TOTP factor (Google Authenticator, Authy, 1Password, Bitwarden — anything
RFC 6238 compatible). After enrolment, every subsequent sign-in requires a
fresh 6-digit code.

### Other CLI commands

| Command                                   | Purpose                                          |
| ----------------------------------------- | ------------------------------------------------ |
| `flask create-user`                       | Create a non-superadmin user.                    |
| `flask create-api-key`                    | Issue an API key for an existing user.           |
| `flask rotate-api-key`                    | Replace an API key — old becomes inactive.       |
| `flask backup-create`                     | Run pg_dump + audit + notification email.        |
| `flask backup-restore --filename …`       | Load a backup over the current database.         |
| `flask send-test-email --to … --template …` | Render and send a template — verifies Mailgun.   |
| `flask seed-email-templates`              | Re-insert any missing default email templates.   |
| `flask seed-settings`                     | Re-insert any missing default settings rows.     |
| `flask db upgrade`                        | Apply pending Alembic migrations.                |
| `flask shell`                             | Python REPL with the app context already loaded. |

---

## License

Proprietary — see `LICENSE` if present, otherwise treat as all rights
reserved.
