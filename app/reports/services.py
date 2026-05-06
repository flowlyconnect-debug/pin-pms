from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func

from app.billing.models import Invoice
from app.expenses.models import Expense
from app.extensions import db
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def occupancy_report(*, organization_id: int, start_date: date, end_date: date) -> dict:
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )

    reserved_units = (
        db.session.query(func.count(func.distinct(Unit.id)))
        .select_from(Unit)
        .join(Property, Unit.property_id == Property.id)
        .join(Reservation, Reservation.unit_id == Unit.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date < end_date,
            Reservation.end_date > start_date,
        )
        .scalar()
        or 0
    )

    occupancy_percentage = 0.0
    if total_units > 0:
        occupancy_percentage = round((reserved_units / total_units) * 100, 2)

    return {
        "total_units": total_units,
        "reserved_units": reserved_units,
        "occupancy_percentage": occupancy_percentage,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


def reservation_report(*, organization_id: int) -> dict:
    scoped = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )

    total_reservations = scoped.count()
    confirmed_reservations = scoped.filter(Reservation.status == "confirmed").count()
    cancelled_reservations = scoped.filter(Reservation.status == "cancelled").count()

    return {
        "total_reservations": total_reservations,
        "confirmed_reservations": confirmed_reservations,
        "cancelled_reservations": cancelled_reservations,
    }


def _month_iter(start_date: date, end_date: date) -> list[date]:
    cursor = date(start_date.year, start_date.month, 1)
    end_month = date(end_date.year, end_date.month, 1)
    months: list[date] = []
    while cursor <= end_month:
        months.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _invoice_property_id(invoice: Invoice) -> int | None:
    if invoice.lease and invoice.lease.unit:
        return invoice.lease.unit.property_id
    if invoice.reservation and invoice.reservation.unit:
        return invoice.reservation.unit.property_id
    return None


def _invoice_income_type(invoice: Invoice) -> str:
    meta = invoice.metadata_json if isinstance(invoice.metadata_json, dict) else {}
    kind = str(meta.get("invoice_kind") or "").strip().lower()
    if kind in {"rent", "service", "deposit"}:
        return kind
    desc = (invoice.description or "").lower()
    if "deposit" in desc or "vakuus" in desc:
        return "deposit"
    if "service" in desc or "palvelu" in desc:
        return "service"
    return "rent"


def cash_flow_report(
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    property_id: int | None = None,
    group_by: str = "month",
) -> dict:
    if group_by != "month":
        raise ValueError("Only month grouping is supported.")

    invoice_rows = (
        Invoice.query.filter(
            Invoice.organization_id == organization_id,
            Invoice.status != "cancelled",
            Invoice.paid_at.isnot(None),
            func.date(Invoice.paid_at) >= start_date,
            func.date(Invoice.paid_at) <= end_date,
        )
        .order_by(Invoice.paid_at.asc(), Invoice.id.asc())
        .all()
    )
    expense_rows = (
        Expense.query.filter(
            Expense.organization_id == organization_id,
            Expense.date >= start_date,
            Expense.date <= end_date,
        )
        .order_by(Expense.date.asc(), Expense.id.asc())
        .all()
    )
    if property_id is not None:
        invoice_rows = [row for row in invoice_rows if _invoice_property_id(row) == property_id]
        expense_rows = [row for row in expense_rows if row.property_id == property_id]

    bucket_map: dict[str, dict] = {}
    for month_start in _month_iter(start_date, end_date):
        key = f"{month_start.year:04d}-{month_start.month:02d}"
        bucket_map[key] = {
            "label": key,
            "income": Decimal("0.00"),
            "expenses": Decimal("0.00"),
            "net": Decimal("0.00"),
        }

    for inv in invoice_rows:
        paid_date = inv.paid_at.date()
        key = f"{paid_date.year:04d}-{paid_date.month:02d}"
        if key in bucket_map:
            bucket_map[key]["income"] += Decimal(inv.total_incl_vat or 0)
    for expense in expense_rows:
        key = f"{expense.date.year:04d}-{expense.date.month:02d}"
        if key in bucket_map:
            bucket_map[key]["expenses"] += Decimal(expense.amount or 0)

    for row in bucket_map.values():
        row["income"] = row["income"].quantize(Decimal("0.01"))
        row["expenses"] = row["expenses"].quantize(Decimal("0.01"))
        row["net"] = (row["income"] - row["expenses"]).quantize(Decimal("0.01"))

    groups = [bucket_map[key] for key in sorted(bucket_map.keys())]
    totals_income = sum((row["income"] for row in groups), Decimal("0.00")).quantize(Decimal("0.01"))
    totals_expenses = sum((row["expenses"] for row in groups), Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    totals_net = (totals_income - totals_expenses).quantize(Decimal("0.01"))
    return {
        "groups": groups,
        "totals": {"income": totals_income, "expenses": totals_expenses, "net": totals_net},
    }


def income_breakdown_report(
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    property_id: int | None = None,
) -> dict:
    rows = (
        Invoice.query.filter(
            Invoice.organization_id == organization_id,
            Invoice.status != "cancelled",
            Invoice.paid_at.isnot(None),
            func.date(Invoice.paid_at) >= start_date,
            func.date(Invoice.paid_at) <= end_date,
        )
        .order_by(Invoice.paid_at.asc(), Invoice.id.asc())
        .all()
    )
    if property_id is not None:
        rows = [row for row in rows if _invoice_property_id(row) == property_id]

    totals = {"rent": Decimal("0.00"), "service": Decimal("0.00"), "deposit": Decimal("0.00")}
    for row in rows:
        kind = _invoice_income_type(row)
        totals[kind] += Decimal(row.total_incl_vat or 0)
    for key in totals:
        totals[key] = totals[key].quantize(Decimal("0.01"))
    total = sum(totals.values(), Decimal("0.00")).quantize(Decimal("0.01"))
    return {"groups": [{"label": k, "amount": v} for k, v in totals.items()], "total": total}


def expenses_breakdown_report(
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    property_id: int | None = None,
) -> dict:
    query = Expense.query.filter(
        Expense.organization_id == organization_id,
        Expense.date >= start_date,
        Expense.date <= end_date,
    )
    if property_id is not None:
        query = query.filter(Expense.property_id == property_id)
    rows = query.all()
    totals: dict[str, Decimal] = {}
    for row in rows:
        cat = (row.category or "other").strip().lower() or "other"
        totals[cat] = totals.get(cat, Decimal("0.00")) + Decimal(row.amount or 0)
    groups = [{"label": key, "amount": value.quantize(Decimal("0.01"))} for key, value in sorted(totals.items())]
    total_amount = sum((row["amount"] for row in groups), Decimal("0.00")).quantize(Decimal("0.01"))
    return {"groups": groups, "total": total_amount}
