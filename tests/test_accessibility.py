from __future__ import annotations

import re
from pathlib import Path


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=True)


def _template_path(rel_path: str) -> Path:
    return Path(__file__).resolve().parent.parent / "app" / "templates" / rel_path


def test_images_have_alt():
    template_paths = [
        _template_path("admin/base.html"),
        _template_path("portal/base.html"),
        _template_path("accessibility.html"),
    ]
    img_pattern = re.compile(r"<img\b([^>]*)>", re.IGNORECASE | re.MULTILINE)
    alt_pattern = re.compile(r'\balt\s*=\s*"[^"]*"', re.IGNORECASE)

    for path in template_paths:
        content = path.read_text(encoding="utf-8")
        for img in img_pattern.findall(content):
            assert alt_pattern.search(img), f"Missing alt attribute in {path}"


def test_form_inputs_have_labels():
    template_paths = [
        _template_path("admin/payments/list.html"),
        _template_path("admin/_filters.html"),
        _template_path("portal/login.html"),
    ]
    input_pattern = re.compile(r"<input\b([^>]*)>", re.IGNORECASE | re.MULTILINE)
    id_pattern = re.compile(r'\bid\s*=\s*"([^"]+)"', re.IGNORECASE)
    type_pattern = re.compile(r'\btype\s*=\s*"([^"]+)"', re.IGNORECASE)
    aria_label_pattern = re.compile(r'\baria-label\s*=\s*"[^"]+"', re.IGNORECASE)

    for path in template_paths:
        content = path.read_text(encoding="utf-8")
        for match in input_pattern.finditer(content):
            attrs = match.group(1)
            input_type_match = type_pattern.search(attrs)
            input_type = input_type_match.group(1).strip().lower() if input_type_match else "text"
            if input_type in {"hidden", "submit", "button"}:
                continue
            if aria_label_pattern.search(attrs):
                continue

            input_id_match = id_pattern.search(attrs)
            assert input_id_match, f"Input missing id or aria-label in {path}: {match.group(0)}"
            input_id = input_id_match.group(1)
            label_for_pattern = re.compile(
                rf'<label[^>]*for\s*=\s*"{re.escape(input_id)}"[^>]*>',
                re.IGNORECASE | re.MULTILINE,
            )
            assert label_for_pattern.search(
                content
            ), f"Missing label for input #{input_id} in {path}"


def test_lang_attribute_set(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    admin_res = client.get("/admin/")
    assert admin_res.status_code == 200
    admin_html = admin_res.get_data(as_text=True)
    assert re.search(r"<html[^>]*\slang=\"[a-z]{2}(?:-[A-Z]{2})?\"", admin_html)

    portal_res = client.get("/portal/login")
    assert portal_res.status_code == 200
    portal_html = portal_res.get_data(as_text=True)
    assert re.search(r"<html[^>]*\slang=\"[a-z]{2}(?:-[A-Z]{2})?\"", portal_html)


def test_skip_link_present(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    admin_html = client.get("/admin/").get_data(as_text=True)
    assert 'class="skip-link"' in admin_html
    assert 'href="#main-content"' in admin_html

    portal_html = client.get("/portal/login").get_data(as_text=True)
    assert ('class="skip-link"' in portal_html) or ('class="pms-login-skip"' in portal_html)


def test_accessibility_page_status_200(client):
    response = client.get("/accessibility")
    assert response.status_code == 200


def test_accessibility_page_extends_portal_base(client):
    html = client.get("/accessibility").get_data(as_text=True)
    assert 'class="skip-link"' in html or "portal-nav" in html


def test_accessibility_page_has_correct_finnish_chars(client):
    html = client.get("/accessibility").get_data(as_text=True)
    assert "Tämä" in html
    assert "järjestelmän" in html
    assert "välttämättä" in html
    assert "Tama" not in html
    assert "jarjestelman" not in html
    assert "valttamatta" not in html


def test_accessibility_template_is_utf8_without_bom():
    path = _template_path("accessibility.html")
    data = path.read_bytes()
    assert not data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8")
    assert "Tämä" in text
    assert "järjestelmän" in text
    assert "Saavutettavuusseloste" in text
    assert "välttämättä" in text


def test_accessibility_link_exists_in_footer_if_present_requirement(client):
    portal_base = _template_path("portal/base.html").read_text(encoding="utf-8")
    admin_base = _template_path("admin/base.html").read_text(encoding="utf-8")
    link_expected = (
        "url_for('core.accessibility_statement')" in portal_base
        or "url_for('core.accessibility_statement')" in admin_base
    )
    if link_expected:
        html = client.get("/accessibility").get_data(as_text=True)
        assert 'href="/accessibility"' in html
