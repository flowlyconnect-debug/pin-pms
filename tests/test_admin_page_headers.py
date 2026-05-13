"""Admin list pages: main heading must not duplicate the shared topbar title."""

from __future__ import annotations

import re

import pytest
from bs4 import BeautifulSoup


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _main_visible_text(html: str) -> str:
    """Visible text inside ``#main-content`` only (excludes sidebar, mobile nav, command palette)."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("#main-content")
    assert main is not None
    for tag in main.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(s for s in main.stripped_strings)


def _word_count(text: str, word: str) -> int:
    return len(re.findall(rf"\b{re.escape(word)}\b", text))


@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/admin/properties", "Kohteet"),
        ("/admin/reservations", "Varaukset"),
        ("/admin/guests", "Asiakkaat"),
        ("/admin/reports", "Raportit"),
    ],
)
def test_admin_list_page_heading_once_in_main(client, admin_user, path: str, heading: str):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get(path)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "<title>" in html
    visible = _main_visible_text(html)
    assert _word_count(visible, heading) == 1, (
        f"expected exactly one {heading!r} in #main-content visible text, got {_word_count(visible, heading)}"
    )


def test_no_duplicate_page_title_h1_in_properties_list(client, admin_user):
    """Content must not repeat the page title as an extra H1 (topbar carries ``page_title``)."""
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    soup = BeautifulSoup(client.get("/admin/properties").get_data(as_text=True), "html.parser")
    main = soup.select_one("#main-content")
    assert main is not None
    assert not main.select("h1.page-title")
