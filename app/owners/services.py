from __future__ import annotations

import os
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from io import BytesIO

from flask import Response, current_app
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.owners.models import (
    OwnerPayout,
    OwnerPayoutStatus,
    OwnerUser,
    PropertyOwner,
    PropertyOwnerAssignment,
)
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def parse_period_month(period_month: str) -> tuple[date, date]:
    year, month = period_month.split("-", 1)
    start = date(int(year), int(month), 1)
    end = date(int(year), int(month), monthrange(start.year, start.month)[1])
    return start, end


def create_owner(
    *, organization_id: int, name: str, email: str, phone: str | None, payout_iban: str | None
) -> PropertyOwner:
    row = PropertyOwner(
        organization_id=organization_id,
        name=(name or "").strip(),
        email=(email or "").strip().lower(),
        phone=(phone or "").strip() or None,
        payout_iban=(payout_iban or "").strip() or None,
        is_active=True,
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "owner.created",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="property_owner",
        target_id=row.id,
        context={"email": row.email, "name": row.name},
        commit=False,
    )
    return row


def deactivate_owner(*, owner_id: int, organization_id: int) -> bool:
    row = PropertyOwner.query.filter_by(id=owner_id, organization_id=organization_id).first()
    if row is None:
        return False
    row.is_active = False
    audit_record(
        "owner.deactivated",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="property_owner",
        target_id=row.id,
        commit=False,
    )
    return True


def assign_property(
    *,
    owner_id: int,
    organization_id: int,
    property_id: int,
    ownership_pct: Decimal,
    management_fee_pct: Decimal,
    valid_from: date,
    valid_to: date | None,
) -> PropertyOwnerAssignment:
    owner = PropertyOwner.query.filter_by(id=owner_id, organization_id=organization_id).first()
    if owner is None:
        raise ValueError("Owner not found.")
    prop = Property.query.filter_by(id=property_id, organization_id=organization_id).first()
    if prop is None:
        raise ValueError("Property not found.")
    row = PropertyOwnerAssignment(
        owner_id=owner_id,
        property_id=property_id,
        ownership_pct=ownership_pct,
        management_fee_pct=management_fee_pct,
        valid_from=valid_from,
        valid_to=valid_to,
    )
    db.session.add(row)
    db.session.flush()
    return row


def create_owner_user(*, owner_id: int, email: str, password: str) -> OwnerUser:
    row = OwnerUser(
        owner_id=owner_id,
        email=(email or "").strip().lower(),
        password_hash=generate_password_hash(password),
        is_active=True,
    )
    db.session.add(row)
    db.session.flush()
    return row


def authenticate_owner_user(*, email: str, password: str) -> OwnerUser | None:
    row = OwnerUser.query.filter_by(email=(email or "").strip().lower(), is_active=True).first()
    if row is None or not check_password_hash(row.password_hash, password or ""):
        return None
    row.last_login_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def _overlap_days(start_a: date, end_a: date, start_b: date, end_b: date) -> int:
    start = max(start_a, start_b)
    end = min(end_a, end_b)
    if end < start:
        return 0
    return (end - start).days + 1


