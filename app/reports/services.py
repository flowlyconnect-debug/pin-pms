from __future__ import annotations

from datetime import date

from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def occupancy_report(*, organization_id: int, start_date: date, end_date: date) -> dict:
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )

    reserved_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .join(Reservation, Reservation.unit_id == Unit.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date < end_date,
            Reservation.end_date > start_date,
        )
        .distinct(Unit.id)
        .count()
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
