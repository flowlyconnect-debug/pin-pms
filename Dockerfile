FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    libjpeg62-turbo \
    libopenjp2-7 \
    libtiff6 \
    libfreetype6 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 5000


RUN ls -la /app && python --version && test -f safe_migrate.py
CMD ["/app/start.sh"]
