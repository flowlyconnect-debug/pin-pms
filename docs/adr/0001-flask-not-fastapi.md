# ADR-0001: Flask, not FastAPI

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, framework

## Context

The product started as a server-rendered admin application with Flask-Login, CSRF forms, and a mature Flask extension ecosystem already in use.

## Decision

Continue using Flask as the primary web framework instead of migrating to FastAPI.

## Consequences

- Preserves existing auth/session and template workflows.
- Lower migration risk and faster delivery for current roadmap.
- Async-first workloads remain a future optimization area.
