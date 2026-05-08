"""Pytest configuration and shared fixtures.

The fixtures are deliberately spartan — just enough to back the nine spec
tests in section 16. The full machinery is split into:

* Module-level setup of ``TEST_DATABASE_URL`` from ``POSTGRES_*`` env vars,
  evaluated *before* any ``app`` import so :class:`TestConfig` (defined at
  import time) sees the right value.
* :func:`_ensure_test_database` — connects to the maintenance ``postgres``
  DB and creates ``pindora_test`` if it does not exist.
* :func:`app` (session) — boots the Flask app under ``TestConfig``, runs
  ``db.create_all()`` once, and tears down at the end.
* :func:`db_isolation` (autouse, function) — wipes every table after each
  test so ordering does not leak state between tests. Tests marked
  ``no_db_isolation`` skip the session ``app`` fixture and DB teardown.
* The data fixtures (``organization``, ``regular_user``, ``superadmin``,
  ``api_key``) build minimal rows and stash a couple of plain-text helpers
  (``password_plain``, ``raw``) on the returned ORM object for test
  convenience. Those attributes are never persisted.

Why we read ``POSTGRES_*`` instead of parsing ``DATABASE_URL``
-------------------------------------------------------------

If the operator picked a strong password containing URL-special characters
(``@``, ``:``, ``/``, ``!``), ``urllib.parse.urlparse`` mis-splits the
``user:password@host`` part because the password is not percent-encoded in
``.env``. ``POSTGRES_USER`` / ``POSTGRES_PASSWORD`` are raw plaintext that
docker-compose passes through unchanged, so they always parse cleanly.
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path

import psycopg2
import pyotp
import pytest
from werkzeug.security import generate_password_hash

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv_for_tests() -> None:
    """Load ``.env`` before building ``TEST_DATABASE_URL`` (pytest does not run ``create_app`` yet)."""

    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(_REPO_ROOT / ".env")


_load_dotenv_for_tests()


DEFAULT_TEST_API_SCOPES = ",".join(
    [
        "reservations:read",
        "reservations:write",
        "invoices:read",
        "invoices:write",
        "guests:read",
        "guests:write",
        "properties:read",
        "properties:write",
        "maintenance:read",
        "maintenance:write",
        "reports:read",
        "search:read",
        "tags:read",
        "tags:write",
        "payments:read",
        "payments:write",
        "admin:*",
        "webhooks:read",
        "webhooks:write",
    ]
)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(4)}@test.local"


def _default_postgres_host() -> str:
    """Choose sensible host default for host pytest vs compose container."""

    # In Docker Compose the PostgreSQL service is reachable as ``db``.
    # On a host machine (plain ``pytest``) loopback with published port is correct.
    if os.path.exists("/.dockerenv"):
        return "db"
    return "127.0.0.1"


def _docker_host_port_from_database_url() -> tuple[str | None, int | None]:
    """Extract host/port from DATABASE_URL when running inside Docker."""

    database_url = os.getenv("DATABASE_URL")
    if not database_url or not os.path.exists("/.dockerenv"):
        return None, None

    try:
        from sqlalchemy.engine import make_url

        parsed = make_url(database_url)
    except Exception:
        return None, None

    host = parsed.host
    port = parsed.port
    return host, port


def _default_postgres_sslmode(host: str) -> str | None:
    """libpq ``sslmode`` for pytest DB checks. Remote hosts default to ``require`` (e.g. Render)."""

    override = (os.getenv("POSTGRES_SSLMODE") or "").strip()
    if override:
        ov = override.lower()
        if ov in {"off", "false", "disable", "omit", "none", "no"}:
            return None
        return override
    h = (host or "").strip().lower()
    if h in {"127.0.0.1", "localhost", "::1", "db"}:
        return None
    return "require"


def _psycopg2_connect_params(p: dict[str, object], *, dbname: str) -> dict[str, object]:
    """Build kwargs for ``psycopg2.connect`` including optional ``sslmode``."""

    kw: dict[str, object] = {
        "host": p["host"],
        "port": int(p["port"]),
        "user": p["user"],
        "password": p["password"],
        "dbname": dbname,
    }
    sslmode = p.get("sslmode")
    if isinstance(sslmode, str) and sslmode.strip():
        kw["sslmode"] = sslmode.strip()
    return kw


def _probe_working_postgres_port(host: str, user: str, password: str) -> int | None:
    """When ``POSTGRES_PORT`` is unset on loopback, prefer compose mapping (5433) then native (5432)."""

    for port in (5433, 5432):
        try:
            conn = psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                dbname="postgres",
                connect_timeout=2,
            )
            conn.close()
            return port
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Resolve test connection params from POSTGRES_* (raw, unencoded).
# ---------------------------------------------------------------------------


def _conn_params() -> dict[str, object]:
    """Plain connection parameters as pytest sees them — never URL-encoded."""

    host = os.getenv("POSTGRES_HOST", _default_postgres_host())
    user = os.environ["POSTGRES_USER"] if "POSTGRES_USER" in os.environ else "postgres"
    password = (
        os.environ["POSTGRES_PASSWORD"] if "POSTGRES_PASSWORD" in os.environ else "postgres"
    )

    port_resolved = False
    if "POSTGRES_PORT" in os.environ:
        port = int(os.environ["POSTGRES_PORT"])
        port_resolved = True
    else:
        port = 5432

    # Some setups keep host-oriented POSTGRES_* values even inside the web
    # container (127.0.0.1:5433). Prefer DATABASE_URL host/port in Docker.
    if host in {"127.0.0.1", "localhost"}:
        docker_host, docker_port = _docker_host_port_from_database_url()
        if docker_host:
            host = docker_host
        if docker_port is not None:
            port = int(docker_port)
            port_resolved = True

    # Local pytest should default to local DB even if developer .env contains
    # a production/staging host. Opt in to remote DB with PYTEST_ALLOW_REMOTE_DB=1.
    allow_remote = (os.getenv("PYTEST_ALLOW_REMOTE_DB") or "").strip() == "1"
    if (not allow_remote) and (not os.path.exists("/.dockerenv")):
        normalized_host = (host or "").strip().lower()
        if normalized_host not in {"127.0.0.1", "localhost", "::1", "db"}:
            host = _default_postgres_host()
            # Re-probe local ports (5433 -> 5432) after host fallback.
            port_resolved = False

    if not port_resolved:
        if host in {"127.0.0.1", "localhost"}:
            probed = _probe_working_postgres_port(host, str(user), str(password))
            port = probed if probed is not None else 5432
        else:
            # Service hostname (e.g. ``db`` inside Compose) always uses the container port.
            port = 5432

    # Default to loopback so ``pytest`` on a developer machine (outside Docker)
    # does not resolve the compose service name ``db`` (which only exists on the
    # Docker network). In CI / ``docker compose exec web pytest``, set
    # POSTGRES_HOST=db (or rely on compose defaults in .env).
    # Match common local Docker defaults (see .env.example) so ``pytest`` works
    # out of the box. If ``POSTGRES_PASSWORD`` is unset, default to ``postgres``;
    # if it is set to an empty string (trust auth), that value is preserved.
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "sslmode": _default_postgres_sslmode(host),
    }


def _percent_encode(value: str) -> str:
    """Encode a password for safe inclusion in a SQLAlchemy URL.

    SQLAlchemy/psycopg2 expect URL-encoded credentials in the connection
    string. ``urllib.parse.quote_plus`` is the right shape for this.
    """

    from urllib.parse import quote_plus

    return quote_plus(value)


def _build_test_database_url() -> str:
    """Construct ``postgresql+psycopg2://...`` for the test DB."""

    force_sqlite = (os.getenv("FORCE_SQLITE_TEST_DB") or "").strip() == "1"
    if force_sqlite:
        sqlite_path = (_REPO_ROOT / "pindora_test.sqlite3").resolve()
        return f"sqlite+pysqlite:///{sqlite_path.as_posix()}"

    p = _conn_params()
    local_host = str(p["host"]).strip().lower() in {"127.0.0.1", "localhost", "::1"}
    if local_host:
        try:
            probe_kw = _psycopg2_connect_params(p, dbname="postgres")
            probe_kw["connect_timeout"] = 2
            probe = psycopg2.connect(**probe_kw)
            probe.close()
        except Exception:
            sqlite_path = (_REPO_ROOT / "pindora_test.sqlite3").resolve()
            return f"sqlite+pysqlite:///{sqlite_path.as_posix()}"

    user = _percent_encode(str(p["user"]))
    password = _percent_encode(str(p["password"]))
    base = f"postgresql+psycopg2://{user}:{password}@{p['host']}:{p['port']}/pindora_test"
    sslmode = p.get("sslmode")
    if isinstance(sslmode, str) and sslmode.strip():
        from urllib.parse import quote_plus

        return f"{base}?sslmode={quote_plus(sslmode.strip())}"
    return base


