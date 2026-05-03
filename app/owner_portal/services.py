from __future__ import annotations

from app.owners.models import OwnerUser, PropertyOwnerAssignment
from app.owners.services import monthly_owner_dashboard
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def owner_user_from_session(*, user_id: int | None) -> OwnerUser | None:
    if user_id is None:
        return None
    return OwnerUser.query.filter_by(id=user_id, is_active=True).first()


def owner_dashboard_page(*, owner_user: OwnerUser, period: str) -> dict:
    stats = monthly_owner_dashboard(owner_id=owner_user.owner_id, period_month=period)
    assignment_rows = (
        PropertyOwnerAssignment.query.join(
            Property, PropertyOwnerAssignment.property_id == Property.id
        )
        .filter(PropertyOwnerAssignment.owner_id == owner_user.owner_id)
        .order_by(Property.name.asc())
        .all()
    )
    properties = [Property.query.get(a.property_id) for a in assignment_rows]
    return {
        "stats": stats,
        "properties": [p for p in properties if p is not None],
    }


def list_owner_property_reservations(*, owner_id: int, property_id: int) -> list[Reservation]:
    assignment = PropertyOwnerAssignment.query.filter_by(
        owner_id=owner_id, property_id=property_id
    ).first()
    if assignment is None:
        raise ValueError("assignment_not_found")
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .filter(Unit.property_id == property_id)
        .order_by(Reservation.start_date.asc(), Reservation.id.asc())
        .all()
    )
