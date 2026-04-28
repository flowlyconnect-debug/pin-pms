# Pindora Lock Integration

This module is implemented under `app/integrations/pindora_lock/` with:

- `client.py`: raw HTTP calls, auth headers, timeout, webhook signature verification
- `service.py`: business-level entrypoints for provisioning/revoking access codes
- `adapter.py`: pure payload normalization functions

## Endpoints currently used (placeholder)

- `POST /devices/{provider_device_id}/codes`
- `DELETE /devices/{provider_device_id}/codes/{provider_code_id}`

These are temporary placeholders until the official vendor API documentation is confirmed.

## Environment variables

- `PINDORA_LOCK_BASE_URL`
- `PINDORA_LOCK_API_KEY`
- `PINDORA_LOCK_WEBHOOK_SECRET`
- `PINDORA_LOCK_TIMEOUT_SECONDS`
- `CHECKIN_FERNET_KEY` (optional; encrypts uploaded check-in ID documents at rest)

## Local run notes

1. Set the env variables above in `.env`.
2. Start stack with `docker compose up`.
3. Run tests with:
   - `docker compose exec -e POSTGRES_HOST=db -e POSTGRES_PORT=5432 web pytest -q`

## Test account

No real vendor account is required for tests. Integration tests use mocked HTTP responses.
