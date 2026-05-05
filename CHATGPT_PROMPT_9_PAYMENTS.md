# Prompt 9 — Maksuintegraatio (Stripe + Paytrail)

Asiakas valitsi **Stripe** (kortit, ulkomaisille vieraille) ja **Paytrail** (kotimaiset verkkopankit + MobilePay + kortit).

> Liitä ChatGPT:lle. Muistuta Prompt 0:n säännöistä jos ChatGPT-keskustelu on vaihtunut.

---

## PROMPT 9 — Maksuintegraatio (Stripe + Paytrail)

```
Tehtävä Cursorille: Lisää maksuintegraatio sekä Stripelle että Paytrailille käyttäen jo olemassa olevaa webhook-runkoa (Prompt 7C) ja idempotency-mekanismia (Prompt 7B).

Tausta: Asiakas haluaa molemmat tarjoajat — Stripe ulkomaisille kortinhaltijoille, Paytrail suomalaisille verkkopankeille (Nordea, OP, Danske), MobilePaylle ja kotimaisille korteille. Kumpaakaan ei vaihdeta toiseksi runtimessa — käyttäjä valitsee maksusivulla. Init-template pakottaa: service-kerros, audit-loki, oikeustarkistus, tenant-isolation, idempotency, ei kovakoodattuja salaisuuksia.

PCI-DSS: Käytä AINA hostattuja maksulomakkeita (Stripe Checkout / Paytrail Payment Page). ÄLÄ koskaan käsittele kortin numeroa omalla palvelimella. Tämä pitää PCI-DSS:n laajuuden minimissä (SAQ-A).

Vaihe 1: Riippuvuudet
- requirements.txt:
  + stripe>=8.0,<10
  + Paytrailille käytetään pelkkää requests-kutsua (ei virallista SDK:ta)

Vaihe 2: Env-muuttujat (.env.example)
- # Stripe — kansainväliset kortit
- STRIPE_ENABLED=0
- STRIPE_PUBLISHABLE_KEY=
- STRIPE_SECRET_KEY=
- STRIPE_WEBHOOK_SECRET=
- # Paytrail — Suomen kotimaiset verkkopankit ja MobilePay
- PAYTRAIL_ENABLED=0
- PAYTRAIL_MERCHANT_ID=
- PAYTRAIL_SECRET_KEY=
- PAYTRAIL_API_BASE=https://services.paytrail.com
- # Yhteiset
- PAYMENT_RETURN_URL=https://app.example.com/payments/return
- PAYMENT_CALLBACK_URL=https://app.example.com/api/v1/webhooks/paytrail
- # Stripe-callback käytetään /api/v1/webhooks/stripe — kovakoodaamatonta secretiä ei tallenneta env:iin tarpeen jälkeen, secret on ProductionConfig.

Vaihe 3: Konfiguraatio (app/config.py)
- Lue env-arvot ProductionConfigissa, vaadi RuntimeError jos *_ENABLED=1 mutta secret puuttuu
- DevelopmentConfigissa salli puuttuminen, mutta loggaa varoitus jos *_ENABLED=1

Vaihe 4: Uusi moduuli app/payments/
Tiedostot:
- app/payments/__init__.py
- app/payments/models.py
- app/payments/services.py
- app/payments/routes.py
- app/payments/providers/__init__.py
- app/payments/providers/base.py
- app/payments/providers/stripe.py
- app/payments/providers/paytrail.py
- app/payments/scheduler.py (vapaaehtoinen — webhookien retry on jo Prompt 7C:ssä)

Vaihe 5: Payment-malli (app/payments/models.py)
- Payment:
  - id, organization_id (FK), invoice_id (FK, nullable jos depositti ei vielä laskutettu)
  - reservation_id (FK, nullable)
  - provider (string: "stripe" | "paytrail")
  - provider_payment_id (string 128, providerin oma transaction id)
  - provider_session_id (string 128, checkout-session id, nullable)
  - amount (Numeric 12, 2)
  - currency (string 3, "EUR")
  - status (string: "pending" | "succeeded" | "failed" | "refunded" | "partially_refunded" | "expired")
  - method (string: "card" | "bank" | "mobilepay" | "other", nullable)
  - last_error (Text, nullable)
  - idempotency_key (string 128, nullable, UNIQUE) — viittaa app/idempotency/-mekanismiin
  - return_url (string), cancel_url (string)
  - created_at, updated_at, completed_at (nullable)
  - metadata (JSON) — esim. {"customer_email": "...", "vat_amount": "..."}
- PaymentRefund:
  - id, payment_id (FK)
  - amount (Numeric)
  - reason (Text)
  - provider_refund_id (string 128)
  - status (string: "pending" | "succeeded" | "failed")
  - actor_user_id (FK)
  - created_at, completed_at (nullable)

Vaihe 6: Provider-rajapinta (app/payments/providers/base.py)
- Abstrakti pohja:
  class PaymentProvider(ABC):
      name: str
      
      @abstractmethod
      def create_checkout(self, *, amount, currency, invoice, return_url, cancel_url, idempotency_key) -> dict:
          """Returns {provider_session_id, redirect_url, expires_at}"""
      
      @abstractmethod
      def verify_webhook(self, *, payload_bytes, signature_header) -> bool:
          """Provider-specific HMAC/signature check"""
      
      @abstractmethod
      def parse_webhook_event(self, *, payload: dict) -> dict:
          """Returns normalized {type: 'payment.succeeded'|'payment.failed'|'refund.succeeded', payment_id, amount, ...}"""
      
      @abstractmethod
      def refund(self, *, provider_payment_id, amount, reason, idempotency_key) -> dict:
          """Returns {provider_refund_id, status}"""

Vaihe 7: Stripe-toteutus (app/payments/providers/stripe.py)
- create_checkout:
  - stripe.checkout.Session.create(
      payment_method_types=["card"],
      line_items=[{...VAT-erottelulla...}],
      mode="payment",
      success_url=return_url,
      cancel_url=cancel_url,
      customer_email=invoice.customer_email,
      metadata={"invoice_id": invoice.id, "organization_id": invoice.organization_id},
      idempotency_key=idempotency_key,  # Stripe SDK:n parametri
    )
  - Tallennetaan: provider_session_id = session.id, redirect_url = session.url, expires_at = session.expires_at
- verify_webhook:
  - stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
  - Hakee secret config:sta — ÄLÄ kovakoodaa
- parse_webhook_event:
  - checkout.session.completed → payment.succeeded
  - payment_intent.payment_failed → payment.failed
  - charge.refunded → refund.succeeded
- refund: stripe.Refund.create(payment_intent=..., amount=..., reason=..., metadata={...})

Vaihe 8: Paytrail-toteutus (app/payments/providers/paytrail.py)
- Paytrailin REST API:n dokumentaatio: https://docs.paytrail.com/
- Kaikki pyynnöt allekirjoitetaan HMAC-SHA256:lla (`signature` header)
- Allekirjoituksen rakentaminen:
  ```python
  def calculate_signature(secret, headers, body):
      paytrail_headers = sorted(
          (k, v) for k, v in headers.items() 
          if k.lower().startswith("checkout-")
      )
      message = "\n".join(f"{k}:{v}" for k, v in paytrail_headers) + "\n" + (body or "")
      return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
  ```
- create_checkout:
  - POST https://services.paytrail.com/payments
  - Headers: checkout-account, checkout-algorithm=sha256, checkout-method=POST, checkout-nonce, checkout-timestamp, signature
  - Body: stamp (idempotency_key), reference, amount (sentteinä, integer!), currency, items, customer, redirectUrls, callbackUrls, language="FI"
  - Vastaus: {transactionId, href (redirect), providers: [...]}
- verify_webhook:
  - HUOM: callback-pyyntö on GET, mutta sisältää kaikki samat checkout-* parametrit query-stringissä
  - Lasketaan signature samalla algoritmilla kuin pyyntöjen luonnissa
- parse_webhook_event:
  - checkout-status=ok → payment.succeeded
  - checkout-status=fail → payment.failed
- refund:
  - POST /payments/{transactionId}/refund
  - Body: refundStamp (idempotency), amount, refundReference, callbackUrls

Vaihe 9: Service-kerros (app/payments/services.py)
- create_checkout(invoice_id, provider_name, return_url, cancel_url, *, actor_user_id):
  - Tarkista että invoice.organization_id == actor's org_id (tenant-isolation)
  - Luo idempotency_key (`f"checkout-{invoice.id}-{int(time.time())}"`) tai käytä Idempotency-Key-headeria
  - Luo Payment-rivi tilaan "pending"
  - Kutsu provider.create_checkout(...)
  - Päivitä Payment.provider_session_id, redirect_url, expires_at
  - Audit: action="payment.checkout_created", target_type="payment", target_id=payment.id
  - Palauta {payment_id, redirect_url}
- handle_webhook_event(provider_name, normalized_event):
  - Tarkista idempotenssi: jos provider_payment_id käsitelty jo, palauta no-op (Prompt 7C tekee tämän jo)
  - Päivitä Payment-status normalized_event.type-arvon mukaan
  - Jos "payment.succeeded":
    - Aseta status="succeeded", completed_at=now()
    - Linkitä Invoice → mark_invoice_paid (tai jos osamaksu, ei merkitse vielä paidiksi)
    - Audit: action="payment.received"
    - Lähetä kuitti-sähköposti (käytä Prompt 7G:n queue-mekanismia)
    - Julkaise webhook-event "invoice.paid" (Prompt 7F:n publisheri)
    - Luo PDF-kuitti (Prompt 7:n pdf-service) ja lähetä liitteenä
  - Jos "payment.failed":
    - status="failed", last_error=normalized_event.error
    - Audit: action="payment.failed"
    - Lähetä admin-notifikaatio (Prompt 8E)
- refund(payment_id, amount, reason, *, actor_user_id):
  - Tarkista permissions (vain admin tai superadmin)
  - Tarkista tenant-isolation
  - Luo PaymentRefund tilaan "pending"
  - Kutsu provider.refund(...)
  - Audit: action="payment.refund_initiated"
  - Webhookin tullessa "refund.succeeded" → päivitä status, audit, julkaise "invoice.refunded"

Vaihe 10: API-reitit (app/payments/routes.py)
- POST /api/v1/payments/checkout @scope_required("payments:write") @idempotent_post("checkout")
  - Body: {invoice_id, provider, return_url, cancel_url}
  - Vastaus: {payment_id, redirect_url}
- GET /api/v1/payments/<payment_id> @scope_required("payments:read")
- POST /api/v1/payments/<payment_id>/refund @scope_required("payments:write")
  - Body: {amount, reason}
- POST /api/v1/webhooks/stripe — Prompt 7C:n inbound-runko hoitaa allekirjoituksen, sitten kutsuu services.handle_webhook_event("stripe", event)
- POST /api/v1/webhooks/paytrail tai GET /api/v1/webhooks/paytrail (Paytrail käyttää GET-callbackia!)
- HUOM: Webhook-endpointit EIVÄT vaadi API-avainta — varmennus tehdään HMAC-allekirjoituksella

Vaihe 11: Vieras-portaalin maksusivu
- Uusi reitti: /portal/invoices/<invoice_id>/pay
  - Näyttää laskun yhteenvedon (käyttäen Prompt 5:n VAT-erottelua)
  - Provider-valinta:
    - "Maksa kortilla (Stripe)" — kansainvälinen
    - "Maksa verkkopankissa (Paytrail)" — kotimainen
    - Näytä molemmat jos *_ENABLED=1
  - Klikkaus → kutsuu /api/v1/payments/checkout, ohjautuu redirect_url:iin
- Onnistumisen jälkeen palautus return_url:iin
  - Näytä kuitti, lataa PDF, kiitos-viesti
- Epäonnistumisen jälkeen cancel_url:iin
  - Selitä syy, mahdollistaa uuden yrityksen

Vaihe 12: Admin-UI
- Lasku-näkymässä:
  - "Lähetä maksulinkki" -painike → luo Payment-rivi + lähettää sähköpostin maksulinkillä
  - "Hyvitä" -painike (vain succeeded-tilan maksuille)
- /admin/payments — lista organisaation maksuista
  - Suodattimet (provider, status, päiväväli) — käyttää Prompt 8D:n suodatin-rakennetta
  - Vienti CSV/XLSX

Vaihe 13: Sähköposti-pohjat
- Lisää seed-pohjat (app/email/seed_data.py):
  - "payment_link" — "Tässä on linkki laskusi 12345 maksamiseen"
  - "payment_received" — "Maksusi on vastaanotettu — kuitti liitteenä"
  - "payment_failed" — "Maksusi epäonnistui, yritä uudestaan"
  - "refund_completed" — "Hyvitys on suoritettu tilillenne"

Vaihe 14: ALV-yhteensopivuus
- Käytä Prompt 5:n VAT-mekanismia
- Stripe line_items: erottele subtotal_excl_vat ja vat_amount
- Paytrail items: items[].vatPercentage = invoice.vat_rate (Paytrail vaatii kokonaisluvun)
- Kuitti-PDF generoituu Prompt 7:n pdf-servicellä, sisältää ALV-erittelyn

Vaihe 15: Webhook-julkaiseminen (Prompt 7F)
- Kun Payment.status muuttuu succeeded → publish "invoice.paid" subscribereille
- Kun PaymentRefund succeeded → publish "invoice.refunded"

Vaihe 16: Idempotency (Prompt 7B)
- /api/v1/payments/checkout — käyttää @idempotent_post -decoratoria
- Webhookien käsittely on jo idempotenttia provider_payment_id:n kautta (Prompt 7C)
- Refund-pyyntö — vaatii Idempotency-Key-headerin tai luodaan automaattinen

Vaihe 17: Audit-tapahtumat
- payment.checkout_created
- payment.received
- payment.failed
- payment.refund_initiated
- payment.refund_completed
- payment.refund_failed
- payment.expired (jos Stripe-session vanhenee)

Vaihe 18: CLI-komennot (app/cli.py)
- flask payments-test-stripe — luo testimaksu Stripeen (test mode), tulosta redirect-URL
- flask payments-test-paytrail — sama Paytrailille
- flask payments-list --status=pending — lista odottavista maksuista
- flask payments-prune-expired --days=30 — siivoa vanhentuneet sessiot

Vaihe 19: Migraatio
- flask db migrate -m "add_payments_tables"
- Tarkista että migraatio:
  - Lisää payments + payment_refunds taulut
  - Päivittää down_revisionin oikein (uusin head: d4e5f6a7b8c9 tai mitä tahansa headia kannassa on)
- flask db upgrade

Vaihe 20: Testit (laaja, jaa useaan tiedostoon)
- tests/test_payments_models.py:
  - Payment-mallin perustestaus
  - PaymentRefund tenant-isolation
- tests/test_payments_stripe.py:
  - test_create_checkout_returns_redirect_url (mockattu stripe.checkout.Session.create)
  - test_webhook_invalid_signature_returns_401
  - test_webhook_succeeded_marks_invoice_paid
  - test_refund_flow
  - test_idempotency_prevents_duplicate_checkout
- tests/test_payments_paytrail.py:
  - test_signature_calculation_matches_paytrail_spec (käytä Paytrailin esimerkki-payloadia)
  - test_callback_get_request_with_valid_signature
  - test_callback_invalid_signature_returns_401
  - test_amount_in_cents_not_euros (Paytrail vaatii sentit)
  - test_refund_flow
- tests/test_payments_routes.py:
  - test_checkout_requires_scope
  - test_checkout_tenant_isolation
  - test_get_payment_returns_only_own_org
  - test_refund_requires_admin_role
- tests/test_portal_payment.py:
  - test_pay_invoice_redirects_to_provider
  - test_payment_return_shows_receipt
  - test_payment_cancel_shows_retry_option
- tests/test_payments_audit.py:
  - test_each_payment_lifecycle_event_audited

Tiedostot:
- requirements.txt (stripe)
- .env.example (env-muuttujat)
- app/config.py (provider-konfiguraatio)
- app/payments/__init__.py, models.py, services.py, routes.py
- app/payments/providers/__init__.py, base.py, stripe.py, paytrail.py
- app/api/__init__.py (rekisteröi payments-routet)
- app/api/routes.py (palauta payment-tiedot lasku-resurssissa)
- app/portal/routes.py + templates (maksusivu)
- app/admin/routes.py + templates (maksulista, refund-painike)
- app/email/seed_data.py (uudet pohjat)
- migrations/versions/*.py (auto)
- tests/test_payments_*.py (useita, yllä lista)
- README.md (lisää "Maksuintegraatio"-luku)

ÄLÄ:
- Älä koskaan tallenna kortin numeroa, CVV:tä tai expiryä omaan kantaan
- Älä koskaan kutsu providerin REST API:a synkronisesti webhookin sisällä (luo idempotenssi-kerros)
- Älä luota client-side parametriin "amount" — laske aina backendissä laskun ALV-eritelmällä
- Älä unohda tenant-isolaatiota — vieras voi maksaa VAIN omaa laskuaan, ei toisen
- Älä unohda audit-lokia jokaisesta tilamuutoksesta
- Älä blokkaa webhook-vastauksia — palauta 200 OK heti kun signature on validi, käsittely taustalle jos hidasta
- Älä lähetä Stripeen tai Paytrailiin PII:tä jolle asiakkaalla ei ole hyväksyntää (kun käytetään customer_email Stripeen, on legitiimi syy = laskutus)
- Älä logita signature-headereita selväkielisinä (RedactingFilter Prompt 4 maskaa "signature"-avaimet — varmista että maskaus toimii myös request.headers["signature"]:n osalta)
- Älä käytä Stripe Elementsiä (frontend cardin-collection) — käytä Stripe Checkout:ia
- Älä yhdistä Stripe-ja Paytrail-tilejä samaan provider_payment_id-tarkistukseen — käytä (provider, provider_payment_id) -paria
- Älä julkista PAYMENT_CALLBACK_URL kovakoodattuna — on env:istä, ja se voi olla eri kehitysympäristön ja tuotannon välillä

Aja lopuksi:
1. flask db upgrade
2. flask seed-email-templates (uudet pohjat)
3. pytest tests/test_payments_*.py -v
4. pytest -v --cov=app --cov-fail-under=80
5. Manuaalitesti Stripe testimoodissa:
   - Aseta STRIPE_SECRET_KEY testikeyhin (sk_test_...)
   - Aseta STRIPE_WEBHOOK_SECRET stripe-CLI:lla
   - stripe listen --forward-to localhost:5000/api/v1/webhooks/stripe
   - flask payments-test-stripe → maksun läpiajo testikortilla 4242 4242 4242 4242
6. Manuaalitesti Paytrail-testimoodissa:
   - Aseta PAYTRAIL_MERCHANT_ID=375917, PAYTRAIL_SECRET_KEY=SAIPPUAKAUPPIAS (Paytrailin julkinen testitili)
   - flask payments-test-paytrail → ohjautuu Paytrailin demoon
7. Manuaalitesti hyvitys: tee maksu → admin-UI:sta hyvitys → vahvista että webhook tulee ja päivitys onnistuu
8. Tarkista audit-loki: jokaisella maksun tilanmuutoksella on audit-rivi
```

