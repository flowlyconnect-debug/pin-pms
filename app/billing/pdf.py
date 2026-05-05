"""On-the-fly invoice / receipt PDF generation (ReportLab, in-memory only)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from typing import Any, Mapping
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.billing.models import Invoice
from app.billing.services import InvoiceServiceError
from app.settings import services as settings_services


def _p(text: str) -> str:
    return escape(text or "", {"\n": "<br/>"})


def _money(value: Any) -> str:
    if value is None:
        return "0.00"
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return "0.00"
    return format(d, "f")


def _invoice_lines(invoice: Invoice) -> list[tuple[str, str, str, str, str]]:
    """Return table rows: description, qty, unit excl VAT, VAT %, line total excl VAT."""

    meta = invoice.metadata_json
    raw_lines: list[Any] | None = None
    if isinstance(meta, dict):
        raw_lines = meta.get("lines") or meta.get("line_items")
    if isinstance(raw_lines, list) and raw_lines:
        rows: list[tuple[str, str, str, str, str]] = []
        for item in raw_lines:
            if not isinstance(item, Mapping):
                continue
            desc = str(item.get("description") or item.get("name") or "").strip() or "—"
            qty_raw = item.get("quantity", item.get("qty", 1))
            try:
                qty_dec = Decimal(str(qty_raw)).quantize(Decimal("0.01"))
            except Exception:
                qty_dec = Decimal("1.00")
            unit_raw = item.get("unit_price_excl_vat", item.get("unit_price", item.get("price")))
            try:
                unit_dec = Decimal(str(unit_raw)).quantize(Decimal("0.01"))
            except Exception:
                unit_dec = Decimal("0.00")
            rate_raw = item.get("vat_rate", invoice.vat_rate)
            try:
                rate_dec = Decimal(str(rate_raw)).quantize(Decimal("0.01"))
            except Exception:
                rate_dec = Decimal(str(invoice.vat_rate)).quantize(Decimal("0.01"))
            line_total = item.get("line_total_excl_vat")
            if line_total is not None:
                try:
                    lt = Decimal(str(line_total)).quantize(Decimal("0.01"))
                except Exception:
                    lt = (qty_dec * unit_dec).quantize(Decimal("0.01"))
            else:
                lt = (qty_dec * unit_dec).quantize(Decimal("0.01"))
            rows.append(
                (
                    desc,
                    _money(qty_dec),
                    _money(unit_dec),
                    _money(rate_dec),
                    _money(lt),
                )
            )
        if rows:
            return rows

    desc = (invoice.description or "").strip() or "Palvelu / majoitus"
    sub = invoice.subtotal_excl_vat
    rate = invoice.vat_rate
    return [
        (
            desc,
            "1.00",
            _money(sub),
            _money(rate),
            _money(sub),
        )
    ]


def _billing_settings() -> dict[str, str]:
    """Read optional billing / company display keys via the settings service."""

    def s(key: str, default: str = "") -> str:
        val = settings_services.get(key, default)
        if val is None:
            return default
        if isinstance(val, Decimal):
            return format(val.quantize(Decimal("0.01")), "f")
        return str(val).strip()

    return {
        "company_name": s("company_name", ""),
        "company_address": s("billing.company_address", ""),
        "business_id": s("billing.business_id", ""),
        "company_email": s("billing.company_email", ""),
        "company_phone": s("billing.company_phone", ""),
        "iban": s("billing.iban", ""),
        "payment_reference": s("billing.payment_reference", ""),
        "vat_id": s("billing.vat_id", ""),
    }


def generate_invoice_pdf(invoice_id: int) -> bytes:
    """Build a PDF for ``invoice_id`` in memory and return raw bytes.

    Raises:
        InvoiceServiceError: ``not_found`` / 404 when the invoice does not exist.

    Callers must enforce tenant isolation before invoking this function.
    """

    invoice = Invoice.query.get(invoice_id)
    if invoice is None:
        raise InvoiceServiceError(
            code="not_found",
            message="Invoice not found.",
            status=404,
        )

    organization = invoice.organization
    reservation = invoice.reservation
    guest = invoice.guest
    if guest is None and reservation is not None:
        guest = reservation.guest

    property_name: str | None = None
    property_address: str | None = None
    if reservation is not None and reservation.unit is not None:
        prop = reservation.unit.property
        if prop is not None:
            property_name = prop.name
            property_address = prop.address

    settings = _billing_settings()
    display_name = settings["company_name"] or (organization.name if organization else "")

    title = "KUITTI" if (invoice.status or "").lower() == "paid" else "LASKU"

    invoice_date: date
    if invoice.created_at is not None:
        invoice_date = invoice.created_at.date()
    else:
        invoice_date = date.today()

    doc_label = (invoice.invoice_number or f"INV-{invoice.id}").strip()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvTitle",
        parent=styles["Title"],
        spaceAfter=12,
    )
    small = ParagraphStyle("InvSmall", parent=styles["Normal"], fontSize=9, leading=11)

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        pageCompression=0,
    )
    story: list[Any] = []

    # Organization header
    header_lines = [f"<b>{_p(display_name)}</b>"]
    addr = settings["company_address"]
    if not addr and property_address:
        addr = property_address
    if addr:
        header_lines.append(_p(addr))
    if settings["business_id"]:
        header_lines.append(f"Y-tunnus: {_p(settings['business_id'])}")
    if settings["company_email"]:
        header_lines.append(_p(settings["company_email"]))
    if settings["company_phone"]:
        header_lines.append(_p(settings["company_phone"]))
    for line in header_lines:
        story.append(Paragraph(line, small))
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph(_p(title), title_style))

    story.append(Paragraph(f"<b>Laskun numero:</b> {_p(doc_label)}", styles["Normal"]))
    story.append(Paragraph(f"<b>Laskun päiväys:</b> {_p(invoice_date.isoformat())}", styles["Normal"]))
    story.append(Paragraph(f"<b>Eräpäivä:</b> {_p(invoice.due_date.isoformat())}", styles["Normal"]))
    story.append(Spacer(1, 0.3 * cm))

    story.append(Paragraph("<b>Asiakas</b>", styles["Heading4"]))
    if guest is not None:
        story.append(Paragraph(_p(guest.full_name), styles["Normal"]))
        if guest.email:
            story.append(Paragraph(_p(guest.email), styles["Normal"]))
        if guest.phone:
            story.append(Paragraph(_p(guest.phone), styles["Normal"]))
    else:
        story.append(Paragraph("—", styles["Normal"]))

    if property_name:
        story.append(Spacer(1, 0.15 * cm))
        story.append(Paragraph(f"<b>Kohde:</b> {_p(property_name)}", small))

    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("<b>Laskurivit</b>", styles["Heading4"]))

    line_rows = [["Kuvaus", "Määrä", "À-hinta (veroton)", "ALV-%", "Summa (veroton)"]]
    line_rows.extend(_invoice_lines(invoice))

    table = Table(line_rows, colWidths=[6.5 * cm, 2 * cm, 2.5 * cm, 2 * cm, 2.5 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.4 * cm))

    cur = (invoice.currency or "EUR").strip()
    story.append(Paragraph("<b>Yhteenveto</b>", styles["Heading4"]))
    story.append(
        Paragraph(
            f"Veroton yhteensä: {_money(invoice.subtotal_excl_vat)} {_p(cur)}",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"ALV: {_money(invoice.vat_amount)} {_p(cur)}",
            styles["Normal"],
        )
    )
    story.append(
        Paragraph(
            f"Yhteensä (sis. ALV): {_money(invoice.total_incl_vat)} {_p(cur)}",
            styles["Normal"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))

    story.append(Paragraph("<b>Maksuohjeet</b>", styles["Heading4"]))
    iban = settings["iban"]
    story.append(Paragraph(f"IBAN: {_p(iban) if iban else '—'}", styles["Normal"]))
    ref = settings["payment_reference"] or doc_label
    story.append(Paragraph(f"Viite: {_p(ref)}", styles["Normal"]))
    story.append(Spacer(1, 0.6 * cm))

    footer_bits = []
    if settings["business_id"]:
        footer_bits.append(f"Y-tunnus: {settings['business_id']}")
    if settings["vat_id"]:
        footer_bits.append(f"ALV-tunnus: {settings['vat_id']}")
    if footer_bits:
        story.append(Paragraph(_p(" · ".join(footer_bits)), small))

    doc.build(story)
    return buffer.getvalue()


__all__ = ["generate_invoice_pdf"]
