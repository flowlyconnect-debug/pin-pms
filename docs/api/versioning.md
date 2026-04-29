# API Versioning Policy

- Current stable version is `/api/v1`.
- New major versions are created only for breaking changes.
- Older major versions stay supported for at least 12 months after new major release.
- Deprecation signaling uses response headers:
  - `X-Pms-Deprecation: true`
  - `Sunset: <rfc1123-date>`
- Admin UI in `/admin/api-keys` should display per-key API version usage and warnings for soon-to-sunset versions.
