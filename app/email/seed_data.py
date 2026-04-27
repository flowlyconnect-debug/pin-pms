"""Default content for system email templates.

The values here are seeded by the migration that creates the
``email_templates`` table and are also consulted at runtime by
``ensure_seed_templates`` so a fresh deployment never finds a missing key.

Editors with a superadmin role can override any of these from the admin UI;
this file only defines the *defaults* that ship with the codebase.
"""
from __future__ import annotations

from typing import TypedDict


class TemplateSeed(TypedDict):
    key: str
    subject: str
    body_text: str
    body_html: str | None
    description: str
    available_variables: list[str]


SEED_TEMPLATES: list[TemplateSeed] = [
    {
        "key": "welcome_email",
        "subject": "Welcome to {{ organization_name }}",
        "body_text": (
            "Hi {{ user_email }},\n\n"
            "Your account at {{ organization_name }} has been created.\n"
            "Sign in here: {{ login_url }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hi <strong>{{ user_email }}</strong>,</p>"
            "<p>Your account at <strong>{{ organization_name }}</strong> has been created.</p>"
            "<p><a href=\"{{ login_url }}\">Sign in</a></p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Sent to a user when their account is provisioned.",
        "available_variables": [
            "user_email",
            "organization_name",
            "login_url",
            "from_name",
        ],
    },
    {
        "key": "password_reset",
        "subject": "Reset your password",
        "body_text": (
            "Hi {{ user_email }},\n\n"
            "Use the link below to set a new password. The link expires in "
            "{{ expires_minutes }} minutes.\n"
            "{{ reset_url }}\n\n"
            "If you did not request this, you can ignore this email.\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hi <strong>{{ user_email }}</strong>,</p>"
            "<p>Use the link below to set a new password. The link expires in "
            "<strong>{{ expires_minutes }}</strong> minutes.</p>"
            "<p><a href=\"{{ reset_url }}\">Reset password</a></p>"
            "<p>If you did not request this, you can ignore this email.</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Password reset link for the self-service flow.",
        "available_variables": [
            "user_email",
            "reset_url",
            "expires_minutes",
            "from_name",
        ],
    },
    {
        "key": "login_2fa_code",
        "subject": "Your sign-in code",
        "body_text": (
            "Hi {{ user_email }},\n\n"
            "Your sign-in code is: {{ code }}\n"
            "It expires in {{ expires_minutes }} minutes.\n\n"
            "If you did not try to sign in, change your password and contact your "
            "administrator immediately.\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hi <strong>{{ user_email }}</strong>,</p>"
            "<p>Your sign-in code is: <strong style=\"font-size:1.4rem\">{{ code }}</strong></p>"
            "<p>It expires in <strong>{{ expires_minutes }}</strong> minutes.</p>"
            "<p>If you did not try to sign in, change your password and contact your "
            "administrator immediately.</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Backup email-based 2FA code for users without an authenticator.",
        "available_variables": [
            "user_email",
            "code",
            "expires_minutes",
            "from_name",
        ],
    },
    {
        "key": "backup_completed",
        "subject": "Backup completed: {{ backup_name }}",
        "body_text": (
            "Backup {{ backup_name }} completed successfully at "
            "{{ completed_at }}.\n"
            "Size: {{ size_human }}\n"
            "Location: {{ location }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Backup <strong>{{ backup_name }}</strong> completed successfully at "
            "{{ completed_at }}.</p>"
            "<ul>"
            "<li>Size: {{ size_human }}</li>"
            "<li>Location: <code>{{ location }}</code></li>"
            "</ul>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Sent to ops when a scheduled backup finishes successfully.",
        "available_variables": [
            "backup_name",
            "completed_at",
            "size_human",
            "location",
            "from_name",
        ],
    },
    {
        "key": "backup_failed",
        "subject": "BACKUP FAILED: {{ backup_name }}",
        "body_text": (
            "The backup {{ backup_name }} failed at {{ failed_at }}.\n\n"
            "Error: {{ error_message }}\n\n"
            "Investigate immediately. The previous successful backup is still "
            "available, but new data is not yet protected.\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p style=\"color:#b91c1c\"><strong>The backup {{ backup_name }} failed</strong> "
            "at {{ failed_at }}.</p>"
            "<pre style=\"background:#f5f5f5;padding:.75rem;border-radius:4px\">"
            "{{ error_message }}</pre>"
            "<p>Investigate immediately. The previous successful backup is still "
            "available, but new data is not yet protected.</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Sent to ops when a scheduled backup fails.",
        "available_variables": [
            "backup_name",
            "failed_at",
            "error_message",
            "from_name",
        ],
    },
    {
        "key": "admin_notification",
        "subject": "{{ subject_line }}",
        "body_text": (
            "{{ message }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>{{ message }}</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": (
            "Generic admin alert used for ad-hoc operational notifications "
            "(e.g. restore completed, suspicious activity)."
        ),
        "available_variables": [
            "subject_line",
            "message",
            "from_name",
        ],
    },
    {
        "key": "reservation_confirmation",
        "subject": "Reservation confirmed (#{{ reservation_id }})",
        "body_text": (
            "Hello {{ user_email }},\n\n"
            "Your reservation #{{ reservation_id }} is confirmed.\n"
            "Unit: {{ unit_name }}\n"
            "Dates: {{ start_date }} to {{ end_date }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello <strong>{{ user_email }}</strong>,</p>"
            "<p>Your reservation <strong>#{{ reservation_id }}</strong> is confirmed.</p>"
            "<ul>"
            "<li>Unit: {{ unit_name }}</li>"
            "<li>Dates: {{ start_date }} to {{ end_date }}</li>"
            "</ul>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Sent to the guest when a reservation is created.",
        "available_variables": [
            "user_email",
            "reservation_id",
            "unit_name",
            "start_date",
            "end_date",
            "from_name",
        ],
    },
    {
        "key": "reservation_cancelled",
        "subject": "Reservation cancelled (#{{ reservation_id }})",
        "body_text": (
            "Hello {{ user_email }},\n\n"
            "Your reservation #{{ reservation_id }} has been cancelled.\n"
            "Unit: {{ unit_name }}\n"
            "Original dates: {{ start_date }} to {{ end_date }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello <strong>{{ user_email }}</strong>,</p>"
            "<p>Your reservation <strong>#{{ reservation_id }}</strong> has been cancelled.</p>"
            "<ul>"
            "<li>Unit: {{ unit_name }}</li>"
            "<li>Original dates: {{ start_date }} to {{ end_date }}</li>"
            "</ul>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Sent to the guest when a reservation is cancelled.",
        "available_variables": [
            "user_email",
            "reservation_id",
            "unit_name",
            "start_date",
            "end_date",
            "from_name",
        ],
    },
    {
        "key": "invoice_created",
        "subject": "Invoice {{ invoice_number }}",
        "body_text": (
            "Hello,\n\n"
            "Invoice {{ invoice_number }} for {{ amount }} {{ currency }} "
            "is due on {{ due_date }}.\n"
            "{{ description }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello,</p>"
            "<p>Invoice <strong>{{ invoice_number }}</strong> for "
            "<strong>{{ amount }} {{ currency }}</strong> is due on "
            "<strong>{{ due_date }}</strong>.</p>"
            "<p>{{ description }}</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Placeholder for future invoice-created notifications (not sent automatically yet).",
        "available_variables": [
            "invoice_number",
            "amount",
            "currency",
            "due_date",
            "description",
            "from_name",
        ],
    },
    {
        "key": "invoice_overdue",
        "subject": "Overdue: invoice {{ invoice_number }}",
        "body_text": (
            "Hello,\n\n"
            "Invoice {{ invoice_number }} was due on {{ due_date }} and is now overdue.\n"
            "Amount: {{ amount }} {{ currency }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello,</p>"
            "<p>Invoice <strong>{{ invoice_number }}</strong> was due on "
            "<strong>{{ due_date }}</strong> and is now overdue.</p>"
            "<p>Amount: {{ amount }} {{ currency }}</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Placeholder for future overdue reminders (not sent automatically yet).",
        "available_variables": [
            "invoice_number",
            "amount",
            "currency",
            "due_date",
            "from_name",
        ],
    },
    {
        "key": "invoice_paid",
        "subject": "Received: invoice {{ invoice_number }}",
        "body_text": (
            "Hello,\n\n"
            "Thank you. Invoice {{ invoice_number }} is marked paid.\n"
            "Amount: {{ amount }} {{ currency }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello,</p>"
            "<p>Thank you. Invoice <strong>{{ invoice_number }}</strong> is marked paid.</p>"
            "<p>Amount: {{ amount }} {{ currency }}</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Placeholder for future paid confirmations (not sent automatically yet).",
        "available_variables": [
            "invoice_number",
            "amount",
            "currency",
            "from_name",
        ],
    },
]
