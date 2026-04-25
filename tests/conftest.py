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
  test so ordering does not leak state between tests.
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

import os

import psycopg2
import pyotp
import pytest
from werkzeug.security import generate_password_hash


# ---------------------------------------------------------------------------
# Resolve test connection params from POSTGRES_* (raw, unencoded).
# ---------------------------------------------------------------------------


def _conn_params() -> dict[str, object]:
    """Plain connection parameters as pytest sees them — never URL-encoded."""

    return {
        "host": os.getenv("POSTGRES_HOST", "db"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
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

    p = _conn_params()
    user = _percent_encode(str(p["user"]))
    password = _percent_encode(str(p["password"]))
    return (
        f"postgresql+psycopg2://{user}:{password}@{p['host']}:{p['port']}/pindora_test"
    )


# Set TEST_DATABASE_URL at module-import time so :class:`TestConfig` (whose
# class-level attribute reads ``os.getenv("TEST_DATABASE_URL")`` at import
# time) sees the right value before ``create_app("testing")`` runs.
if not os.environ.get("TEST_DATABASE_URL"):
    os.environ["TEST_DATABASE_URL"] = _build_test_database_url()


# ---------------------------------------------------------------------------
# One-time DB bootstrap — creates pindora_test if missing.
# ---------------------------------------------------------------------------


def _ensure_test_database() -> None:
    """Create the test database if Postgres does not already have it."""

    p = _conn_params()
    test_db_name = "pindora_test"

    conn = psycopg2.connect(
        host=p["host"],
        port=p["port"],
        user=p["user"],
        password=p["password"],
        dbname="postgres",
    )
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

    yield application

    db.session.remove()
    db.drop_all()
    ctx.pop()


@pytest.fixture
def client(app):
    """A Flask test client. Cookies persist across calls inside a single test."""

    return app.test_client()


# ---------------------------------------------------------------------------
# Per-test data isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def db_isolation(app):
    """Wipe every table after each test so ordering does not leak state."""

    from app.extensions import db

    yield

    # ``sorted_tables`` returns parents-before-children; reversing flips that
    # so we delete child rows before the parents they reference.
    for table in reversed(db.metadata.sorted_tables):
        db.session.execute(table.delete())
    db.session.commit()


# ---------------------------------------------------------------------------
# Data fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def organization(app):
    from app.extensions import db
    from app.organizations.models import Organization

    org = Organization(name="Test Org")
    db.session.add(org)
    db.session.commit()
    return org


@pytest.fixture
def regular_user(organization):
    """Non-superadmin user. ``password_plain`` is stashed on the row for tests."""

    from app.extensions import db
    from app.users.models import User, UserRole

    user = User(
        email="user@test.local",
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
def superadmin(organization):
    """Superadmin with TOTP already enabled. ``totp_secret`` exposed for tests."""

    from app.extensions import db
    from app.users.models import User, UserRole

    secret = pyotp.random_base32()
    user = User(
        email="admin@test.local",
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
        scopes="",
    )
    db.session.add(key)
    db.session.commit()

    key.raw = raw
    return key
