# Cursor-prompti — Maksuintegraation viimeistely (Prompt 9.5)

Tämä on jatko Prompt 9:lle. v1-toteutus on valmis mutta:
- Coverage 77.5 % < 80 % (init-template §22 hyväksymiskriteeri rikki)
- Webhook-käsittelyn robustisuus puuttuu joiltakin osin
- Refund-skenaariot eivät ole täysin testattuja
- Admin-CSV/XLSX-export ei ole kytkettynä payments-listaan

Liitä Cursoriin sellaisenaan. Tämä on keskittynyt iteraatio, EI uusi iso ominaisuus.

```
Tehtävä: Viimeistele maksuintegraatio (Stripe + Paytrail) tuotantotasoiseksi.

Tausta: Prompt 9:n v1 on valmis (payments-moduuli, providerit, reitit, webhookit, idempotency, CLI, migraatio, admin-UI, portal-UI, sähköpostipohjat). Kuitenkin:
- pytest -v --cov=app --cov-fail-under=80 → 77.5 % (alle vaaditun rajan)
- Webhook-käsittely toimii happy-pathilla mutta ei ole testattu kuormassa, network-virheissä, eikä idempotency-konfliktissa
- Refund- ja partial-refund-kirjanpito on perustasoa
- /admin/payments -CSV-vienti ei ole vielä kytketty 8D:n export-mekanismiin
- "Paljon tiedostoja, vähän testejä" = alhainen coverage

Kohdista parannukset siten että init-template §22 hyväksymiskriteerit täyttyvät ja maksuintegraatio kestää tuotantokuorman.

Vaihe 1: Diagnostiikka (älä muokkaa vielä)
1. Aja: pytest --cov=app --cov-report=term-missing | grep -E "app/payments|app/webhooks" | head -50
2. Listaa rivit joilla on "missing" — nämä ovat haaroja jotka eivät ole testikatteen alla
3. Painota fokus näihin: app/payments/services.py, providers/stripe.py, providers/paytrail.py, app/webhooks/services.py (refund-osio)
4. Aja: pytest tests/test_payments_*.py -v 2>&1 | tail -30 — katso mitkä testit lähinnä toimivat ja missä on aukot
5. Raportoi käyttäjälle missä on suurin coverage-aukko ennen kuin lisäät testejä

Vaihe 2: Webhook-robustisuus (app/webhooks/services.py + app/payments/services.py)

a) Idempotenssi-konflikti:
- Jos sama webhook-event tulee TOISEN kerran (Stripe lähettää webhookin uudelleen), pitää palauttaa 200 OK ilman uudelleenkäsittelyä
- Käytä WebhookEvent.external_id + UNIQUE-rajoitusta + INSERT...ON CONFLICT DO NOTHING -patterniä TAI try/except IntegrityError
- Audit-loki: action="webhook.duplicate_ignored", level=info (ei warning, koska tämä on odotettu)

b) Provider-API:n hidas vastaus:
- Webhook-handler ei saa odottaa providerin vastausta yli 5 sekuntia (Stripe TIMEOUT)
- Jos käsittely vie kauemmin, palauta 200 OK heti ja jatka taustatyössä (queue with-status="processing")
- Yksinkertaisin tapa: tallenna WebhookEvent.processed=False, palauta 200, processi APSchedulerilla

c) Allekirjoituksen virhe:
- 401 Unauthorized + audit FAILURE
- Älä paljasta error-vastauksessa miksi epäonnistui (security)
- Loki: detail (jolla maskaus suoritettu signature-arvolle)

d) Provider unknown:
- Jos pyyntö tulee /api/v1/webhooks/<provider> jossa provider ei ole "stripe" tai "paytrail", palauta 404
- Audit: action="webhook.unknown_provider"

e) Payload-koko:
- Rajoita request.content_length < 1 MB (Stripe-event on yleensä < 50 KB, > 1MB on epäilyttävä)
- Yli rajan: 413 Payload Too Large + audit

Vaihe 3: Refund- ja partial-refund-skenaariot (app/payments/services.py refund() + handle_webhook_event())

a) Partial refund:
- Payment.amount = 100 €, ensimmäinen refund 30 €, toinen 50 €
- Status muutos: succeeded → partially_refunded → partially_refunded → refunded (kun yhteissumma == amount)
- Älä salli yli amount:ia menevää refundia
- PaymentRefund-rivit linkittyvät yhteen Paymentiin
- Audit: jokainen refund kirjautuu erikseen

b) Refund-failure:
- Stripe API kaatuu (esim. invalid_request) → PaymentRefund.status = "failed", last_error tallennetaan
- Audit: action="payment.refund_failed"
- Admin-UI näyttää virheen ja sallii uuden yrityksen

c) Refund-webhookin kesto:
- Stripe lähettää charge.refunded -webhookin asynkronisesti
- Päivitä Payment.status vain kun webhook saapuu, ei refund-pyyntö-vaiheessa
- Tämä takaa että UI näyttää oikean tilan vasta kun rahat ovat oikeasti palautuneet

d) Idempotenssi:
- Refund-pyyntö samalla idempotency-keyllä → palauta sama vastaus
- Käytä Idempotency-Key headeria (Prompt 7B) tai luo automaattisesti

Vaihe 4: Lisää testit (tests/test_payments_*.py + tests/test_webhooks*.py)

Erityisesti seuraavat:

tests/test_payments_stripe.py:
- test_create_checkout_with_vat_breakdown_passes_correct_line_items_to_stripe (mock stripe.checkout.Session.create, verify call args)
- test_webhook_succeeded_marks_invoice_paid_and_publishes_event (assert publisher.publish called with "invoice.paid")
- test_webhook_succeeded_sends_receipt_email (queue assertion)
- test_webhook_failed_sets_payment_status (status="failed")
- test_webhook_handles_unknown_event_type_gracefully (Stripe lähettää joskus uudet event_typeja — älä kaada)
- test_refund_partial_then_full (Payment.status: succeeded → partially_refunded → refunded)
- test_refund_exceeding_amount_returns_400
- test_refund_idempotency_with_key (sama key + sama amount → no-op, sama key + eri amount → 409)

tests/test_payments_paytrail.py:
- test_signature_calculation_matches_paytrail_official_example (käytä Paytrailin doc:n esimerkki-payloadia ja vertaa output)
- test_callback_get_request_with_valid_signature_processes_event
- test_callback_invalid_signature_returns_401
- test_callback_unknown_status_returns_400 (Paytrailin checkout-status muu kuin ok/fail)
- test_amount_in_cents_correctly_converted (€10.00 → 1000 sentissä)
- test_paytrail_refund_signature_calculation
- test_paytrail_provides_field_includes_finnish_banks (OP, Nordea, Danske, Handelsbanken)

tests/test_payments_routes.py:
- test_checkout_with_invalid_provider_returns_400
- test_checkout_with_amount_zero_returns_400
- test_checkout_returns_503_when_provider_disabled (STRIPE_ENABLED=0)
- test_get_payment_returns_404_for_other_org_payment (tenant-isolation)
- test_refund_requires_admin_role_not_user (regular user → 403)
- test_refund_creates_payment_refund_row
- test_refund_route_uses_idempotency_key

tests/test_portal_payment.py:
- test_pay_invoice_shows_only_enabled_providers
- test_pay_invoice_other_org_invoice_returns_404
- test_pay_invoice_already_paid_returns_redirect_with_message
- test_payment_return_renders_receipt_link
- test_payment_cancel_renders_retry_link

tests/test_payments_audit.py:
- test_full_lifecycle_audits_all_states (checkout_created → received → refund_initiated → refund_completed)
- test_invalid_signature_audited_as_failure
- test_duplicate_webhook_audited_as_info_not_warning

Vaihe 5: Admin-CSV-vienti
- /admin/payments-listalla "Vie CSV" -painike
- Käytä Prompt 8D:n export-mekanismia (jos jo olemassa) tai luo uusi:
  GET /admin/payments/export?format=csv&<filters>
- Sarakkeet: id, created_at, provider, amount, currency, status, method, invoice_number, customer_email
- Suodattimet samat kuin /admin/payments-listalla (provider, status, päiväväli)
- Audit: action="payment.exported"
- Testi: test_admin_payment_csv_export_includes_only_own_org

Vaihe 6: Coverage-mittarit
- Aja: pytest --cov=app --cov-fail-under=80 — pitää nyt mennä läpi
- Jos coverage on edelleen alle 80 %, raportoi käyttäjälle TÄSMÄLLISET puutuvat haarat (käytä --cov-report=html ja avaa htmlcov/index.html)

Vaihe 7: Manuaalitesti-checklist (käyttäjälle ohjeena)
- Lisää README.md:hen sektio "Maksuintegraation manuaalitesti":
  1. Stripe testimoodi:
     - export STRIPE_SECRET_KEY=sk_test_...
     - stripe listen --forward-to localhost:5000/api/v1/webhooks/stripe (toinen terminaali)
     - flask payments-test-stripe → ohjautuu Stripe Checkoutiin
     - Maksa testikortilla 4242 4242 4242 4242, mikä tahansa CVV+future date
     - Tarkista webhook tuli läpi, audit-loki, sähköpostipohja
  2. Paytrail testimoodi:
     - export PAYTRAIL_MERCHANT_ID=375917 (Paytrailin julkinen testitili)
     - export PAYTRAIL_SECRET_KEY=SAIPPUAKAUPPIAS (tunnettu testisecret)
     - flask payments-test-paytrail → ohjautuu Paytrailin demosivulle
     - Valitse "Nordea Demo" → vahvista
     - Tarkista callback tuli, audit-loki

Tiedostot:
- app/payments/services.py (refund-skenaariot, idempotenssi-vahvistus)
- app/payments/providers/stripe.py (timeout-käsittely)
- app/payments/providers/paytrail.py (signature-tarkistus, partial refund)
- app/webhooks/services.py (duplicate-ignore, payload-koko, unknown-provider)
- app/admin/routes.py (CSV-export-reitti)
- app/templates/admin/payments/list.html (CSV-export-painike)
- README.md (manuaalitesti-osio)
- tests/test_payments_*.py (laajennus)
- tests/test_webhooks*.py (uudet skenaariot)

ÄLÄ:
- Älä lisää 'unsafe-inline' CSP:hen (uudet UI-elementit käyttävät static .js-tiedostoja)
- Älä logita raakaa Stripe-payloadia (sisältää PII — käytä RedactingFilter Prompt 4)
- Älä koske Renderissä jo ajettuihin migraatioihin (a7b8c9d0e1f2, 2d7c6826218b ym.) — tee uusi migraatio jos tarvitaan tietokannan rakenteeseen muutosta
- Älä laske coverage-vaatimusta alle 80 % (init-template §16)
- Älä cachee tarpeettomasti — payment-data muuttuu nopeasti
- Älä julkista Paytrailin testisecrettiä prod-konfiguraatioon vahingossa

Aja lopuksi:
1. pytest tests/test_payments_*.py tests/test_webhooks*.py -v
2. pytest -v --cov=app --cov-fail-under=80 — pitää mennä läpi
3. Aja: flask db upgrade (jos uutta migraatiota)
4. Manuaalitesti Stripe-testimoodissa
5. Manuaalitesti Paytrail-testitilillä
6. Raportoi käyttäjälle: "Coverage X.X % (tavoite 80 %), kaikki testit vihreänä, manuaalitestit OK"
```

