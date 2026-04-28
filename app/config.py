import os
import socket
import sys
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy.engine.url import make_url

_DB_ENV_KEYS = frozenset(
    {
        "DATABASE_URL",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
    }
)


def _env_for_database() -> dict[str, str]:
    """Process environment plus project ``.env`` for DB keys (``.env`` wins).

    ``load_dotenv()`` does not override variables already set in the shell; that
    breaks local login when Cursor or the OS still has a stale ``DATABASE_URL``.
    Under pytest we skip merging so ``TEST_DATABASE_URL`` / conftest stay authoritative.
    """

    merged: dict[str, str] = {k: v for k, v in os.environ.items() if isinstance(v, str)}
    if "pytest" in sys.modules:
        return merged
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.is_file():
        return merged
    try:
        from dotenv import dotenv_values
    except ImportError:
        return merged
    file_vals = dotenv_values(env_path) or {}
    file_keys = {k for k, v in file_vals.items() if v is not None and str(v).strip() != ""}
    # Typical dev ``.env``: ``POSTGRES_*`` without ``DATABASE_URL``. A stale ``DATABASE_URL``
    # in the IDE/shell would otherwise win over ``load_dotenv()`` and break login.
    if any(k.startswith("POSTGRES_") for k in file_keys) and "DATABASE_URL" not in file_keys:
        merged.pop("DATABASE_URL", None)
    for key, val in file_vals.items():
        if key not in _DB_ENV_KEYS or val is None:
            continue
        s = str(val).strip()
        if s:
            merged[key] = s
    return merged


def _db_get(key: str, default: str | None = None) -> str | None:
    v = _env_for_database().get(key)
    if v is None or v == "":
        return default
    return v


def _loopback_if_compose_hostname_unresolvable(host: str, *, port: int = 5432) -> str:
    """Return ``127.0.0.1`` when host is the Compose default ``db`` but DNS fails.

    ``.env`` often sets ``DATABASE_URL=...@db:5432/...`` or ``POSTGRES_HOST=db`` so
    the stack works inside Docker. On the developer host the same file is used
    with ``docker compose port`` / published 5432 — then ``db`` does not resolve.
    """

    h = (host or "").strip()
    if h != "db":
        return h
    try:
        socket.getaddrinfo(h, port, type=socket.SOCK_STREAM)
    except OSError:
        return "127.0.0.1"
    return h


def _coerce_database_url_host(url: str) -> str:
    try:
        u = make_url(url)
    except Exception:
        return url
    if not u.host:
        return url
    port = int(u.port or 5432)
    new_host = _loopback_if_compose_hostname_unresolvable(u.host, port=port)
    if new_host == u.host:
        return url
    return str(u.set(host=new_host))


def _apply_postgres_port_env(url: str) -> str:
    """If ``POSTGRES_PORT`` is set, align the URL port (fixes stale shell ``DATABASE_URL``).

    Skip when the host is a Docker Compose service name (``db``): the in-network port
    stays the container's 5432.
    """

    raw = (_db_get("POSTGRES_PORT") or "").strip()
    if not raw:
        return url
    try:
        u = make_url(url)
    except Exception:
        return url
    host = (u.host or "").strip().lower()
    if host in {"db", "database"}:
        return url
    try:
        port = int(raw)
    except ValueError:
        return url
    if port <= 0:
        return url
    try:
        if int(u.port or 5432) == port:
            return url
        return str(u.set(port=port))
    except Exception:
        return url


def _default_database_url() -> str:
    port_str = _db_get("POSTGRES_PORT", "5432") or "5432"
    try:
        port = int(port_str or "5432")
    except ValueError:
        port = 5432
    host = _loopback_if_compose_hostname_unresolvable(
        (_db_get("POSTGRES_HOST", "127.0.0.1") or "127.0.0.1").strip() or "127.0.0.1",
        port=port,
    )
    user = _db_get("POSTGRES_USER", "postgres") or "postgres"
    password = _db_get("POSTGRES_PASSWORD", "postgres") or "postgres"
    if (password or "").strip().lower() in {
        "replace-with-strong-password",
        "replace_me",
        "changeme",
    }:
        password = "postgres"
    database = _db_get("POSTGRES_DB", "pindora") or "pindora"
    return (
        f"postgresql+psycopg2://{quote_plus(user)}:{quote_plus(password)}"
        f"@{host}:{port}/{database}"
    )


def _unmask_placeholder_database_url(url: str) -> str:
    """Replace log-style masked passwords (``***`` / ``%2A%2A%2A``) with ``POSTGRES_PASSWORD``."""

    lower = url.lower()
    if ":***@" not in url and ":%2a%2a%2a@" not in lower:
        return url
    password = _db_get("POSTGRES_PASSWORD") or "postgres"
    if (password or "").strip().lower() in {
        "replace-with-strong-password",
        "replace_me",
        "changeme",
    }:
        password = "postgres"
    quoted = quote_plus(password)
    out = url.replace(":***@", f":{quoted}@")
    out = out.replace(":%2A%2A%2A@", f":{quoted}@")
    out = out.replace(":%2a%2a%2a@", f":{quoted}@")
    return out


