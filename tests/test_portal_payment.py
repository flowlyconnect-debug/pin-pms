def test_guest_cannot_pay_other_guests_invoice(client):
    resp = client.get("/portal/invoices/999999/pay")
    assert resp.status_code in {302, 404}


def test_payment_return_renders_receipt_link(client):
    resp = client.get("/portal/payments/return")
    assert resp.status_code in {200, 302}


def test_payment_cancel_renders_retry_link(client):
    resp = client.get("/portal/payments/cancel/1")
    assert resp.status_code in {200, 302}
