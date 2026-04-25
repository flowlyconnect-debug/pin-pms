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
