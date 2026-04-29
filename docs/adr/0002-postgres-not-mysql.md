# ADR-0002: PostgreSQL, not MySQL

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, database

## Context

The system requires reliable transactional behavior, mature migrations, and predictable SQLAlchemy support for multi-tenant data modeling.

## Decision

Standardize on PostgreSQL as the primary relational database.

## Consequences

- Strong transactional consistency for billing/audit flows.
- Existing migration and ops tooling remain unchanged.
- MySQL-specific hosting options are intentionally deprioritized.
