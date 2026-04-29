# Deploy templates

Reference configurations for running Pin PMS on a Linux host with
Nginx + systemd + Gunicorn (project brief section 1).

These are *examples* — copy them, replace placeholder hostnames and
paths with the real ones for your environment, and review every directive
before enabling.

## Files

| File | Target | Purpose |
|---|---|---|
| `nginx.conf.example` | `/etc/nginx/sites-available/pindora.conf` | TLS termination + reverse proxy in front of Gunicorn |
| `pindora.service.example` | `/etc/systemd/system/pindora.service` | systemd unit running Gunicorn + Flask |

## Bringing it up

```bash
# 1) Project + virtualenv (one-time)
sudo mkdir -p /opt/pindora
sudo chown $USER:$USER /opt/pindora
git clone <repo-url> /opt/pindora
cd /opt/pindora
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # edit with real secrets

# 2) Database
sudo -u postgres createuser pindora
sudo -u postgres createdb -O pindora pindora
.venv/bin/flask db upgrade
.venv/bin/flask create-superadmin

# 3) systemd
sudo cp deploy/pindora.service.example /etc/systemd/system/pindora.service
sudo systemctl daemon-reload
sudo systemctl enable --now pindora.service
journalctl -u pindora -n 50

# 4) Nginx
sudo cp deploy/nginx.conf.example /etc/nginx/sites-available/pindora.conf
sudo ln -s /etc/nginx/sites-available/pindora.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## Notes

- `BACKUP_DIR` and `UPLOADS_DIR` must be on durable storage (volume,
  ZFS dataset, or off-host). The unit's `ReadWritePaths` whitelist must
  include both.
- TLS material in the example assumes `certbot` defaults; substitute the
  paths your CA produces.
- The Gunicorn worker count (`--workers 3`) is a starting point.
  Tune via `2 * cores + 1` and Linux load testing.
