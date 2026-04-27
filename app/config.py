import os


class BaseConfig:
    SECRET_KEY = os.getenv("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL", "postgresql+psycopg2://postgres:postgres@db:5432/pindora"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Session cookie hardening (safe defaults for all environments).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Rate limit values per project brief section 18.
    LOGIN_RATE_LIMIT = os.getenv("LOGIN_RATE_LIMIT", "5/minute")
    API_RATE_LIMIT = os.getenv("API_RATE_LIMIT", "100/hour")

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

    # Billing scheduler (runs alongside backup scheduler when enabled).
    INVOICE_OVERDUE_SCHEDULER_ENABLED = os.getenv(
        "INVOICE_OVERDUE_SCHEDULER_ENABLED", "1"
    ).lower() in {"1", "true", "yes"}
    INVOICE_OVERDUE_SCHEDULE_CRON = os.getenv("INVOICE_OVERDUE_SCHEDULE_CRON", "30 6 * * *")


class DevelopmentConfig(BaseConfig):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


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
