"""Playwright E2E fixtures: live Flask server (SQLite) + seed data.

Design
------
* The suite is self-contained: it boots the real app (``create_app("testing")``)
  against a throwaway SQLite file, so no Postgres or Docker is needed.
* A werkzeug dev server runs in a background thread for the whole session;
  each test gets freshly seeded rows and the DB is wiped between tests.
* Browser automation comes from ``pytest-playwright`` (fixtures ``page``,
  ``context`` etc.). Install browsers once with:  ``python -m playwright install chromium``.

Run:  ``pytest e2e --browser chromium``  (or ``make test-e2e``).
"""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pyotp
import pytest
from werkzeug.security import generate_password_hash

# ---------------------------------------------------------------------------
# Environment must be fixed BEFORE any ``app`` import: TestConfig reads
# TEST_DATABASE_URL at class-definition (import) time.
# ---------------------------------------------------------------------------
_E2E_DB_PATH = Path(tempfile.gettempdir()) / f"pindora_e2e_{os.getpid()}.sqlite3"
os.environ["TEST_DATABASE_URL"] = f"sqlite+pysqlite:///{_E2E_DB_PATH.as_posix()}"
os.environ.setdefault("FORCE_SQLITE_TEST_DB", "1")

ADMIN_PASSWORD = "E2eAdminPass123!"
SUPERADMIN_PASSWORD = "E2eSuperPass123!"
PORTAL_PASSWORD = "E2ePortalPass123!"


def pytest_collection_modifyitems(items):
    for item in items:
        item.add_marker(pytest.mark.e2e)


# ---------------------------------------------------------------------------
# Application + live server (session scope)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def flask_app():
    from app import create_app
    from app.extensions import db

    application = create_app("testing")
    # Real browser flows should exercise CSRF like production does.
    application.config["WTF_CSRF_ENABLED"] = True

    ctx = application.app_context()
    ctx.push()
    db.create_all()

    from app.email.services import ensure_seed_templates
    from app.settings.services import ensure_seed_settings

    ensure_seed_templates()
    ensure_seed_settings()

    yield application

    db.session.remove()
    try:
        db.drop_all()
    except Exception:
        db.session.rollback()
    ctx.pop()
    try:
        _E2E_DB_PATH.unlink(missing_ok=True)
    except OSError:
        pass


@pytest.fixture(scope="session")
def live_server(flask_app):
    """Serve the app on an ephemeral localhost port for the whole session."""

    from werkzeug.serving import make_server

    server = make_server("127.0.0.1", 0, flask_app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    yield base_url
    server.shutdown()
    thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Per-test data isolation + seed
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _db_isolation(flask_app):
    """Wipe every table after each test (mirrors tests/conftest.py)."""

    from app.extensions import db

    yield

    db.session.rollback()
    db.session.remove()
    for table in reversed(db.metadata.sorted_tables):
        try:
            db.session.execute(table.delete())
        except Exception:
            db.session.rollback()
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    finally:
        db.session.remove()

    # Re-seed rows the app expects on every request (login page etc.).
    from app.email.services import ensure_seed_templates
    from app.settings.services import ensure_seed_settings

    ensure_seed_templates()
    ensure_seed_settings()


@dataclass
class SeedData:
    org_id: int
    admin_email: str
    superadmin_email: str
    superadmin_totp_secret: str
    portal_email: str
    portal_user_id: int
    property_id: int
    property_name: str
    unit_id: int
    unit_name: str
    guest_id: int
    guest_name: str
    extra: dict = field(default_factory=dict)

    # Booking window used by reservation tests (far future, deterministic).
    @property
    def check_in(self) -> date:
        return date.today() + timedelta(days=30)

    @property
    def check_out(self) -> date:
        return date.today() + timedelta(days=33)


@pytest.fixture()
def seed(flask_app) -> SeedData:
    """Organization + admin + superadmin(TOTP) + portal user + property/unit/guest."""

    from app.extensions import db
    from app.guests.models import Guest
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    org = Organization(name="E2E Org")
    db.session.add(org)
    db.session.commit()

    admin = User(
        email="e2e-admin@example.com",
        password_hash=generate_password_hash(ADMIN_PASSWORD),
        organization_id=org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    totp_secret = pyotp.random_base32()
    superadmin = User(
        email="e2e-superadmin@example.com",
        password_hash=generate_password_hash(SUPERADMIN_PASSWORD),
        organization_id=org.id,
        role=UserRole.SUPERADMIN.value,
        is_active=True,
        totp_secret=totp_secret,
        is_2fa_enabled=True,
    )
    portal_user = User(
        email="e2e-guest@example.com",
        password_hash=generate_password_hash(PORTAL_PASSWORD),
        organization_id=org.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add_all([admin, superadmin, portal_user])

    prop = Property(organization_id=org.id, name="E2E Kohde", city="Helsinki")
    db.session.add(prop)
    db.session.commit()

    unit = Unit(property_id=prop.id, name="Huone 101")
    db.session.add(unit)
    guest = Guest(
        organization_id=org.id,
        first_name="Erkki",
        last_name="Esimerkki",
        email="erkki@example.com",
        phone="+358401234567",
    )
    db.session.add(guest)
    db.session.commit()

    return SeedData(
        org_id=org.id,
        admin_email=admin.email,
        superadmin_email=superadmin.email,
        superadmin_totp_secret=totp_secret,
        portal_email=portal_user.email,
        portal_user_id=portal_user.id,
        property_id=prop.id,
        property_name=prop.name,
        unit_id=unit.id,
        unit_name=unit.name,
        guest_id=guest.id,
        guest_name="Erkki Esimerkki",
    )


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------


def login(page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("button[type=submit]")


@pytest.fixture()
def admin_page(page, live_server, seed):
    """A page already logged in as the organization admin."""

    login(page, live_server, seed.admin_email, ADMIN_PASSWORD)
    page.wait_for_url("**/admin/**")
    return page


@pytest.fixture()
def superadmin_page(page, live_server, seed):
    """A page logged in as superadmin with the TOTP step completed."""

    login(page, live_server, seed.superadmin_email, SUPERADMIN_PASSWORD)
    page.wait_for_url("**/2fa/verify**")
    code = pyotp.TOTP(seed.superadmin_totp_secret).now()
    page.fill("input[name=code]", code)
    page.click("button[type=submit]")
    page.wait_for_url("**/admin/**")
    return page
