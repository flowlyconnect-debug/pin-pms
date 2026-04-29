# Webhook Events

## Signature

- Every inbound and outbound webhook must include HMAC signature header:
  - `X-PMS-Signature: sha256=<hex>`
- Signature payload: raw request body bytes.
- Verify with shared secret from environment variables.

## Retry policy

- Retry schedule: 30s, 2m, 10m, 1h, 6h.
- Maximum attempts: 5.

## Event: `reservation.created`

- Trigger: reservation successfully created.
- Example payload:
```json
{
  "event_type": "reservation.created",
  "id": "evt_123",
  "organization_id": 1,
  "data": { "reservation_id": 42 }
}
```
- JSON Schema:
```json
{
  "type": "object",
  "required": ["event_type", "id", "organization_id", "data"],
  "properties": {
    "event_type": { "const": "reservation.created" },
    "id": { "type": "string" },
    "organization_id": { "type": "integer" },
    "data": {
      "type": "object",
      "required": ["reservation_id"],
      "properties": { "reservation_id": { "type": "integer" } }
    }
  }
}
```