---

## Sen jälkeen committaa ja pushaa

Tämä on iso commit jossa on Prompt 9 (v1) + Prompt 9.5 (hardening). Jaa kahteen committiin selkeyden vuoksi:

```powershell
.venv\Scripts\activate

# Vahvista että tests/-indeksi on jo palautettu (vaihe 1 yllä)
git status --short tests/ | head -10

# Aja kaikki testit ja coverage — pitää mennä läpi nyt 80%+
pytest -v --cov=app --cov-fail-under=80
```

Jos vihreä, jaa kahteen committiin:

```powershell
# Lock pois jos tarpeen
Remove-Item -Force .git\index.lock 2>$null

# Commit 1 — Prompt 9 v1 (kaikki uudet payments-tiedostot)
git add app/payments/
git add app/api/payments.py
git add app/api/__init__.py
git add app/api/models.py
git add migrations/versions/1a2b3c4d5e6f_add_payments_tables.py
git add app/cli.py
git add app/config.py
git add .env.example
git add requirements.txt
git add app/__init__.py
git add app/email/seed_data.py
git add app/email/models.py
git add app/portal/routes.py
git add app/portal/services.py
git add app/templates/portal/pay_invoice.html
git add app/templates/portal/payment_return.html
git add app/templates/portal/payment_cancel.html
git add app/templates/portal/invoices.html
git add app/admin/routes.py
git add app/templates/admin/invoices/detail.html
git add app/templates/admin/payments/list.html
git add app/webhooks/routes.py
git add app/webhooks/services.py
git add tests/test_payments_models.py
git add tests/test_payments_stripe.py
git add tests/test_payments_paytrail.py
git add tests/test_payments_routes.py
git add tests/test_portal_payment.py
git add tests/test_payments_audit.py
git add tests/conftest.py
git add README.md

git commit -m "feat(payments): Stripe + Paytrail integration (Prompt 9)

Generic Payment + PaymentRefund models with provider abstraction.
Stripe Checkout + Paytrail Payment Page (PCI-DSS SAQ-A scope).
Webhooks via Prompt 7C inbound framework, idempotency via Prompt 7B.
ALV breakdown via Prompt 5, PDF receipt via Prompt 7.
Audit log on every state change.
CLI commands: payments-test-stripe, payments-test-paytrail, payments-list, payments-prune-expired."

# Commit 2 — Prompt 9.5 hardening (jos teit Cursorilla viimeistelyn)
# Tämä commit sisältää lisätyt testit + webhook-robustisuus + refund-skenaariot
git add tests/test_payments_stripe.py tests/test_payments_paytrail.py tests/test_payments_routes.py tests/test_portal_payment.py tests/test_payments_audit.py
git add app/payments/services.py app/payments/providers/stripe.py app/payments/providers/paytrail.py
git add app/webhooks/services.py
git add app/admin/routes.py app/templates/admin/payments/list.html
git add README.md

git commit -m "fix(payments): harden webhook handling, partial refunds, idempotency conflicts; raise coverage above 80%"

# Tarkista ennen pushia
git log --stat -2 | head -30

# Push — laukaisee Renderin uuden deploymentin
git push origin main
```

