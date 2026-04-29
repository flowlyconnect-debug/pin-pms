# ADR-0004: APScheduler over Celery

- Status: Accepted
- Date: 2026-04-29
- Deciders: Core backend team
- Tags: architecture, jobs

## Context

Current scheduled workloads are periodic and limited in throughput (backups, sync jobs, cleanups) with modest operational complexity targets.

## Decision

Use APScheduler for in-process scheduled jobs instead of introducing Celery.

## Consequences

- Lower infrastructure overhead and faster local development.
- Sufficient for current cron-style background tasks.
- Future high-volume async workloads may require reevaluation.
