# ADR-0003: Flask-Login sessions over JWT for admin

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, auth

## Context

The admin and operator interfaces are browser-first, server-rendered, and require session controls plus CSRF protection.

## Decision

Use Flask-Login cookie-backed sessions for admin/superadmin flows instead of JWT.

## Consequences

- Cleaner integration with existing form-based UI.
- Easier superadmin 2FA gating and session invalidation.
- JWT remains available for API-key style integrations only where needed.