# Set TEST_DATABASE_URL at module-import time so :class:`TestConfig` (whose
# class-level attribute reads ``os.getenv("TEST_DATABASE_URL")`` at import
# time) sees the right value before ``create_app("testing")`` runs.
if not os.environ.get("TEST_DATABASE_URL"):
    os.environ["TEST_DATABASE_URL"] = _build_test_database_url()


def pytest_configure(config) -> None:
    """Stabilise logging during teardown (handlers must not write to closed stdio)."""

    _ = config
    logging.raiseExceptions = False


# ---------------------------------------------------------------------------
# One-time DB bootstrap — creates pindora_test if missing.
# ---------------------------------------------------------------------------


def _ensure_test_database() -> None:
    """Create the test database if Postgres does not already have it."""

    test_url = (os.getenv("TEST_DATABASE_URL") or "").strip().lower()
    if test_url.startswith("sqlite"):
        return

    p = _conn_params()
    test_db_name = "pindora_test"

    try:
        kw = _psycopg2_connect_params(p, dbname="postgres")
        kw["connect_timeout"] = 15
        conn = psycopg2.connect(**kw)
    except psycopg2.OperationalError as exc:
        raise RuntimeError(
            "Could not connect to PostgreSQL for tests. Start Postgres locally, copy "
            ".env.example to .env with matching POSTGRES_* values, or set "
            "TEST_DATABASE_URL / POSTGRES_HOST / POSTGRES_USER / POSTGRES_PASSWORD. "
            "On loopback, port 5433 (Docker publish) then 5432 is tried when POSTGRES_PORT "
            "is unset. Hosted providers (e.g. Render) need TLS: sslmode=require is applied "
            "automatically for non-local hosts, or set POSTGRES_SSLMODE explicitly. "
            "Inside Docker Compose, use POSTGRES_HOST=db (see .env.example).\n"
            f"Original error: {exc}"
        ) from exc
    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (test_db_name,))
        if cur.fetchone() is None:
            # Identifier injection is impossible here — the name is hard-coded
            # above. Belt-and-braces sanity check before interpolation.
            if not test_db_name.replace("_", "").isalnum():
                raise RuntimeError(
                    f"Refusing to CREATE DATABASE with non-alphanumeric name {test_db_name!r}"
                )
            cur.execute(f'CREATE DATABASE "{test_db_name}"')
        cur.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def app():
    """Boot the app under TestConfig with a fresh schema."""

    _ensure_test_database()

    # Import here so any ``DATABASE_URL`` already in the environment doesn't
    # get inherited by the application factory before TestConfig overrides it.
    from app import create_app
    from app.extensions import db

    application = create_app("testing")
    ctx = application.app_context()
    ctx.push()
    db.create_all()

    # ``db.create_all()`` does not run Alembic data seeds; several flows (e.g.
    # password reset) expect default email template rows.
    from app.email.services import ensure_seed_templates
    from app.settings.services import ensure_seed_settings

    ensure_seed_templates()
    ensure_seed_settings()

    yield application

    db.session.remove()
    try:
        db.drop_all()
    except Exception:
        # Some optional tables may not exist in lightweight local schemas.
        db.session.rollback()
    ctx.pop()


