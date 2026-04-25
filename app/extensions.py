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
