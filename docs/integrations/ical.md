# iCal Integration

## What this integration does

- Exposes tenant unit reservations as read-only iCal feeds via `GET /api/v1/units/<id>/calendar.ics`.
- Imports external iCal feeds (Airbnb/Booking.com) as availability blocks only.
- Detects overlap conflicts between imported blocks and internal reservations.

## Endpoints used

- `GET /api/v1/units/<id>/calendar.ics?token=<signed>`
  - Returns an `.ics` calendar built from `units.reservations`.
  - No normal auth required; access controlled by HMAC token.

## Admin UI

- `/admin/units/<id>/calendar-sync`
  - Shows export URL for copy/paste into channels.
  - Stores external iCal source URLs for that unit.
  - Allows manual sync trigger.
- `/admin/calendar-sync/conflicts`
  - Lists detected overlaps.

## Environment variables

- `ICAL_FEED_SECRET`: secret used to sign feed URLs.
- `ICAL_HTTP_TIMEOUT_SECONDS`: timeout for remote iCal fetch.
- `ICAL_SYNC_ENABLED`: enable background polling scheduler (`1/0`).
- `ICAL_SYNC_INTERVAL_MINUTES`: poll interval in minutes.

## Local run

1. Set `ICAL_FEED_SECRET` in `.env`.
2. Run app normally (`docker compose up` or `flask run`).
3. Open unit sync page in admin and add iCal source URL.
4. Trigger manual sync from UI or wait for scheduler.

## Testing

- Adapter tests parse `.ics` payload into normalized event blocks.
- Client tests mock HTTP fetch behavior and timeout/header usage.

