FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

# Production default: validate migration graph, run migrations, then start Gunicorn.
# Local dev overrides this via docker-compose.yml (uses `flask run` for auto-reload).
CMD ["sh", "-c", "python safe_migrate.py && exec gunicorn --bind 0.0.0.0:5000 --workers 3 --access-logfile - --error-logfile - run:app"]
