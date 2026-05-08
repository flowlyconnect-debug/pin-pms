from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.billing.models import Invoice, Lease
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


def compute_aging_receivables(*, organization_id: int, as_of: date) -> dict[str, Decimal]:
    rows = (
        Invoice.query.filter(
            Invoice.organization_id == organization_id,
            Invoice.status.in_(("open", "overdue")),
            Invoice.due_date.isnot(None),
            Invoice.due_date < as_of,
        )
        .with_entities(Invoice.due_date, Invoice.total_incl_vat)
        .all()
    )
    buckets = {
        "0_30": Decimal("0.00"),
        "31_60": Decimal("0.00"),
        "61_90": Decimal("0.00"),
        "90_plus": Decimal("0.00"),
    }
    for row in rows:
        overdue_days = (as_of - row.due_date).days
        amount = Decimal(row.total_incl_vat or 0)
        if overdue_days <= 30:
            buckets["0_30"] += amount
        elif overdue_days <= 60:
            buckets["31_60"] += amount
        elif overdue_days <= 90:
            buckets["61_90"] += amount
        else:
            buckets["90_plus"] += amount
    for key in buckets:
        buckets[key] = buckets[key].quantize(Decimal("0.01"))
    return buckets


def _count_monthly_occurrences(*, lease_start: date, window_start: date, window_end: date) -> int:
    cursor_month = date(window_start.year, window_start.month, 1)
    month_end = date(window_end.year, window_end.month, 1)
    day = lease_start.day
    count = 0
    while cursor_month <= month_end:
        if cursor_month.month == 12:
            next_month = date(cursor_month.year + 1, 1, 1)
        else:
            next_month = date(cursor_month.year, cursor_month.month + 1, 1)
        last_day = (next_month - timedelta(days=1)).day
        due_day = min(day, last_day)
        due_date = date(cursor_month.year, cursor_month.month, due_day)
        if window_start <= due_date <= window_end and due_date >= lease_start:
            count += 1
        cursor_month = next_month
    return count


def _lease_forecast_amount(*, lease: Lease, window_start: date, window_end: date) -> Decimal:
    if lease.status != "active":
        return Decimal("0.00")
    lease_start = lease.start_date
    lease_end = lease.end_date or window_end
    if lease_end < window_start or lease_start > window_end:
        return Decimal("0.00")
    cycle = (lease.billing_cycle or "monthly").strip().lower()
    rent = Decimal(lease.rent_amount or 0)
    if cycle == "one_time":
        if window_start <= lease_start <= window_end:
            return rent.quantize(Decimal("0.01"))
        return Decimal("0.00")
    if cycle == "weekly":
        start_anchor = max(lease_start, window_start)
        offset = (start_anchor - lease_start).days % 7
        first_due = start_anchor if offset == 0 else start_anchor + timedelta(days=(7 - offset))
        effective_end = min(lease_end, window_end)
        if first_due > effective_end:
            return Decimal("0.00")
        occurrences = ((effective_end - first_due).days // 7) + 1
        return (rent * occurrences).quantize(Decimal("0.01"))
    effective_start = max(lease_start, window_start)
    effective_end = min(lease_end, window_end)
    if effective_start > effective_end:
        return Decimal("0.00")
    occurrences = _count_monthly_occurrences(
        lease_start=lease_start,
        window_start=effective_start,
        window_end=effective_end,
    )
    return (rent * occurrences).quantize(Decimal("0.01"))


def compute_forecasted_cash_flow(*, organization_id: int, days_ahead: int) -> Decimal:
    today = date.today()
    horizon = today + timedelta(days=max(0, int(days_ahead)))
    active_leases = (
        Lease.query.filter(
            Lease.organization_id == organization_id,
            Lease.status == "active",
            Lease.start_date <= horizon,
        )
        .all()
    )
    lease_total = sum(
        (
            _lease_forecast_amount(lease=lease, window_start=today, window_end=horizon)
            for lease in active_leases
        ),
        Decimal("0.00"),
    )
    reservations_total = (
        db.session.query(func.coalesce(func.sum(Reservation.amount), 0))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.amount.isnot(None),
            Reservation.start_date >= today,
            Reservation.start_date <= horizon,
        )
        .scalar()
    )
    return (lease_total + Decimal(reservations_total or 0)).quantize(Decimal("0.01"))


