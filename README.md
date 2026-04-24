# Pindora PMS - Flask SaaS Base

Initial secure SaaS skeleton for a PMS system using Flask with an application factory pattern.
This repository contains only the project foundation, not PMS business features.

## Tech Stack

- Flask
- SQLAlchemy
- Flask-Migrate
- PostgreSQL
- Docker Compose

## Project Structure

```text
app/
  __init__.py
  config.py
  extensions.py
  core/
  auth/
  admin/
  api/
  users/
  email/
  backups/
migrations/
tests/
.env.example
requirements.txt
Dockerfile
docker-compose.yml
run.py
```

## Getting Started

1. Copy env example:
   - `cp .env.example .env`
2. Update `.env` with strong values, especially:
   - `SECRET_KEY`
   - `POSTGRES_PASSWORD`
3. Build and run:
   - `docker compose up --build`
4. Check health endpoint:
   - [http://localhost:5000/health](http://localhost:5000/health)

## Notes

- No authentication, 2FA, or PMS models are included yet.
- Secrets are loaded from environment variables.
- Production mode requires `SECRET_KEY`.
