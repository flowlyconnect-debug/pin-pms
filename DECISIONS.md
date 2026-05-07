## Module pruning review — 2026-05-07

### `app/subscriptions/`
- **Findings:** `SubscriptionPlan` is imported in app startup model registration, linked from `Organization.subscription_plan_id`, read by API rate-limit resolution, and covered by `tests/test_api_rate_limits.py`.
- **In use:** Yes.
- **Decision:** keep.
- **Rationale:** This is not FK-only dead code; removing it would impact API throttling behavior and require schema work.

### `app/owner_portal/`
- **Findings:** Blueprint is registered in app factory, owner routes/templates exist, and route behavior is exercised in `tests/test_owners.py`; services have dedicated tests.
- **In use:** Yes, but production rollout status is not provable from repository-only signals.
- **Decision:** feature-flag.
- **Rationale:** Keep module intact while gating registration behind `OWNER_PORTAL_ENABLED` (default false) to avoid exposing unfinished/optional surface by default.

### `app/status/`
- **Findings:** `/api/v1/health/ready` is implemented in API routes and explicitly exercised by multiple tests; README documents status models/service usage.
- **In use:** Yes.
- **Decision:** keep.
- **Rationale:** Endpoint and related status service are active and tested; no safe removal/flagging case found.

### `app/integrations/pindora_lock/`
- **Findings:** Integration has config keys in `.env.example`, README and docs; code paths are referenced from webhook/portal flows and covered by tests.
- **In use:** Potentially yes; deployment enablement is env-driven.
- **Decision:** keep (document only).
- **Rationale:** Retain integration; activation depends on deploy environment variables.

### `app/integrations/ical/`
- **Findings:** iCal config keys are present in `.env.example` and docs; adapter/service/scheduler are wired and covered by `tests/test_ical_integration.py`.
- **In use:** Potentially yes; deployment enablement is env-driven.
- **Decision:** keep (document only).
- **Rationale:** Retain integration; activation depends on deploy environment variables.

### `app/payments/`
- **Findings:** No clear dead branch/stub markers were found with TODO/deprecated/unused scans inside `app/payments`.
- **In use:** Yes, heavily.
- **Decision:** keep.
- **Rationale:** Business-critical payment flows remain untouched without explicit dead-code proof and test-backed safety.
