from __future__ import annotations

import re
from html.parser import HTMLParser

from app.extensions import db
from app.properties.models import Property, Unit


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.scripts.append(dict(attrs))


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_admin_calendar_get_returns_200_and_nonce_scripts(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Calendar Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    db.session.add(Unit(property_id=prop.id, name="A1", unit_type="double"))
    db.session.commit()

    response = client.get("/admin/calendar")
    assert response.status_code == 200

    html = response.get_data(as_text=True)
    parser = _ScriptParser()
    parser.feed(html)

    # Local admin calendar logic must come from a static JS file.
    assert any(script.get("src", "").endswith("/static/js/admin-calendar.js") for script in parser.scripts)
    # Inline event handlers are forbidden under strict CSP.
    assert re.search(r"\son[a-zA-Z]+\s*=", html) is None


def test_calendar_sync_view_renders_when_no_feeds(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/calendar-sync/conflicts")
    assert response.status_code == 200
    assert "Ristiriitoja ei löytynyt." in response.get_data(as_text=True)


def test_calendar_sync_view_renders_when_scheduler_disabled(client, admin_user, monkeypatch):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    def _raise_scheduler_error(*args, **kwargs):
        raise RuntimeError("scheduler offline")

    monkeypatch.setattr(
        "app.admin.routes.IcalService.detect_conflicts",
        _raise_scheduler_error,
    )

    response = client.get("/admin/calendar-sync/conflicts")
    assert response.status_code == 200
    assert "Kalenteriristiriitojen lataus epäonnistui." in response.get_data(as_text=True)
