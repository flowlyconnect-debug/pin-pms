# ADR-0005: Shared DB, tenant isolation by organization_id

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, multi-tenant

## Context

The platform serves multiple organizations and must keep data isolated while staying operationally simple for deployment and backups.

## Decision

Use one shared PostgreSQL database and enforce tenant isolation via `organization_id` in application and service-layer queries.

## Consequences

- Simpler operational model and migration lifecycle.
- Requires strict discipline in every data mutation/query path.
- Test coverage must continuously validate cross-tenant isolation.
