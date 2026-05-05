#!/bin/sh
set -eu

echo "START_SH_RUNNING"
echo "PORT=${PORT:-missing}"
ls -la /app
python --version
python safe_migrate.py
exec gunicorn --bind 0.0.0.0:${PORT:-10000} --workers 1 --access-logfile - --error-logfile - run:app
