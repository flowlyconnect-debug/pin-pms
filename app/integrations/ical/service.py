from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import datetime, timezone

from flask import current_app
from icalendar import Calendar, Event

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.core.telemetry import traced
from app.extensions import db
from app.integrations.ical import adapter
from app.integrations.ical.client import IcalClient
from app.integrations.ical.models import ImportedCalendarEvent, ImportedCalendarFeed
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


@dataclass
class IcalServiceError(Exception):
    code: str
    message: str
    status: int


class IcalService:
    def __init__(self, client: IcalClient | None = None):
        self.client = client or IcalClient.from_config()

    def sign_unit_token(self, *, unit_id: int) -> str:
        secret = (current_app.config.get("ICAL_FEED_SECRET") or "").encode("utf-8")
        if not secret:
            raise IcalServiceError("config_error", "iCal feed secret is not configured.", 500)
        digest = hmac.new(secret, str(unit_id).encode("utf-8"), hashlib.sha256).hexdigest()
        return digest

    def verify_unit_token(self, *, unit_id: int, token: str) -> bool:
        if not token:
            return False
        expected = self.sign_unit_token(unit_id=unit_id)
        return hmac.compare_digest(expected, token.strip())

    def export_unit_calendar(self, *, unit_id: int) -> str:
        unit = Unit.query.get(unit_id)
        if unit is None:
            raise IcalServiceError("not_found", "Unit not found.", 404)
        events = (
            Reservation.query.filter(
                Reservation.unit_id == unit_id,
                Reservation.status != "cancelled",
            )
            .order_by(Reservation.start_date.asc(), Reservation.id.asc())
            .all()
        )
        cal = Calendar()
        cal.add("prodid", "-//Pin PMS//iCal Feed//EN")
        cal.add("version", "2.0")
        for row in events:
            item = Event()
            item.add("uid", f"reservation-{row.id}@pindora")
            item.add("summary", f"Reserved: {unit.name}")
            item.add("dtstart", row.start_date)
            item.add("dtend", row.end_date)
            item.add("dtstamp", datetime.now(timezone.utc))
            cal.add_component(item)
        return cal.to_ical().decode("utf-8")

    def list_unit_feeds(self, *, organization_id: int, unit_id: int) -> list[ImportedCalendarFeed]:
        return (
            ImportedCalendarFeed.query.filter_by(
                organization_id=organization_id,
                unit_id=unit_id,
            )
            .order_by(ImportedCalendarFeed.id.asc())
            .all()
        )

    def create_feed(
        self, *, organization_id: int, unit_id: int, source_url: str, name: str | None
    ) -> ImportedCalendarFeed:
        unit = (
            Unit.query.join(Property, Unit.property_id == Property.id)
            .filter(Unit.id == unit_id, Property.organization_id == organization_id)
            .first()
        )
        if unit is None:
            raise IcalServiceError("not_found", "Unit not found.", 404)
        row = ImportedCalendarFeed(
            organization_id=organization_id,
            unit_id=unit_id,
            source_url=source_url.strip(),
            name=(name or "").strip() or None,
            is_active=True,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def detect_conflicts(self, *, organization_id: int, unit_id: int | None = None) -> list[dict]:
        imported_query = ImportedCalendarEvent.query.filter_by(organization_id=organization_id)
        if unit_id is not None:
            imported_query = imported_query.filter_by(unit_id=unit_id)
        imported_rows = imported_query.order_by(ImportedCalendarEvent.start_date.asc()).all()
        out: list[dict] = []
        for ext in imported_rows:
            internal_rows = (
                Reservation.query.filter(
                    Reservation.unit_id == ext.unit_id,
                    Reservation.status != "cancelled",
                    Reservation.start_date < ext.end_date,
                    Reservation.end_date > ext.start_date,
                )
                .order_by(Reservation.start_date.asc())
                .all()
            )
            for res in internal_rows:
                out.append(
                    {
                        "reservation_id": res.id,
                        "unit_id": res.unit_id,
                        "reservation_start": res.start_date.isoformat(),
                        "reservation_end": res.end_date.isoformat(),
                        "external_uid": ext.external_uid,
                        "external_summary": ext.summary or "",
                        "external_start": ext.start_date.isoformat(),
                        "external_end": ext.end_date.isoformat(),
                    }
                )
        return out

    @traced("ical.sync_all_feeds")
    def sync_all_feeds(self, *, organization_id: int | None = None) -> int:
        query = ImportedCalendarFeed.query.filter_by(is_active=True)
        if organization_id is not None:
            query = query.filter_by(organization_id=organization_id)
        feeds = query.order_by(ImportedCalendarFeed.id.asc()).all()
        imported_count = 0
        for feed in feeds:
            try:
                payload = self.client.fetch_calendar(source_url=feed.source_url)
                parsed = adapter.parse_ical_events(payload)
                ImportedCalendarEvent.query.filter_by(feed_id=feed.id).delete()
                for item in parsed:
                    db.session.add(
                        ImportedCalendarEvent(
                            organization_id=feed.organization_id,
                            unit_id=feed.unit_id,
                            feed_id=feed.id,
                            external_uid=item["uid"],
                            summary=item["summary"],
                            start_date=item["start_date"],
                            end_date=item["end_date"],
                        )
                    )
                feed.last_error = None
                feed.last_synced_at = datetime.now(timezone.utc)
                db.session.commit()
                imported_count += len(parsed)
                conflicts = self.detect_conflicts(
                    organization_id=feed.organization_id,
                    unit_id=feed.unit_id,
                )
                audit_record(
                    "calendar.imported",
                    status=AuditStatus.SUCCESS,
                    organization_id=feed.organization_id,
                    target_type="unit",
                    target_id=feed.unit_id,
                    context={"feed_id": feed.id, "imported_count": len(parsed)},
                    commit=True,
                )
                if conflicts:
                    audit_record(
                        "calendar.conflict_detected",
                        status=AuditStatus.SUCCESS,
                        organization_id=feed.organization_id,
                        target_type="unit",
                        target_id=feed.unit_id,
                        context={"feed_id": feed.id, "conflict_count": len(conflicts)},
                        commit=True,
                    )
            except Exception as exc:  # noqa: BLE001
                db.session.rollback()
                feed.last_error = str(exc)[:512]
                feed.last_synced_at = datetime.now(timezone.utc)
                db.session.commit()
        return imported_count
