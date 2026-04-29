# ADR-0007: Pindora as first lock vendor

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, integrations

## Context

Smart-lock workflows are required for property access automation and partner commitments. The first committed integration is with Pindora.

## Decision

Implement Pindora as the first lock vendor under `app/integrations/pindora_lock/` with client/service/adapter separation.

## Consequences

- Delivers immediate lock integration value.
- Creates a reusable integration pattern for future vendors.
- Additional vendors should follow the same folder contract for consistency.
