"""Maintenance request email notifications to the maintenance contact."""

from __future__ import annotations

import logging

import pytest


def _property_and_unit(*, organization_id: int, maintenance_email: str | None = None):
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(
        organization_id=organization_id,
        name="Maint Notify Hotel",
        address=None,
        maintenance_email=maintenance_email,
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="201", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def _seed_maintenance_template() -> None:
    from app.email.services import ensure_seed_templates

    ensure_seed_templates()


@pytest.fixture
def maintenance_notify_setup(app):
    _seed_maintenance_template()
    app.config["MAIL_DEV_LOG_ONLY"] = False


def test_create_queues_email_to_property_maintenance_address(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch
):
    from app.audit.models import AuditLog
    from app.email.models import OutgoingEmail, TemplateKey
    from app.maintenance import services as maintenance_service

    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="property-maint@test.local",
    )
    queued: list[dict] = []

    def _capture_send(key: str, *, to: str, context=None) -> bool:
        queued.append({"key": key, "to": to, "context": dict(context or {})})
        return True

    monkeypatch.setattr("app.maintenance.services.send_template", _capture_send)

    row = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Broken window",
        description="Lobby glass",
        priority="normal",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )
    assert row["id"] > 0
    assert len(queued) == 1
    assert queued[0]["key"] == TemplateKey.MAINTENANCE_REQUEST
    assert queued[0]["to"] == "property-maint@test.local"
    assert queued[0]["context"]["property_name"] == "Maint Notify Hotel"
    assert queued[0]["context"]["unit_name"] == "201"
    assert "maintenance-requests" in queued[0]["context"]["maintenance_url"]

    audit = (
        AuditLog.query.filter_by(
            action="maintenance_request.email_queued",
            target_id=row["id"],
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.context.get("event_type") == "created"
    assert audit.context.get("recipient_email") == "pr***@test.local"
    assert "Lobby glass" not in (audit.context or {})


def test_property_email_wins_over_org_default(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch
):
    from app.maintenance import services as maintenance_service
    from app.settings import services as settings_service

    settings_service.set_value(
        "maintenance.default_email",
        "org-default@test.local",
        type_="string",
        description="test",
        is_secret=False,
        actor_user_id=admin_user.id,
    )
    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="property-wins@test.local",
    )
    sent_to: list[str] = []
    monkeypatch.setattr(
        "app.maintenance.services.send_template",
        lambda key, *, to, context=None: sent_to.append(to) or True,
    )

    maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Leak",
        description=None,
        priority="low",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )
    assert sent_to == ["property-wins@test.local"]


def test_missing_recipient_logs_warning_without_exception(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch, caplog
):
    from app.maintenance import services as maintenance_service
    from app.settings import services as settings_service

    settings_service.set_value(
        "maintenance.default_email",
        "",
        type_="string",
        description="test",
        is_secret=False,
        actor_user_id=admin_user.id,
    )
    prop, unit = _property_and_unit(organization_id=organization.id, maintenance_email=None)
    monkeypatch.setattr(
        "app.maintenance.services.send_template",
        lambda *args, **kwargs: pytest.fail("send_template should not be called"),
    )

    with caplog.at_level(logging.WARNING):
        row = maintenance_service.create_maintenance_request(
            organization_id=organization.id,
            property_id=prop.id,
            unit_id=unit.id,
            guest_id=None,
            reservation_id=None,
            title="No email target",
            description=None,
            priority="normal",
            status="new",
            due_date_raw=None,
            assigned_to_id=None,
            actor_user_id=admin_user.id,
        )
    assert row["id"] > 0
    assert any("no maintenance recipient email" in r.message for r in caplog.records)


def test_notifications_disabled_skips_send(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch
):
    from app.maintenance import services as maintenance_service
    from app.settings import services as settings_service

    settings_service.set_value(
        "maintenance.email_notifications_enabled",
        False,
        type_="bool",
        description="test",
        is_secret=False,
        actor_user_id=admin_user.id,
    )
    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="disabled@test.local",
    )
    monkeypatch.setattr(
        "app.maintenance.services.send_template",
        lambda *args, **kwargs: pytest.fail("send_template should not be called"),
    )

    maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Muted",
        description=None,
        priority="urgent",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )


def test_maintenance_request_template_renders_variables(app, maintenance_notify_setup):
    from app.email.services import render_template

    rendered = render_template(
        "maintenance_request",
        {
            "property_name": "Hotelli A",
            "unit_name": "101",
            "priority": "Kiireellinen",
            "status": "new",
            "description": "Vesivuoto keittiössä",
            "maintenance_url": "https://pms.example/admin/maintenance-requests/9",
            "from_name": "Pin PMS",
        },
    )
    assert "Hotelli A" in rendered.subject
    assert "Vesivuoto keittiössä" in rendered.text
    assert "https://pms.example/admin/maintenance-requests/9" in rendered.text
    assert rendered.html is not None
    assert "Kiireellinen" in rendered.html


def test_urgent_priority_sends_only_on_change(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch
):
    from app.maintenance import services as maintenance_service

    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="urgent@test.local",
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "app.maintenance.services.send_template",
        lambda key, *, to, context=None: calls.append(to) or True,
    )

    created = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Already urgent",
        description=None,
        priority="urgent",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 1

    maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=created["id"],
        data={"priority": "urgent", "title": "Still urgent"},
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 1

    maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=created["id"],
        data={"priority": "high"},
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 1

    maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=created["id"],
        data={"priority": "urgent"},
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 2


def test_assignee_change_sends_only_on_change(
    app, organization, admin_user, maintenance_notify_setup, monkeypatch
):
    from app.extensions import db
    from app.maintenance import services as maintenance_service
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="assign@test.local",
    )
    assignee = User(
        email="assignee-maint@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=organization.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(assignee)
    db.session.commit()

    calls: list[str] = []
    monkeypatch.setattr(
        "app.maintenance.services.send_template",
        lambda key, *, to, context=None: calls.append(to) or True,
    )

    created = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="With assignee at create",
        description=None,
        priority="normal",
        status="new",
        due_date_raw=None,
        assigned_to_id=assignee.id,
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 1

    maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=created["id"],
        data={"assigned_to_id": assignee.id},
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 1

    maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=created["id"],
        data={"assigned_to_id": None},
        actor_user_id=admin_user.id,
    )
    assert len(calls) == 2


def test_send_template_queues_real_row(
    app, organization, admin_user, maintenance_notify_setup
):
    from app.email.models import OutgoingEmail, OutgoingEmailStatus, TemplateKey
    from app.maintenance import services as maintenance_service

    prop, unit = _property_and_unit(
        organization_id=organization.id,
        maintenance_email="queue-row@test.local",
    )
    row = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Queue integration",
        description="Details",
        priority="high",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )
    queued = OutgoingEmail.query.filter_by(
        to="queue-row@test.local",
        template_key=TemplateKey.MAINTENANCE_REQUEST,
    ).first()
    assert queued is not None
    assert queued.status == OutgoingEmailStatus.PENDING
    assert queued.context_json.get("property_name") == "Maint Notify Hotel"
    assert row["id"] > 0


def test_seed_email_templates_idempotent(app):
    from app.email.models import EmailTemplate
    from app.email.services import ensure_seed_templates

    ensure_seed_templates()
    count_before = EmailTemplate.query.filter_by(key="maintenance_request").count()
    ensure_seed_templates()
    count_after = EmailTemplate.query.filter_by(key="maintenance_request").count()
    assert count_before == 1
    assert count_after == 1
