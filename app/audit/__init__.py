"""Audit logging subsystem.

Records security- and governance-relevant events in a dedicated table so the
operator of the system can answer questions like:

  * Who logged in and from where?
  * When did a superadmin enable 2FA?
  * Which API key was created, by whom, for which user?
  * Were there failed login attempts before a successful one?

The module exposes :func:`record` as the single public entry point used
throughout the app. Import routes at the bottom so the admin blueprint can
attach views without creating a circular import.
"""

from app.audit.services import audit_record, record  # noqa: F401
