from flask import g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
# CSRF protection for all state-changing non-API forms. The public API is
# exempted in ``app/__init__.py`` because it authenticates with API keys
# instead of browser-bound sessions.
csrf = CSRFProtect()


def _rate_limit_key() -> str:
    """Return the bucket key for rate limiting.

    For API requests where ``g.api_key`` has been populated by
    :func:`app.api.auth.require_api_key`, we bucket per API key so that one
    noisy client cannot exhaust an entire NAT egress IP. For everything else
    (including unauthenticated API calls and all browser traffic) we fall back
    to the remote address.
    """

    api_key = getattr(g, "api_key", None)
    if api_key is not None and getattr(api_key, "id", None) is not None:
        return f"api_key:{api_key.id}"
    return get_remote_address()


# In-memory storage is intentional: the project brief does not mandate Redis,
# and the values are env-driven (``API_RATE_LIMIT``, ``LOGIN_RATE_LIMIT``).
# When the app eventually scales to multiple Gunicorn workers or hosts, swap
# ``storage_uri`` to a Redis URL — the limit decorators stay unchanged.
limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri="memory://",
    headers_enabled=True,
)