[Avaa hardening-prompti](computer://C:\Users\matso\Downloads\pindora-pms\CURSOR_PROMPT_PAYMENTS_HARDEN.md)

## Pushin jälkeen Renderille

1. Render rakentaa uuden imagen (~3-5 min — payments-moduuli isohko, mutta build pitäisi onnistua)
2. Build käy läpi: `flask db upgrade` ajaa migraation `1a2b3c4d5e6f_add_payments_tables` → uusi `payments`- ja `payment_refunds`-taulu
3. Renderissä lisää **Environment Variables**:
   - `STRIPE_ENABLED=1` (tai 0 jos haluat test-vaihteessa odotellen)
   - `STRIPE_SECRET_KEY=sk_live_...` (tuotanto) tai `sk_test_...` (testaus)
   - `STRIPE_WEBHOOK_SECRET=whsec_...` (saa Stripe Dashboard → Webhooks → "Add endpoint")
   - `PAYTRAIL_ENABLED=1`
   - `PAYTRAIL_MERCHANT_ID=...`
   - `PAYTRAIL_SECRET_KEY=...`
   - `PAYMENT_RETURN_URL=https://pin-pms.onrender.com/portal/payments/return`
   - `PAYMENT_CALLBACK_URL=https://pin-pms.onrender.com/api/v1/webhooks/paytrail`
4. **Stripe Dashboard:** Webhooks → "Add endpoint" → URL: `https://pin-pms.onrender.com/api/v1/webhooks/stripe` → events: `checkout.session.completed`, `payment_intent.payment_failed`, `charge.refunded` → tallenna webhook secret env:iin
5. **Paytrail-portaali:** Settings → Callback URLs → lisää sama URL kuin `PAYMENT_CALLBACK_URL`
6. Tee testimaksu pienellä summalla (esim. 0,50 €) Stripe-testikortilla ja Paytrail-testitilillä — varmista että webhookit menevät läpi ja audit-loki näyttää tapahtumat

## Yhteenveto

Tämä viimeistely tekee maksuintegraatiosta tuotantotason. v1 oli hyvä runko mutta kestää tuotantoliikenteen vasta kun:
1. Idempotenssi-konfliktit testattu
2. Refund- ja partial-refund-flow testattu
3. Webhook-virheet (timeout, invalid signature) käsitelty
4. Coverage palannut 80%+
5. Manuaalitestit Stripe + Paytrail testimoodissa läpi

Tee Cursor-prompti ensin, varmista pytest vihreä + coverage 80%+, sitten committaa ja pushaa kahdessa erässä. Render rakentaa uuden imagen ja maksuintegraatio menee tuotantoon. Customer voi sitten alkaa testata.