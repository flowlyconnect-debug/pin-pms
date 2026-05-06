from __future__ import annotations

from datetime import date
from functools import wraps

from flask import abort, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from app.extensions import limiter
from app.payments.models import Payment
from app.portal import portal_bp
from app.portal import services as portal_service
from app.payments import services as payment_service


def _login_rate_limit():
    return current_app.config["LOGIN_RATE_LIMIT"]


def _current_portal_user():
    user_id = session.get("portal_user_id")
    return portal_service.get_portal_user_or_none(user_id=user_id)


def _payment_error_message_for_portal(code: str) -> str:
    return {
        "provider_disabled": "Maksuyhteys on tilapäisesti pois käytöstä, yritä uudelleen myöhemmin",
        "validation_error": "Tarkista syöttämäsi tiedot",
        "forbidden": "Et voi maksaa tätä laskua",
    }.get(code, "Maksun aloitus epäonnistui, yritä uudelleen")


def require_portal_login(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = _current_portal_user()
        if user is None:
            return redirect(url_for("portal.login"))
        return view_func(user, *args, **kwargs)

    return wrapped


@portal_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Liian monta kirjautumisyritystä. Odota hetki ja yritä uudelleen.",
)
def login():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = portal_service.portal_login_with_audit(email=email, password=password)
        if user is None:
            return render_template("portal/login.html", error="Virheellinen sähköposti tai salasana.")
        session["portal_user_id"] = user.id
        return redirect(url_for("portal.dashboard"))
    return render_template("portal/login.html", error=None)


