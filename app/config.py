import os


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@db:5432/pindora"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session cookie hardening (safe defaults for all environments).
    # SECURE is intentionally only enforced in production where HTTPS is available.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Rate limit values per project brief section 18. They are env-driven so
    # ops can tighten or relax them without a redeploy. Use Flask-Limiter's
    # human-readable syntax: ``"<count>/<period>"`` (e.g. ``5/minute``,
    # ``100/hour``).
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
    API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "100/hour")

    # Mailgun outbound email — project brief section 7. Templates themselves
    # live in the ``email_templates`` table so superadmins can edit them at
    # runtime; only the transport credentials are read from env.
    MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
    MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
    MAILGUN_BASE_URL = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net/v3")
    MAIL_FROM = os.getenv("MAIL_FROM", "noreply@example.com")
    MAIL_FROM_NAME = os.getenv("MAIL_FROM_NAME", "Pindora PMS")
    # When set to "1" / "true", emails are *logged* instead of sent. Useful for
    # local development without a real Mailgun account. Production deployments
    # must keep this off.
    MAIL_DEV_LOG_ONLY = os.getenv("MAIL_DEV_LOG_ONLY", "0").lower() in {"1", "true", "yes"}


class DevelopmentConfig(BaseConfig):
    DEBUG = True

    # Dev runs over HTTP, so SECURE must stay off or the cookie is never sent.
    SESSION_COOKIE_SECURE = False


class ProductionConfig(BaseConfig):
    DEBUG = False

    # Production is served over HTTPS only.
    SESSION_COOKIE_SECURE = True


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "default": DevelopmentConfig,
}