---

## Mitä asiakkaalta vielä mahdollisesti tarvitaan

Jos eivät vielä ole tulleet:
- **Paytrail merchant ID + Secret Key** (saa kirjautumalla paytrail.fi-portaaliin)
- **Stripe API-avaimet** (test- ja prod-tilille erikseen)
- **PCI-DSS SAQ-A -lomakkeen vahvistus** — Stripe Checkout pitää scope:n minimissä, mutta lomake silti täytetään
- **Hyvityskäytäntö** — milloin vieras voi peruuttaa maksun? Onko peruutusehdot kirjattava käyttöehtoihin?
- **Maksusivun branding** — logo, värit (Stripe Checkout sallii niiden konfiguroinnin)
- **Kuitti-PDF:n yritystiedot** — Y-tunnus, ALV-numero, IBAN (käytetään Prompt 7:n pdf-templatessa)

---

## Pushin jälkeen — Render

1. Varmista Renderin Environment-asetukset:
   - STRIPE_ENABLED, STRIPE_*-avaimet (production-arvot)
   - PAYTRAIL_ENABLED, PAYTRAIL_*-arvot
   - PAYMENT_RETURN_URL, PAYMENT_CALLBACK_URL (julkiset URL:t)
2. Stripen Dashboard → Webhooks → lisää `https://pin-pms.onrender.com/api/v1/webhooks/stripe`
3. Paytrailin portaalissa lisää `https://pin-pms.onrender.com/api/v1/webhooks/paytrail`
4. Aja `flask db upgrade` Renderin shellissä
5. Aja `flask seed-email-templates`
6. Tee testimaksu tuotannossa pienellä summalla (esim. 0,50 €) varmistaaksesi että webhookit toimivat

---

## Lopuksi

Tämän jälkeen sovellus on **maksuvalmis ja täydellinen** init-templaten mukaan + ammattitason PMS Suomen markkinoille. Maksuintegraatio on viimeinen iso paketti — sen jälkeen voit keskittyä asiakaspalautteeseen, oman brändin viimeistelyyn ja markkinointiin.

Jos jokin maksuun liittyvä ei onnistu (esim. Paytrailin signature-validointi heittää pelkkää 401:tä), tuo virheilmoitukset minulle.