def _to_cents(value: Decimal) -> int:
    return int((value * Decimal("100")).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _payout_pdf_bytes(
    *, owner: PropertyOwner, period_month: str, gross: int, fee: int, expenses: int, net: int
) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4
    y = page_h - 48

    def write(text: str, step: int = 18):
        nonlocal y
        pdf.drawString(48, y, text)
        y -= step

    pdf.setTitle(f"Owner payout {owner.id} {period_month}")
    pdf.setFont("Helvetica-Bold", 16)
    write("Owner Monthly Payout")
    pdf.setFont("Helvetica", 11)
    write(f"Owner: {owner.name} ({owner.email})")
    write(f"Period: {period_month}")
    y -= 8
    write(f"Gross revenue: {gross / 100:.2f} EUR")
    write(f"Management fee: {fee / 100:.2f} EUR")
    write(f"Expenses: {expenses / 100:.2f} EUR")
    write(f"Net payout: {net / 100:.2f} EUR")
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_monthly_payout(*, owner_id: int, period_month: str) -> OwnerPayout:
    owner = PropertyOwner.query.get(owner_id)
    if owner is None:
        raise ValueError("Owner not found.")
    month_start, month_end = parse_period_month(period_month)
    assignments = (
        PropertyOwnerAssignment.query.join(
            Property, PropertyOwnerAssignment.property_id == Property.id
        )
        .filter(
            PropertyOwnerAssignment.owner_id == owner_id,
            Property.organization_id == owner.organization_id,
            PropertyOwnerAssignment.valid_from <= month_end,
            db.or_(
                PropertyOwnerAssignment.valid_to.is_(None),
                PropertyOwnerAssignment.valid_to >= month_start,
            ),
        )
        .all()
    )
    gross = Decimal("0")
    fee = Decimal("0")
    for assignment in assignments:
        reservation_rows = (
            Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
            .filter(
                Unit.property_id == assignment.property_id,
                Reservation.status == "confirmed",
                Reservation.start_date <= month_end,
                Reservation.end_date > month_start,
            )
            .all()
        )
        for row in reservation_rows:
            if row.amount is None:
                continue
            reservation_start = row.start_date
            reservation_end = row.end_date - timedelta(days=1)
            if reservation_end < reservation_start:
                continue
            assignment_end = assignment.valid_to or month_end
            overlap = _overlap_days(
                reservation_start,
                reservation_end,
                max(month_start, assignment.valid_from),
                min(month_end, assignment_end),
            )
            total_days = _overlap_days(
                reservation_start, reservation_end, reservation_start, reservation_end
            )
            if overlap <= 0 or total_days <= 0:
                continue
            prorata = Decimal(overlap) / Decimal(total_days)
            base = Decimal(row.amount) * prorata
            owner_gross = base * Decimal(assignment.ownership_pct or 0)
            owner_fee = owner_gross * Decimal(assignment.management_fee_pct or 0)
            gross += owner_gross
            fee += owner_fee

    expenses = Decimal("0")
    net = gross - fee - expenses
    payout = OwnerPayout.query.filter_by(owner_id=owner_id, period_month=period_month).first()
    if payout is None:
        payout = OwnerPayout(owner_id=owner_id, period_month=period_month)
        db.session.add(payout)
        db.session.flush()
    payout.gross_revenue_cents = _to_cents(gross)
    payout.management_fee_cents = _to_cents(fee)
    payout.expenses_cents = _to_cents(expenses)
    payout.net_payout_cents = _to_cents(net)
    payout.status = OwnerPayoutStatus.DRAFT
    pdf_bytes = _payout_pdf_bytes(
        owner=owner,
        period_month=period_month,
        gross=payout.gross_revenue_cents,
        fee=payout.management_fee_cents,
        expenses=payout.expenses_cents,
        net=payout.net_payout_cents,
    )
    out_dir = os.path.join(current_app.instance_path, "owner_payouts")
    os.makedirs(out_dir, exist_ok=True)
    filename = f"owner-{owner.id}-{period_month}.pdf"
    absolute_path = os.path.join(out_dir, filename)
    with open(absolute_path, "wb") as handle:
        handle.write(pdf_bytes)
    payout.pdf_path = f"owner_payouts/{filename}"
    audit_record(
        "payout.generated",
        status=AuditStatus.SUCCESS,
        organization_id=owner.organization_id,
        target_type="owner_payout",
        target_id=payout.id,
        context={"owner_id": owner.id, "period_month": period_month},
        commit=False,
    )
    db.session.commit()
    return payout


def send_payout_email(*, payout: OwnerPayout) -> bool:
    owner = PropertyOwner.query.get(payout.owner_id)
    if owner is None:
        return False
    ok = send_template(
        TemplateKey.ADMIN_NOTIFICATION,
        to=owner.email,
        context={
            "user_email": owner.email,
            "subject_line": f"Monthly payout {payout.period_month}",
            "message": f"Your payout PDF is ready: {payout.pdf_path}",
        },
    )
    if ok:
        payout.status = OwnerPayoutStatus.SENT
        payout.sent_at = datetime.now(timezone.utc)
        audit_record(
            "payout.sent",
            status=AuditStatus.SUCCESS,
            organization_id=owner.organization_id,
            target_type="owner_payout",
            target_id=payout.id,
            context={"owner_id": owner.id, "period_month": payout.period_month},
            commit=False,
        )
        db.session.commit()
    return ok


def mark_payout_paid(*, payout_id: int, organization_id: int) -> bool:
    payout = (
        OwnerPayout.query.join(PropertyOwner, OwnerPayout.owner_id == PropertyOwner.id)
        .filter(OwnerPayout.id == payout_id, PropertyOwner.organization_id == organization_id)
        .first()
    )
    if payout is None:
        return False
    payout.status = OwnerPayoutStatus.PAID
    payout.paid_at = datetime.now(timezone.utc)
    audit_record(
        "payout.marked_paid",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="owner_payout",
        target_id=payout.id,
        commit=False,
    )
    db.session.commit()
    return True


def monthly_owner_dashboard(*, owner_id: int, period_month: str) -> dict:
    payout = OwnerPayout.query.filter_by(owner_id=owner_id, period_month=period_month).first()
    return {
        "period_month": period_month,
        "gross_revenue_cents": payout.gross_revenue_cents if payout else 0,
        "management_fee_cents": payout.management_fee_cents if payout else 0,
        "net_payout_cents": payout.net_payout_cents if payout else 0,
    }


def payout_pdf_response(*, payout_id: int, owner_id: int) -> Response | None:
    payout = OwnerPayout.query.filter_by(id=payout_id, owner_id=owner_id).first()
    if payout is None or not payout.pdf_path:
        return None
    absolute_path = os.path.join(current_app.instance_path, payout.pdf_path)
    if not os.path.isfile(absolute_path):
        return None
    with open(absolute_path, "rb") as handle:
        body = handle.read()
    response = Response(body, mimetype="application/pdf")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="{os.path.basename(absolute_path)}"'
    )
    response.headers["Content-Length"] = str(len(body))
    response.headers["Cache-Control"] = "no-store"
    return response
