# ADR-0006: Mailgun as primary email provider

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, email

## Context

Transactional email delivery is central to password resets, notifications, and operational workflows. Team already has Mailgun integration and templates.

## Decision

Use Mailgun as the default and only production email provider for now.

## Consequences

- One stable provider path simplifies support and observability.
- Faster delivery of email-related features.
- Provider abstraction can be added later if requirements change.
