"""Default content for the six email templates required by section 7.

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
]