def compute_cash_flow_breakdown(*, start: date, end: date, organization_id: int) -> dict:
    from app.payments.models import Payment

    lease_unit = aliased(Unit)
    lease_property = aliased(Property)
    res_unit = aliased(Unit)
    res_property = aliased(Property)
    invoices = (
        db.session.query(
            Invoice.id.label("invoice_id"),
            func.coalesce(lease_property.id, res_property.id).label("property_id"),
            func.coalesce(lease_property.name, res_property.name, "Tuntematon").label("property_name"),
            func.coalesce(lease_unit.id, res_unit.id).label("unit_id"),
            func.coalesce(lease_unit.name, res_unit.name, "-").label("unit_name"),
            Invoice.total_incl_vat.label("amount"),
        )
        .select_from(Invoice)
        .outerjoin(Lease, Invoice.lease_id == Lease.id)
        .outerjoin(lease_unit, Lease.unit_id == lease_unit.id)
        .outerjoin(lease_property, lease_unit.property_id == lease_property.id)
        .outerjoin(Reservation, Invoice.reservation_id == Reservation.id)
        .outerjoin(res_unit, Reservation.unit_id == res_unit.id)
        .outerjoin(res_property, res_unit.property_id == res_property.id)
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.status != "cancelled",
            Invoice.paid_at.isnot(None),
            func.date(Invoice.paid_at) >= start,
            func.date(Invoice.paid_at) <= end,
        )
        .all()
    )
    invoice_ids = [row.invoice_id for row in invoices]
    payment_rows = []
    if invoice_ids:
        payment_rows = (
            Payment.query.with_entities(Payment.invoice_id, Payment.provider)
            .filter(
                Payment.organization_id == organization_id,
                Payment.status == "succeeded",
                Payment.invoice_id.in_(invoice_ids),
            )
            .all()
        )
    providers_by_invoice: dict[int, str] = {}
    for row in payment_rows:
        if row.invoice_id is None or row.invoice_id in providers_by_invoice:
            continue
        providers_by_invoice[row.invoice_id] = (row.provider or "").strip().lower()

    income_by_property: dict[tuple[int | None, str], Decimal] = {}
    income_by_unit: dict[tuple[int | None, int | None, str, str], Decimal] = {}
    income_by_payment_method = {
        "Stripe": Decimal("0.00"),
        "Paytrail": Decimal("0.00"),
        "Manuaalinen": Decimal("0.00"),
    }
    for row in invoices:
        amount = Decimal(row.amount or 0)
        property_key = (row.property_id, row.property_name)
        unit_key = (row.unit_id, row.property_id, row.property_name, row.unit_name)
        income_by_property[property_key] = income_by_property.get(property_key, Decimal("0.00")) + amount
        income_by_unit[unit_key] = income_by_unit.get(unit_key, Decimal("0.00")) + amount
        provider = providers_by_invoice.get(row.invoice_id)
        if provider == "stripe":
            label = "Stripe"
        elif provider == "paytrail":
            label = "Paytrail"
        else:
            label = "Manuaalinen"
        income_by_payment_method[label] += amount

    def _q(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"))

    return {
        "income_by_property": [
            {"property_id": key[0], "property": key[1], "amount": _q(value)}
            for key, value in sorted(income_by_property.items(), key=lambda item: item[0][1].lower())
        ],
        "income_by_unit": [
            {
                "unit_id": key[0],
                "property_id": key[1],
                "property": key[2],
                "unit": key[3],
                "amount": _q(value),
            }
            for key, value in sorted(
                income_by_unit.items(),
                key=lambda item: (item[0][2].lower(), item[0][3].lower()),
            )
        ],
        "income_by_payment_method": [
            {"payment_method": label, "amount": _q(value)}
            for label, value in income_by_payment_method.items()
        ],
        "aging_receivables": compute_aging_receivables(organization_id=organization_id, as_of=end),
        "forecast": {
            "30": compute_forecasted_cash_flow(organization_id=organization_id, days_ahead=30),
            "60": compute_forecasted_cash_flow(organization_id=organization_id, days_ahead=60),
            "90": compute_forecasted_cash_flow(organization_id=organization_id, days_ahead=90),
        },
    }


def compute_profitability_by_property(*, start: date, end: date, organization_id: int) -> list[dict]:
    lease_unit = aliased(Unit)
    lease_property = aliased(Property)
    res_unit = aliased(Unit)
    res_property = aliased(Property)
    income_rows = (
        db.session.query(
            func.coalesce(lease_property.id, res_property.id, 0).label("property_id"),
            func.coalesce(lease_property.name, res_property.name, "Tuntematon").label("property_name"),
            func.coalesce(func.sum(Invoice.total_incl_vat), 0).label("income"),
        )
        .select_from(Invoice)
        .outerjoin(Lease, Invoice.lease_id == Lease.id)
        .outerjoin(lease_unit, Lease.unit_id == lease_unit.id)
        .outerjoin(lease_property, lease_unit.property_id == lease_property.id)
        .outerjoin(Reservation, Invoice.reservation_id == Reservation.id)
        .outerjoin(res_unit, Reservation.unit_id == res_unit.id)
        .outerjoin(res_property, res_unit.property_id == res_property.id)
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.status != "cancelled",
            Invoice.paid_at.isnot(None),
            func.date(Invoice.paid_at) >= start,
            func.date(Invoice.paid_at) <= end,
        )
        .group_by(lease_property.id, lease_property.name, res_property.id, res_property.name)
        .all()
    )
    expense_rows = (
        db.session.query(
            Expense.property_id.label("property_id"),
            func.coalesce(func.sum(Expense.amount), 0).label("expense"),
        )
        .select_from(Expense)
        .filter(
            Expense.organization_id == organization_id,
            Expense.date >= start,
            Expense.date <= end,
            Expense.property_id.isnot(None),
        )
        .group_by(Expense.property_id)
        .all()
    )
    total_units_rows = (
        db.session.query(Property.id, func.count(Unit.id))
        .select_from(Property)
        .join(Unit, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .group_by(Property.id)
        .all()
    )
    reserved_units_rows = (
        db.session.query(Property.id, func.count(func.distinct(Unit.id)))
        .select_from(Property)
        .join(Unit, Unit.property_id == Property.id)
        .join(Reservation, Reservation.unit_id == Unit.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date < end,
            Reservation.end_date > start,
        )
        .group_by(Property.id)
        .all()
    )
    property_names = {
        row.id: row.name
        for row in Property.query.with_entities(Property.id, Property.name).filter(
            Property.organization_id == organization_id
        )
    }
    income_map = {int(row.property_id): Decimal(row.income or 0) for row in income_rows if row.property_id}
    expense_map = {int(row.property_id): Decimal(row.expense or 0) for row in expense_rows if row.property_id}
    total_units_map = {int(prop_id): int(cnt or 0) for prop_id, cnt in total_units_rows}
    reserved_units_map = {int(prop_id): int(cnt or 0) for prop_id, cnt in reserved_units_rows}
    property_ids = sorted(set(income_map) | set(expense_map))
    output: list[dict] = []
    for property_id in property_ids:
        income = income_map.get(property_id, Decimal("0.00")).quantize(Decimal("0.01"))
        expenses = expense_map.get(property_id, Decimal("0.00")).quantize(Decimal("0.01"))
        total_units = total_units_map.get(property_id, 0)
        reserved_units = reserved_units_map.get(property_id, 0)
        occupancy_rate = round((reserved_units / total_units) * 100, 2) if total_units else 0.0
        output.append(
            {
                "property_id": property_id,
                "property": property_names.get(property_id, f"Kohde #{property_id}"),
                "income": income,
                "expenses": expenses,
                "net": (income - expenses).quantize(Decimal("0.01")),
                "occupancy_rate": occupancy_rate,
            }
        )
    return output
