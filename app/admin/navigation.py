"""Data-driven admin sidebar and settings hub navigation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from flask_login import AnonymousUserMixin
from sqlalchemy import func

from app.extensions import db

NavAccess = Literal["pms", "superadmin", "public"]
ActiveMatch = Literal["exact", "prefix", "any"]


@dataclass(frozen=True)
class NavItem:
    label: str
    endpoint: str
    icon: str
    access: NavAccess = "pms"
    badge_key: str | None = None
    active_match: ActiveMatch = "exact"
    active_endpoints: tuple[str, ...] = ()


@dataclass(frozen=True)
class NavGroup:
    id: str
    title: str
    items: tuple[NavItem, ...]


@dataclass(frozen=True)
class SettingsHubItem:
    label: str
    endpoint: str
    description: str
    access: NavAccess = "superadmin"
    icon: str = "settings"


@dataclass(frozen=True)
class SettingsHubSection:
    id: str
    title: str
    items: tuple[SettingsHubItem, ...]


SIDEBAR_GROUPS: tuple[NavGroup, ...] = (
    NavGroup(
        id="primary",
        title="Päätoiminnot",
        items=(
            NavItem("Etusivu", "admin.admin_home", "dashboard", active_endpoints=("admin.admin_home",)),
            NavItem(
                "Kalenteri",
                "admin.calendar_page",
                "calendar",
                active_match="any",
                active_endpoints=("admin.calendar_page", "admin.calendar_events"),
            ),
            NavItem(
                "Saatavuus",
                "admin.availability_page",
                "calendar_emoji",
                active_endpoints=("admin.availability_page",),
            ),
            NavItem(
                "Varaukset",
                "admin.reservations_list",
                "bookings",
                active_match="prefix",
                active_endpoints=("admin.reservations_",),
            ),
            NavItem(
                "Kohteet",
                "admin.properties_list",
                "building",
                active_match="prefix",
                active_endpoints=("admin.properties_", "admin.units_"),
            ),
            NavItem(
                "Asiakkaat",
                "admin.guests_list",
                "user",
                active_match="prefix",
                active_endpoints=("admin.guests_", "admin.api_guests_search"),
            ),
        ),
    ),
    NavGroup(
        id="finance",
        title="Talous",
        items=(
            NavItem(
                "Laskut",
                "admin.invoices_list",
                "invoice",
                badge_key="open_invoices",
                active_match="prefix",
                active_endpoints=("admin.invoices_",),
            ),
            NavItem(
                "Vuokrasopimukset",
                "admin.leases_list",
                "document",
                active_match="prefix",
                active_endpoints=("admin.leases_",),
            ),
            NavItem(
                "Kulut",
                "admin.expenses_list",
                "document",
                active_match="prefix",
                active_endpoints=("admin.expenses_",),
            ),
            NavItem(
                "Raportit",
                "admin.reports_index",
                "reports",
                active_match="prefix",
                active_endpoints=("admin.reports_",),
            ),
        ),
    ),
    NavGroup(
        id="operations",
        title="Operointi",
        items=(
            NavItem(
                "Huolto",
                "admin.maintenance_requests_list",
                "maintenance",
                active_match="prefix",
                active_endpoints=("admin.maintenance_requests_",),
            ),
            NavItem(
                "Konfliktit",
                "admin.conflicts_page",
                "warning",
                badge_key="conflicts",
                active_match="any",
                active_endpoints=(
                    "admin.conflicts_page",
                    "admin.conflicts_legacy_redirect",
                ),
            ),
            NavItem(
                "Ilmoitukset",
                "admin.notifications_list",
                "bell",
                active_match="prefix",
                active_endpoints=("admin.notifications_",),
            ),
        ),
    ),
)

SETTINGS_NAV_ITEM = NavItem(
    "Asetukset",
    "admin.settings_list",
    "settings",
    access="pms",
    active_match="any",
    active_endpoints=(),
)

SETTINGS_HUB_ACTIVE_ENDPOINTS: frozenset[str] = frozenset(
    {
        "admin.settings_list",
        "admin.settings_new",
        "admin.settings_edit",
        "admin.users_list",
        "admin.users_new",
        "admin.users_edit",
        "admin.organizations_list",
        "admin.organizations_new",
        "admin.organizations_edit",
        "admin.api_keys_list",
        "admin.api_keys_new",
        "admin.api_keys_toggle_active",
        "admin.api_keys_delete",
        "admin.api_keys_usage",
        "admin.webhooks_list",
        "admin.webhooks_detail",
        "admin.webhooks_new",
        "admin.email_templates_list",
        "admin.email_template_edit",
        "admin.email_template_preview",
        "admin.email_template_test_send",
        "admin.lease_templates_list",
        "admin.lease_templates_new",
        "admin.lease_templates_edit",
        "backups_admin.backups_list",
        "backups_admin.backups_create",
        "backups_admin.backups_download",
        "backups_admin.backups_restore",
        "admin.audit",
        "admin.superadmin_status",
        "core.accessibility_statement",
    }
)

SETTINGS_HUB_SECTIONS: tuple[SettingsHubSection, ...] = (
    SettingsHubSection(
        id="users_permissions",
        title="Käyttäjät ja oikeudet",
        items=(
            SettingsHubItem(
                "Käyttäjät",
                "admin.users_list",
                "Hallitse käyttäjiä ja rooleja.",
                icon="users",
            ),
            SettingsHubItem(
                "Organisaatiot",
                "admin.organizations_list",
                "Organisaatiot ja tilaukset.",
                icon="org",
            ),
            SettingsHubItem(
                "API-avaimet",
                "admin.api_keys_list",
                "Integraatioavaimet ja käyttö.",
                icon="key",
            ),
        ),
    ),
    SettingsHubSection(
        id="content",
        title="Sisältö ja viestintä",
        items=(
            SettingsHubItem(
                "Sähköpostipohjat",
                "admin.email_templates_list",
                "Järjestelmän sähköpostipohjat.",
                icon="mail",
            ),
            SettingsHubItem(
                "Sopimuspohjat",
                "admin.lease_templates_list",
                "Vuokrasopimuspohjat organisaatiolle.",
                icon="document",
            ),
        ),
    ),
    SettingsHubSection(
        id="integrations",
        title="Integraatiot",
        items=(
            SettingsHubItem(
                "Webhookit",
                "admin.webhooks_list",
                "Lähtevät webhook-tilaukset.",
                icon="link",
            ),
        ),
    ),
    SettingsHubSection(
        id="system",
        title="Järjestelmä ja ylläpito",
        items=(
            SettingsHubItem(
                "Varmuuskopiot",
                "backups_admin.backups_list",
                "Tietokannan varmuuskopiot ja palautus.",
                icon="server",
            ),
            SettingsHubItem(
                "Audit-loki",
                "admin.audit",
                "Tapahtumaloki ja suodatus.",
                icon="clipboard",
            ),
            SettingsHubItem(
                "Tilannehallinta",
                "admin.superadmin_status",
                "Palvelun tila ja häiriöt.",
                icon="status",
            ),
            SettingsHubItem(
                "Saavutettavuus",
                "core.accessibility_statement",
                "Saavutettavuusseloste.",
                access="public",
                icon="a11y",
            ),
        ),
    ),
)

MOBILE_BOTTOM_ITEMS: tuple[NavItem, ...] = (
    NavItem("Etusivu", "admin.admin_home", "dashboard", active_endpoints=("admin.admin_home",)),
    NavItem(
        "Kohteet",
        "admin.properties_list",
        "building",
        active_match="prefix",
        active_endpoints=("admin.properties_", "admin.units_"),
    ),
    NavItem(
        "Varaukset",
        "admin.reservations_list",
        "bookings",
        active_match="prefix",
        active_endpoints=("admin.reservations_",),
    ),
    NavItem(
        "Laskut",
        "admin.invoices_list",
        "invoice",
        active_match="prefix",
        active_endpoints=("admin.invoices_",),
    ),
)

MOBILE_MORE_ITEMS: tuple[NavItem, ...] = (
    NavItem(
        "Asiakkaat",
        "admin.guests_list",
        "user",
        active_match="prefix",
        active_endpoints=("admin.guests_",),
    ),
    NavItem(
        "Vuokrasopimukset",
        "admin.leases_list",
        "document",
        active_match="prefix",
        active_endpoints=("admin.leases_",),
    ),
    NavItem(
        "Huolto",
        "admin.maintenance_requests_list",
        "maintenance",
        active_match="prefix",
        active_endpoints=("admin.maintenance_requests_",),
    ),
    NavItem(
        "Kalenteri",
        "admin.calendar_page",
        "calendar",
        active_match="any",
        active_endpoints=("admin.calendar_page", "admin.calendar_events"),
    ),
    NavItem(
        "Raportit",
        "admin.reports_index",
        "reports",
        active_match="prefix",
        active_endpoints=("admin.reports_",),
    ),
    SETTINGS_NAV_ITEM,
)


def _user_has_access(access: NavAccess, *, is_superadmin: bool, has_pms: bool) -> bool:
    if access == "public":
        return has_pms
    if access == "superadmin":
        return is_superadmin
    return has_pms


def _user_can_see_nav(user) -> tuple[bool, bool]:
    if not user or isinstance(user, AnonymousUserMixin) or not getattr(user, "is_authenticated", False):
        return False, False
    from app.users.models import UserRole

    has_pms = user.role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}
    is_superadmin = bool(getattr(user, "is_superadmin", False))
    return has_pms, is_superadmin


def count_open_invoices(organization_id: int | None) -> int:
    if organization_id is None:
        return 0
    from app.billing.models import Invoice

    return int(
        db.session.query(func.count())
        .select_from(Invoice)
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.status.in_(("open", "overdue")),
        )
        .scalar()
        or 0
    )


def compute_nav_badges(*, organization_id: int | None) -> dict[str, int]:
    return {"open_invoices": count_open_invoices(organization_id)}


def is_endpoint_active(item: NavItem, endpoint: str) -> bool:
    if item.endpoint == "admin.settings_list":
        return endpoint in SETTINGS_HUB_ACTIVE_ENDPOINTS

    rules = item.active_endpoints or (item.endpoint,)
    if item.active_match == "exact":
        return endpoint in rules
    if item.active_match == "prefix":
        return any(endpoint.startswith(rule) for rule in rules)
    if item.active_match == "any":
        return endpoint in rules or any(endpoint.startswith(rule) for rule in rules if rule.endswith("_"))
    return endpoint == item.endpoint


def filter_nav_item(item: NavItem, *, is_superadmin: bool, has_pms: bool) -> bool:
    return _user_has_access(item.access, is_superadmin=is_superadmin, has_pms=has_pms)


def sidebar_groups_for_user(user) -> list[NavGroup]:
    has_pms, is_superadmin = _user_can_see_nav(user)
    if not has_pms:
        return []
    groups: list[NavGroup] = []
    for group in SIDEBAR_GROUPS:
        items = tuple(
            item for item in group.items if filter_nav_item(item, is_superadmin=is_superadmin, has_pms=has_pms)
        )
        if items:
            groups.append(NavGroup(id=group.id, title=group.title, items=items))
    return groups


def settings_hub_sections_for_user(user) -> list[SettingsHubSection]:
    has_pms, is_superadmin = _user_can_see_nav(user)
    if not has_pms:
        return []
    sections: list[SettingsHubSection] = []
    for section in SETTINGS_HUB_SECTIONS:
        items = tuple(
            item
            for item in section.items
            if _user_has_access(item.access, is_superadmin=is_superadmin, has_pms=has_pms)
        )
        if items:
            sections.append(SettingsHubSection(id=section.id, title=section.title, items=items))
    return sections


def mobile_bottom_items_for_user(user) -> list[NavItem]:
    has_pms, is_superadmin = _user_can_see_nav(user)
    if not has_pms:
        return []
    return [
        item
        for item in MOBILE_BOTTOM_ITEMS
        if filter_nav_item(item, is_superadmin=is_superadmin, has_pms=has_pms)
    ]


def mobile_more_items_for_user(user) -> list[NavItem]:
    has_pms, is_superadmin = _user_can_see_nav(user)
    if not has_pms:
        return []
    return [
        item
        for item in MOBILE_MORE_ITEMS
        if filter_nav_item(item, is_superadmin=is_superadmin, has_pms=has_pms)
    ]


def settings_nav_item_for_user(user) -> NavItem | None:
    has_pms, is_superadmin = _user_can_see_nav(user)
    if not has_pms:
        return None
    if filter_nav_item(SETTINGS_NAV_ITEM, is_superadmin=is_superadmin, has_pms=has_pms):
        return SETTINGS_NAV_ITEM
    return None


def build_nav_context(*, endpoint: str, user) -> dict:
    org_id = None
    if user is not None and not isinstance(user, AnonymousUserMixin):
        try:
            if getattr(user, "is_authenticated", False):
                org_id = getattr(user, "organization_id", None)
        except Exception:
            org_id = None
    badges = compute_nav_badges(organization_id=org_id)
    settings_item = settings_nav_item_for_user(user)

    def _active(item: NavItem) -> bool:
        return is_endpoint_active(item, endpoint)

    return {
        "admin_nav_groups": sidebar_groups_for_user(user),
        "admin_nav_settings_item": settings_item,
        "admin_nav_badges": badges,
        "admin_settings_hub_sections": settings_hub_sections_for_user(user),
        "admin_mobile_bottom_items": mobile_bottom_items_for_user(user),
        "admin_mobile_more_items": mobile_more_items_for_user(user),
        "admin_nav_is_active": _active,
    }
