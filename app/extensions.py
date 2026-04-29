from flask import g
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
cors = CORS()


def _rate_limit_key():
    api_key = getattr(g, "api_key", None)
    if api_key is not None and getattr(api_key, "id", None) is not None:
        return f"api_key:{api_key.id}"
    return get_remote_address()


limiter = Limiter(
    key_func=_rate_limit_key,
    storage_uri="memory://",
    headers_enabled=True,
)
