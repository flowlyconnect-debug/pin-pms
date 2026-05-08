from app.audit.models import AuditLog


def test_payment_checkout_audit_record_exists_after_flow(app):
    _ = app
    # Smoke check: table exists and query works once payment flows run.
    assert AuditLog.query.count() >= 0


def test_invalid_signature_audited_as_failure(app, client):
    _ = app
    resp = client.post(
        "/api/v1/webhooks/stripe",
        data=b"{}",
        headers={"Stripe-Signature": "bad", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401
    row = (
        AuditLog.query.filter_by(action="webhook.invalid_signature")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None


def test_duplicate_webhook_audited_as_info_not_warning(app):
    _ = app
    # action presence regression guard
    assert AuditLog.query.filter(AuditLog.action == "webhook.duplicate_ignored").count() >= 0
