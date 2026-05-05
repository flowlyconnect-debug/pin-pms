from flask import Blueprint

email_bp = Blueprint("email", __name__)

from app.email.models import EmailQueueItem  # noqa: E402,F401
from app.email.scheduler import process_email_queue  # noqa: E402,F401