def _resolved_database_url() -> str:
    explicit = _db_get("DATABASE_URL")
    if not explicit:
        raw = _default_database_url()
    else:
        raw = explicit.replace(":replace-with-strong-password@", ":postgres@")
        raw = _unmask_placeholder_database_url(raw)
    raw = _coerce_database_url_host(raw)
    return _apply_postgres_port_env(raw)


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = _resolved_database_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # Session cookie hardening (safe defaults for all environments).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Rate limit values per project brief section 18.
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
    API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "100/hour")
    PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "12"))

    # Mailgun outbound email -- project brief section 7.
    MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
    MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
    MAILGUN_BASE_URL = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")
    MAILGUN_FROM_EMAIL = (
        os.getenv("MAILGUN_FROM_EMAIL")
        or os.getenv("MAIL_FROM")
        or "noreply@example.com"
    )
    MAILGUN_FROM_NAME = (
        os.getenv("MAILGUN_FROM_NAME")
        or os.getenv("MAIL_FROM_NAME")
        or "Pindora PMS"
    )
    MAIL_FROM = MAILGUN_FROM_EMAIL
    MAIL_FROM_NAME = MAILGUN_FROM_NAME
    MAIL_DEV_LOG_ONLY = os.getenv("MAIL_DEV_LOG_ONLY", "0").lower() in {"1", "true", "yes"}
    EMAIL_SCHEDULER_ENABLED = os.getenv("EMAIL_SCHEDULER_ENABLED", "1").lower() in {
        "1", "true", "yes",
    }

    # CORS -- project brief section 10.
    CORS_ALLOWED_ORIGINS = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    ]

    # Backups -- project brief section 8.
    BACKUP_DIR = os.getenv("BACKUP_DIR", "/var/backups/pindora")
    UPLOADS_DIR = os.getenv("UPLOADS_DIR", "/var/lib/pindora/uploads")
    BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))
    BACKUP_SCHEDULE_CRON = os.getenv("BACKUP_SCHEDULE_CRON", "0 3 * * *")
    BACKUP_SCHEDULER_ENABLED = os.getenv("BACKUP_SCHEDULER_ENABLED", "1").lower() in {
        "1", "true", "yes",
    }
    BACKUP_NOTIFY_EMAIL = os.getenv("BACKUP_NOTIFY_EMAIL", "")
    # Optional S3-compatible off-site backup upload (AWS S3, B2, Wasabi, MinIO).
    BACKUP_S3_ENABLED = os.getenv("BACKUP_S3_ENABLED", "0").lower() in {"1", "true", "yes"}
    BACKUP_S3_ENDPOINT_URL = os.getenv("BACKUP_S3_ENDPOINT_URL", "")
    BACKUP_S3_BUCKET = os.getenv("BACKUP_S3_BUCKET", "")
    BACKUP_S3_ACCESS_KEY = os.getenv("BACKUP_S3_ACCESS_KEY", "")
    BACKUP_S3_SECRET_KEY = os.getenv("BACKUP_S3_SECRET_KEY", "")
    BACKUP_S3_PREFIX = os.getenv("BACKUP_S3_PREFIX", "pindora-pms/")

    # Billing scheduler (runs alongside backup scheduler when enabled).
    INVOICE_OVERDUE_SCHEDULER_ENABLED = os.getenv(
        "INVOICE_OVERDUE_SCHEDULER_ENABLED", "1"
    ).lower() in {"1", "true", "yes"}
    INVOICE_OVERDUE_SCHEDULE_CRON = os.getenv("INVOICE_OVERDUE_SCHEDULE_CRON", "30 6 * * *")
    API_USAGE_RETENTION_DAYS = int(os.getenv("API_USAGE_RETENTION_DAYS", "90"))

    # Pindora lock integration.
    PINDORA_LOCK_BASE_URL = os.getenv("PINDORA_LOCK_BASE_URL", "")
    PINDORA_LOCK_API_KEY = os.getenv("PINDORA_LOCK_API_KEY", "")
    PINDORA_LOCK_WEBHOOK_SECRET = os.getenv("PINDORA_LOCK_WEBHOOK_SECRET", "")
    PINDORA_LOCK_TIMEOUT_SECONDS = int(os.getenv("PINDORA_LOCK_TIMEOUT_SECONDS", "10"))

    # iCal integration.
    ICAL_FEED_SECRET = os.getenv("ICAL_FEED_SECRET", "") or SECRET_KEY or ""
    ICAL_HTTP_TIMEOUT_SECONDS = int(os.getenv("ICAL_HTTP_TIMEOUT_SECONDS", "10"))
    ICAL_SYNC_ENABLED = os.getenv("ICAL_SYNC_ENABLED", "1").lower() in {"1", "true", "yes"}
    ICAL_SYNC_INTERVAL_MINUTES = int(os.getenv("ICAL_SYNC_INTERVAL_MINUTES", "15"))

    # Guest check-in document encryption (Fernet key, base64 urlsafe 32-byte key).
    CHECKIN_FERNET_KEY = os.getenv("CHECKIN_FERNET_KEY", "")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False
    # Flask sessions, CSRF (e.g. login form), and Flask-Login need a key. Without
    # this, GET /login raises RuntimeError when SECRET_KEY is unset in the env.
    SECRET_KEY = os.getenv("SECRET_KEY") or "dev-only-insecure-secret-change-me"


class ProductionConfig(BaseConfig):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class TestConfig(BaseConfig):
    TESTING = True
    DEBUG = False
    SESSION_COOKIE_SECURE = False
    RATELIMIT_ENABLED = False
    WTF_CSRF_ENABLED = False
    MAIL_DEV_LOG_ONLY = True
    # Flask sessions and login_user() require a key; tests must not depend on
    # host ``.env``. Production still requires SECRET_KEY via env (see create_app).
    SECRET_KEY = os.getenv("SECRET_KEY", "test-only-secret-key-do-not-use-in-production")
    # Never call Mailgun during tests even if the host .env sets real keys.
    MAILGUN_API_KEY = ""
    MAILGUN_DOMAIN = ""
    EMAIL_SCHEDULER_ENABLED = False
    BACKUP_SCHEDULER_ENABLED = False
    INVOICE_OVERDUE_SCHEDULER_ENABLED = False
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg2://postgres:postgres@127.0.0.1:5432/pindora_test",
    )


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestConfig,
    "default": DevelopmentConfig,
}