@pytest.fixture
def client(app):
    """A Flask test client. Cookies persist across calls inside a single test."""

    return app.test_client()


# ---------------------------------------------------------------------------
# Per-test data isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def db_isolation(request):
    """Wipe every table after each test so ordering does not leak state."""
    if request.node.get_closest_marker("no_db_isolation"):
        yield
        return

    request.getfixturevalue("app")
    from app.extensions import db

    yield

    # If a test left an open/failed transaction, clear it first.
    db.session.rollback()
    # Drop the scoped session so a poisoned Postgres transaction (e.g. aborted
    # mid-test) cannot leak into the per-table DELETE pass below.
    db.session.remove()

    from sqlalchemy.exc import InternalError, OperationalError, ProgrammingError

    # sorted_tables is parent->child; reverse so child rows are deleted first.
    for table in reversed(db.metadata.sorted_tables):
        try:
            db.session.execute(table.delete())
        except (ProgrammingError, InternalError, OperationalError):
            # Missing table (optional models) or aborted transaction — skip and reset.
            db.session.rollback()

    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    finally:
        # Clear identity map so stale ORM objects cannot be reused.
        db.session.remove()


@pytest.fixture
def organization(app):
    from app.extensions import db
    from app.organizations.models import Organization

    org = Organization(name=f"Test Org {secrets.token_hex(3)}")
    db.session.add(org)
    # Flush keeps the row persisted for dependent fixtures while avoiding
    # commit-time expiration of the ORM instance.
    db.session.flush()
    return org


@pytest.fixture
def regular_user(organization):
    """Non-superadmin user. ``password_plain`` is stashed on the row for tests."""

    from app.extensions import db
    from app.users.models import User, UserRole

    user = User(
        email=_unique_email("user"),
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()

    user.password_plain = "UserPass123!"
    return user


@pytest.fixture
def admin_user(organization):
    """Organization admin user. ``password_plain`` is stashed for tests."""

    from app.extensions import db
    from app.users.models import User, UserRole

    user = User(
        email=_unique_email("adminuser"),
        password_hash=generate_password_hash("AdminUserPass123!"),
        organization_id=organization.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()

    user.password_plain = "AdminUserPass123!"
    return user


@pytest.fixture
def superadmin(organization):
    """Superadmin with TOTP already enabled. ``totp_secret`` exposed for tests."""

    from app.extensions import db
    from app.users.models import User, UserRole

    secret = pyotp.random_base32()
    user = User(
        email=_unique_email("superadmin"),
        password_hash=generate_password_hash("AdminPass123!"),
        organization_id=organization.id,
        role=UserRole.SUPERADMIN.value,
        is_active=True,
        totp_secret=secret,
        is_2fa_enabled=True,
    )
    db.session.add(user)
    db.session.commit()

    user.password_plain = "AdminPass123!"
    return user


@pytest.fixture
def api_key(regular_user):
    """Active API key for the regular user. Raw token is on ``key.raw``."""

    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="Test key",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes=DEFAULT_TEST_API_SCOPES,
    )
    db.session.add(key)
    db.session.commit()

    key.raw = raw
    return key