@portal_bp.route("/magic-link", methods=["POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Liian monta yritystä. Odota hetki ja yritä uudelleen.",
)
def request_magic_link():
    email = (request.form.get("email") or "").strip().lower()
    portal_service.send_portal_magic_link_email_and_audit(email=email)
    flash("Jos käyttäjätilisi on olemassa, sähköpostiisi lähetettiin kirjautumislinkki.")
    return redirect(url_for("portal.login"))


@portal_bp.get("/magic/<token>")
def magic_link_login(token: str):
    user = portal_service.complete_portal_magic_link_login(raw_token=token)
    if user is None:
        abort(404)
    session["portal_user_id"] = user.id
    return redirect(url_for("portal.dashboard"))


@portal_bp.get("/logout")
def logout():
    session.pop("portal_user_id", None)
    flash("Olet kirjautunut ulos.")
    return redirect(url_for("portal.login"))


@portal_bp.get("/dashboard")
@require_portal_login
def dashboard(user):
    stats = portal_service.get_dashboard_stats(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/dashboard.html", stats=stats)


@portal_bp.get("/reservations")
@require_portal_login
def reservations(user):
    rows = portal_service.list_reservations(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/reservations.html", rows=rows)


@portal_bp.get("/reservations/<int:reservation_id>")
@require_portal_login
def reservation_detail(user, reservation_id: int):
    try:
        row = portal_service.get_reservation(
            organization_id=user.organization_id,
            guest_id=user.id,
            reservation_id=reservation_id,
        )
    except portal_service.PortalServiceError:
        abort(404)
    return render_template("portal/reservation_detail.html", row=row)


@portal_bp.get("/invoices")
@require_portal_login
def invoices(user):
    rows = portal_service.list_invoices(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/invoices.html", rows=rows)


@portal_bp.route("/invoices/<int:invoice_id>/pay", methods=["GET", "POST"])
@require_portal_login
def pay_invoice(user, invoice_id: int):
    try:
        invoice = portal_service.get_invoice(
            organization_id=user.organization_id,
            guest_id=user.id,
            invoice_id=invoice_id,
        )
    except portal_service.PortalServiceError:
        abort(404)

    if request.method == "POST":
        provider = (request.form.get("provider") or "").strip().lower()
        base_return = url_for("portal.payment_return", _external=True)
        sep = "&" if "?" in base_return else "?"
        return_url = f"{base_return}{sep}payment_id={{payment_id}}"
        cancel_url = url_for("portal.payment_cancel", invoice_id=invoice_id, _external=True)
        try:
            out = payment_service.create_checkout(
                invoice_id=invoice_id,
                provider_name=provider,
                return_url=return_url,
                cancel_url=cancel_url,
                actor_user_id=user.id,
                idempotency_key=(request.headers.get("Idempotency-Key") or "").strip() or None,
            )
        except payment_service.PaymentServiceError as err:
            msg = _payment_error_message_for_portal(err.code)
            flash(msg)
            return render_template(
                "portal/pay_invoice.html",
                row=invoice,
                stripe_enabled=current_app.config.get("STRIPE_ENABLED", False),
                paytrail_enabled=current_app.config.get("PAYTRAIL_ENABLED", False),
                error=msg,
            )
        return redirect(out["redirect_url"])

    return render_template(
        "portal/pay_invoice.html",
        row=invoice,
        stripe_enabled=current_app.config.get("STRIPE_ENABLED", False),
        paytrail_enabled=current_app.config.get("PAYTRAIL_ENABLED", False),
        error=None,
    )


@portal_bp.get("/payments/return")
@require_portal_login
def payment_return(user):
    raw = (request.args.get("payment_id") or "").strip()
    payment_id = int(raw) if raw.isdigit() else None
    row = None
    poll_url = None
    if payment_id is not None:
        row = Payment.query.filter_by(id=payment_id, organization_id=user.organization_id).first()
        if row is None:
            payment_id = None
        else:
            poll_url = url_for("portal.portal_payment_status", payment_id=payment_id)
    return render_template(
        "portal/payment_return.html",
        payment_id=payment_id,
        payment=row,
        poll_url=poll_url,
    )


@portal_bp.get("/payments/<int:payment_id>/status")
@require_portal_login
def portal_payment_status(user, payment_id: int):
    row = Payment.query.filter_by(id=payment_id, organization_id=user.organization_id).first()
    if row is None:
        abort(404)
    return jsonify(
        {
            "id": row.id,
            "status": row.status,
            "amount": str(row.amount),
            "currency": row.currency,
            "invoice_id": row.invoice_id,
        }
    )


@portal_bp.get("/payments/cancel/<int:invoice_id>")
@require_portal_login
def payment_cancel(user, invoice_id: int):
    _ = user
    return render_template("portal/payment_cancel.html", invoice_id=invoice_id)


@portal_bp.route("/maintenance", methods=["GET", "POST"])
@require_portal_login
def maintenance(user):
    error = None
    if request.method == "POST":
        reservation_id_raw = (request.form.get("reservation_id") or "").strip()
        try:
            reservation_id = int(reservation_id_raw)
            _ = portal_service.create_maintenance_request(
                organization_id=user.organization_id,
                guest_id=user.id,
                reservation_id=reservation_id,
                title=(request.form.get("title") or "").strip(),
                description=(request.form.get("description") or "").strip() or None,
                priority=(request.form.get("priority") or "normal").strip().lower(),
                due_date_raw=(request.form.get("due_date") or "").strip() or None,
            )
        except ValueError:
            error = "Varaus on pakollinen."
        except portal_service.PortalServiceError as exc:
            if exc.status == 404:
                abort(404)
            error = exc.message
        else:
            flash("Huoltopyyntö luotu.")
            return redirect(url_for("portal.maintenance"))
    rows = portal_service.list_maintenance_requests(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    options = portal_service.maintenance_form_scope(
        organization_id=user.organization_id,
        guest_id=user.id,
    )
    return render_template("portal/maintenance.html", rows=rows, options=options, error=error)


@portal_bp.get("/maintenance/<int:request_id>")
@require_portal_login
def maintenance_detail(user, request_id: int):
    try:
        row = portal_service.get_maintenance_request(
            organization_id=user.organization_id,
            guest_id=user.id,
            request_id=request_id,
        )
    except portal_service.PortalServiceError:
        abort(404)
    return render_template("portal/maintenance_detail.html", row=row)


@portal_bp.route("/check-in/<token>", methods=["GET", "POST"])
def check_in(token: str):
    if request.method == "GET":
        return render_template("portal/checkin.html", error=None, access_code=None)
    full_name = (request.form.get("full_name") or "").strip()
    dob_raw = (request.form.get("date_of_birth") or "").strip()
    rules_signature = (request.form.get("rules_signature") or "").strip()
    idempotency_key = (
        (request.headers.get("Idempotency-Key") or "").strip()
        or (request.form.get("idempotency_key") or "").strip()
        or None
    )
    file = request.files.get("id_document")
    if not full_name or not dob_raw or not rules_signature or file is None or not file.filename:
        return (
            render_template(
                "portal/checkin.html",
                error="Kaikki kentät ovat pakollisia verkkokirjautumisessa.",
                access_code=None,
            ),
            400,
        )
    try:
        dob = date.fromisoformat(dob_raw)
    except ValueError:
        return (
            render_template("portal/checkin.html", error="Virheellinen syntymäaika.", access_code=None),
            400,
        )
    try:
        _, access_code = portal_service.complete_checkin(
            token=token,
            full_name=full_name,
            date_of_birth=dob,
            id_document_bytes=file.read(),
            id_document_name=file.filename,
            rules_signature=rules_signature,
            idempotency_key=idempotency_key,
        )
    except portal_service.PortalServiceError as exc:
        if exc.status == 404:
            abort(404)
        return (
            render_template("portal/checkin.html", error=exc.message, access_code=None),
            exc.status,
        )
    return render_template("portal/checkin.html", error=None, access_code=access_code)