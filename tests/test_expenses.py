from __future__ import annotations

from decimal import Decimal


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_expense_create_audits(app, organization, admin_user):
    from app.audit.models import AuditLog
    from app.expenses import services as expense_service
    from app.extensions import db
    from app.properties.models import Property

    prop = Property(organization_id=organization.id, name="Audit house", address=None)
    db.session.add(prop)
    db.session.commit()
    row = expense_service.create_expense(
        organization_id=organization.id,
        property_id=prop.id,
        category="maintenance",
        amount_raw="100.00",
        vat_raw="24.00",
        date_raw="2026-05-01",
        description="Fix sink",
        payee="Handyman Oy",
        actor_user_id=admin_user.id,
    )
    assert row.amount == Decimal("100.00")
    assert AuditLog.query.filter_by(action="expense.created", target_id=row.id).first() is not None


def test_reports_tenant_isolation(app, client, organization, admin_user):
    from app.expenses import services as expense_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    other_org = Organization(name="Other org")
    db.session.add(other_org)
    db.session.flush()
    other_admin = User(
        email="other-admin@test.local",
        password_hash=generate_password_hash("OtherAdminPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_admin)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Other prop", address=None)
    db.session.add(other_prop)
    db.session.commit()
    expense_service.create_expense(
        organization_id=other_org.id,
        property_id=other_prop.id,
        category="cleaning",
        amount_raw="55.00",
        vat_raw="0",
        date_raw="2026-04-10",
        description="Other tenant",
        payee="Cleaner",
        actor_user_id=other_admin.id,
    )
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    rv = client.get("/admin/reports/expenses-breakdown?start_date=2026-04-01&end_date=2026-04-30")
    assert rv.status_code == 200
    assert "55.00" not in rv.data.decode("utf-8")

