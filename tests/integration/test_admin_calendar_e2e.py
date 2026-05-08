from __future__ import annotations

import pytest

pytestmark = pytest.mark.skip(
    reason="Browser E2E framework (Playwright/Selenium) is not configured in this repository."
)


def test_calendar_event_click_middle_opens_reservation():
    """Smoke placeholder for browser click-through flow."""
    pass


def test_calendar_empty_day_click_shows_empty_day_message():
    """Smoke placeholder for empty-day click feedback."""
    pass
