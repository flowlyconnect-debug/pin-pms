"""Centralised application settings.

Per project brief section 9, the application has a single ``settings`` table
and code must read/write through the service layer in
:mod:`app.settings.services` — never via direct ``Setting.query`` calls. That
indirection lets us add per-request caching, secret masking, and audit hooks
in one place.
"""
