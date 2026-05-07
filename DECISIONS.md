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

## Template pruning review — 2026-05-07

- **Scan scope:** `app/templates/**/*` (110 template files found).
- **Obsolete-name scan:** searched `*.old.html`, `*.bak.html`, `*.backup.html`, `*copy*.html`, `*old*.html`, `*bak*.html`.
- **Result:** no matching obsolete/copy template filenames were found.
- **Decision:** remove nothing.
- **Safety note:** because no candidate files matched obsolete naming patterns, no template deletions were performed and no `render_template`/Jinja reference checks were needed for deletion safety in this pass.

## Route pruning review — 2026-05-07

- **Route listing method:** `python -m flask --app app routes --sort endpoint`.
- **Usage evidence collected:** template `url_for()`/`href` scans, route usage scans in tests, and blueprint registration scan in `app/__init__.py`.
- **Dead-route candidates:** none with high-confidence deletion safety.
- **Notable outcome:** `owner_portal` routes are now explicitly gated by `OWNER_PORTAL_ENABLED`; with flag disabled, those endpoints are intentionally absent instead of silently exposed.
- **Decision:** keep all currently registered API/admin/portal/auth/backups/webhook routes; no route removals in this pass.
- **Needs product decision:** none raised in this pass because no low-risk dead endpoint had sufficient evidence for deletion.
