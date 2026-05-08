from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.expenses.models import Expense
from app.extensions import db
from app.properties.models import Property

ALLOWED_CATEGORIES = (
    "cleaning",
    "maintenance",
    "utilities",
    "insurance",
    "taxes",
    "marketing",
    "other",
)


@dataclass
class ExpenseServiceError(Exception):
    code: str
    message: str
    status: int


def _parse_amount(raw: Any, field_name: str) -> Decimal:
    text = str(raw or "").strip()
    if not text:
        raise ExpenseServiceError("validation_error", f"{field_name} is required.", 400)
    try:
        value = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ExpenseServiceError(
            "validation_error", f"{field_name} must be decimal.", 400
        ) from None
    if value < Decimal("0.00"):
        raise ExpenseServiceError("validation_error", f"{field_name} must be >= 0.", 400)
    return value


def _parse_date(raw: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError:
        raise ExpenseServiceError("validation_error", "date must be YYYY-MM-DD.", 400) from None


def _ensure_property_in_org(*, organization_id: int, property_id: int | None) -> None:
    if property_id is None:
        return
    row = Property.query.filter_by(id=property_id, organization_id=organization_id).first()
    if row is None:
        raise ExpenseServiceError("validation_error", "Property not found in organization.", 400)


def list_expenses(*, organization_id: int, property_id: int | None = None) -> list[Expense]:
    query = Expense.query.filter(Expense.organization_id == organization_id)
    if property_id is not None:
        query = query.filter(Expense.property_id == property_id)
    return query.order_by(Expense.date.desc(), Expense.id.desc()).all()


def create_expense(
    *,
    organization_id: int,
    property_id: int | None,
    category: str,
    amount_raw: Any,
    vat_raw: Any,
    date_raw: str,
    description: str | None,
    payee: str | None,
    actor_user_id: int | None = None,
) -> Expense:
    normalized_category = (category or "").strip().lower()
    if normalized_category not in ALLOWED_CATEGORIES:
        raise ExpenseServiceError("validation_error", "Invalid category.", 400)

    _ensure_property_in_org(organization_id=organization_id, property_id=property_id)
    amount = _parse_amount(amount_raw, "amount")
    vat = _parse_amount(vat_raw or "0", "vat")
    expense_date = _parse_date(date_raw)

    row = Expense(
        organization_id=organization_id,
        property_id=property_id,
        category=normalized_category,
        amount=amount,
        vat=vat,
        date=expense_date,
        description=(description or "").strip() or None,
        payee=(payee or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "expense.created",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="expense",
        target_id=row.id,
        actor_id=actor_user_id,
        metadata={
            "category": normalized_category,
            "amount": str(amount),
            "vat": str(vat),
            "property_id": property_id,
        },
        commit=False,
    )
    db.session.commit()
    return row
