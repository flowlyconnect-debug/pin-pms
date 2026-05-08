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
            '<p><a href="{{ login_url }}">Sign in</a></p>'
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
            '<p><a href="{{ reset_url }}">Reset password</a></p>'
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
            '<p>Your sign-in code is: <strong style="font-size:1.4rem">{{ code }}</strong></p>'
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
            '<p style="color:#b91c1c"><strong>The backup {{ backup_name }} failed</strong> '
            "at {{ failed_at }}.</p>"
            '<pre style="background:#f5f5f5;padding:.75rem;border-radius:4px">'
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
        "body_text": ("{{ message }}\n\n" "— {{ from_name }}\n"),
        "body_html": ("<p>{{ message }}</p>" "<p>— {{ from_name }}</p>"),
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
            "Invoice {{ invoice_number }} (due {{ due_date }})\n"
            "Subtotal excl. VAT: {{ subtotal_excl_vat }} {{ currency }}\n"
            "VAT ({{ vat_rate }}%): {{ vat_amount }} {{ currency }}\n"
            "Total incl. VAT: {{ total_incl_vat }} {{ currency }}\n"
            "{{ description }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hello,</p>"
            "<p>Invoice <strong>{{ invoice_number }}</strong> — due "
            "<strong>{{ due_date }}</strong></p>"
            "<table style=\"border-collapse:collapse;margin:.5rem 0\">"
            "<tr><td style=\"padding:.25rem .75rem .25rem 0\">Subtotal (excl. VAT)</td>"
            "<td><strong>{{ subtotal_excl_vat }} {{ currency }}</strong></td></tr>"
            "<tr><td style=\"padding:.25rem .75rem .25rem 0\">VAT ({{ vat_rate }}%)</td>"
            "<td><strong>{{ vat_amount }} {{ currency }}</strong></td></tr>"
            "<tr><td style=\"padding:.25rem .75rem .25rem 0\">Total (incl. VAT)</td>"
            "<td><strong>{{ total_incl_vat }} {{ currency }}</strong></td></tr>"
            "</table>"
            "<p>{{ description }}</p>"
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Placeholder for future invoice-created notifications (not sent automatically yet).",
        "available_variables": [
            "invoice_number",
            "amount",
            "subtotal_excl_vat",
            "vat_rate",
            "vat_amount",
            "total_incl_vat",
            "currency",
            "due_date",
            "description",
            "from_name",
        ],
    },
    {
        "key": "invoice_overdue",
        "subject": "Erääntynyt lasku {{ invoice_number }}",
        "body_text": (
            "Hei,\n\n"
            "Lasku {{ invoice_number }} erääntyi {{ due_date }} ja on nyt erääntynyt.\n"
            "Summa: {{ amount }} {{ currency }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hei,</p>"
            "<p>Lasku <strong>{{ invoice_number }}</strong> erääntyi "
            "<strong>{{ due_date }}</strong> ja on nyt erääntynyt.</p>"
            "<p>Summa: {{ amount }} {{ currency }}</p>"
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
        "subject": "Lasku {{ invoice_number }} maksettu",
        "body_text": (
            "Hei,\n\n"
            "Kiitos. Lasku {{ invoice_number }} on merkitty maksetuksi.\n"
            "Summa: {{ amount }} {{ currency }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hei,</p>"
            "<p>Kiitos. Lasku <strong>{{ invoice_number }}</strong> on merkitty maksetuksi.</p>"
            "<p>Summa: {{ amount }} {{ currency }}</p>"
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
    {
        "key": "lease_sign_request",
        "subject": "Vuokrasopimus allekirjoitettavaksi",
        "body_text": (
            "Hei {{ tenant_name }},\n\n"
            "Sinulle on lahetetty vuokrasopimus allekirjoitettavaksi.\n"
            "Sopimus #{{ lease_id }}\n"
            "Vuokra: {{ rent_amount }}\n"
            "Laskutusjakso: {{ billing_cycle }}\n"
            "Voimassa: {{ lease_start_date }} - {{ lease_end_date }}\n\n"
            "Allekirjoita taalla: {{ sign_url }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hei {{ tenant_name }},</p>"
            "<p>Sinulle on lahetetty vuokrasopimus allekirjoitettavaksi.</p>"
            "<ul>"
            "<li>Sopimus #{{ lease_id }}</li>"
            "<li>Vuokra: {{ rent_amount }}</li>"
            "<li>Laskutusjakso: {{ billing_cycle }}</li>"
            "<li>Voimassa: {{ lease_start_date }} - {{ lease_end_date }}</li>"
            "</ul>"
            '<p><a href="{{ sign_url }}">Avaa allekirjoituslinkki</a></p>'
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Vuokrasopimuksen allekirjoituspyynto asiakkaalle.",
        "available_variables": [
            "tenant_name",
            "lease_id",
            "rent_amount",
            "billing_cycle",
            "lease_start_date",
            "lease_end_date",
            "sign_url",
            "from_name",
        ],
    },
    {
        "key": "payment_link",
        "subject": "Maksulinkki laskulle {{ invoice_number }}",
        "body_text": (
            "Hei,\n\n"
            "Tässä on linkki laskusi {{ invoice_number }} maksamiseen:\n"
            "{{ payment_url }}\n\n"
            "— {{ from_name }}\n"
        ),
        "body_html": (
            "<p>Hei,</p>"
            "<p>Tässä on linkki laskusi <strong>{{ invoice_number }}</strong> maksamiseen:</p>"
            '<p><a href="{{ payment_url }}">Avaa maksusivu</a></p>'
            "<p>— {{ from_name }}</p>"
        ),
        "description": "Maksulinkki asiakkaalle.",
        "available_variables": ["invoice_number", "payment_url", "from_name"],
    },
    {
        "key": "payment_received",
        "subject": "Maksu vastaanotettu",
        "body_text": "Maksusi on vastaanotettu — kuitti liitteenä.\n\n— {{ from_name }}\n",
        "body_html": "<p>Maksusi on vastaanotettu — kuitti liitteenä.</p><p>— {{ from_name }}</p>",
        "description": "Maksun onnistumisviesti.",
        "available_variables": ["invoice_number", "amount", "currency", "from_name"],
    },
    {
        "key": "payment_failed",
        "subject": "Maksu epäonnistui",
        "body_text": "Maksusi epäonnistui, yritä uudestaan.\n\n— {{ from_name }}\n",
        "body_html": "<p>Maksusi epäonnistui, yritä uudestaan.</p><p>— {{ from_name }}</p>",
        "description": "Maksun epäonnistumisviesti.",
        "available_variables": ["invoice_number", "from_name"],
    },
    {
        "key": "refund_completed",
        "subject": "Hyvitys suoritettu",
        "body_text": "Hyvitys on suoritettu tilillenne.\n\n— {{ from_name }}\n",
        "body_html": "<p>Hyvitys on suoritettu tilillenne.</p><p>— {{ from_name }}</p>",
        "description": "Hyvityksen valmistumisviesti.",
        "available_variables": ["invoice_number", "amount", "currency", "from_name"],
    },
]
