# Pindora PMS — Kattava selvitys sovelluksen tilasta

**Päivämäärä:** 6.5.2026
**Selvityksen kohde:** `pindora-pms/` -repo (Render-deploy tuotannossa)
**Vertailupohja:** Asiakkaan init-template (Sovelluskehityksen init-template, §1–§23)
**Tarkastelun painopiste:** Maksuintegraatiot, Booking/Airbnb-kytkennät, mitä vielä puuttuu aidolta PMS:ltä

---

## 0. TL;DR — yhden minuutin yhteenveto

- Sovellus on **arkkitehtuurisesti kunnossa** ja täyttää init-templaten 23 pykälästä **22**. Vain §13 (UI-modernisointi) on osittain.
- **Hyväksymiskriteerit (§22) täyttyvät**: superadmin + 2FA, hashatut API-avaimet, päivittäinen backup, palautus 2FA:lla, audit-loki, Mailgun, testit, README, .env.example, Docker, migraatiot.
- **Maksut toimivat tuotantotasolla**: Stripe Checkout + Paytrail Payment Page, hostatut sivut (PCI-DSS SAQ-A), webhook-allekirjoituksen verifiointi, refund-kirjanpito, idempotency, audit-loki, sähköposti-ilmoitukset.
  - Maksuintegraatioissa **EI ole pakollisia avoimia töitä**, mutta **6 ammattitason puutetta** UX/operaation tasolla (kuvattu §3.B alla).
- **Booking.com / Airbnb -yhteys on vain yksisuuntainen iCal**. Tämä on aito PMS-näkökulmasta **kriittinen aukko** — pelkkä iCal ei riitä ammattitason kanavasynkkiin (ei hintapäivitystä, ei real-timea, ei overbooking-suojausta).
- **13 muuta ammattitason puutetta** (channel manager, i18n, a11y, kuvagalleria, ennakkomaksu, vieraskommunikaatio jne.) listattu §5 punch listissä.

Toisin sanoen: **runko on valmis ja turvallinen, maksut toimivat, mutta "aidoksi PMS:ksi" tarvitaan vielä erityisesti kahdensuuntainen channel manager.**

---

## 1. Sovelluksen tarkoitus ja teknologiapohja

### 1.1 Mikä tämä on

Pindora on **monitenanttinen kiinteistö-/lyhytvuokraus-PMS** (Property Management System), joka kattaa:

- Organisaatiot, käyttäjät (4 roolia), kiinteistöt, yksiköt
- Vieraat, varaukset (status-koneisto), vuokrasopimukset (lease) ja laskutus (invoice)
- Maintenance-tikettijärjestelmä (statuksilla ja prioriteeteilla)
- Vieraille oma portaali (`/portal`) ja omistajille oma portaali (`/owner_portal`)
- Maksuintegraatio (Stripe + Paytrail), refundit, kuitit
- iCal-kalenterituonti/-vienti (Airbnb/Booking)
- Pindora-älylukon API-integraatio (placeholder-rungon päällä)
- Ulkomaisille subscribereille lähtevä webhook-julkaisu (HMAC-allekirjoitettu)
- Audit-loki, GDPR-export, varmuuskopiot, sähköpostipohjat, rate limit, 2FA superadminille

### 1.2 Tekninen pino vs. init-template §1

| Vaatimus (§1)                 | Toteutus repossa                            | OK |
|-------------------------------|---------------------------------------------|----|
| Python 3 + Flask              | Python 3.12+, Flask                         | ✅ |
| Gunicorn                      | `Dockerfile` + `start.sh`                   | ✅ |
| Nginx                         | `deploy/` referenssi-konfit                 | ✅ |
| systemd                       | `deploy/`                                   | ✅ |
| PostgreSQL                    | `psycopg2-binary`, `docker-compose.yml`     | ✅ |
| SQLAlchemy + Alembic          | `flask-sqlalchemy`, `flask-migrate`         | ✅ |
| Flask-Login                   | requirements.txt                            | ✅ |
| API-avain / JWT               | API-avaimet hashattuina (Bearer / X-API-Key) | ✅ |
| Flask-WTF                     | requirements.txt + lomakkeet               | ✅ |
| Werkzeug-hashaus              | requirements.txt                            | ✅ |
| Mailgun                       | `app/email/services.py` + queue + retry     | ✅ |
| APScheduler                   | requirements.txt + 5+ ajastinta             | ✅ |
| Logging + journald            | `app/core/logging.py` + structlog           | ✅ |
| `.env`                        | `.env.example` (kaikki muuttujat dokumentoitu) | ✅ |
| pytest                        | `pytest.ini`, 80 % coverage gate            | ✅ |
| Virtualenv + Gunicorn + Nginx + systemd | dokumentoitu README:ssä          | ✅ |

**Ei kovakoodattuja salaisuuksia.** `gitleaks` pre-commit-hookissa ja `.gitleaks.toml` allowlist vain `tests/` ja `.env.example`.

---

## 2. Init-template noudatus pykäläkohtaisesti

| § | Aihe | Tila | Huomio |
|---|------|------|--------|
| 1 | Tekniikkapino | ✅ | Täysi |
| 2 | Moduulirakenne | ✅ | `app/` jaettu ohjeen mukaisesti + lisämoduulit (billing, payments, integrations, owner_portal, gdpr, idempotency, notifications, comments, tags, owners, status, subscriptions, webhooks) |
| 3 | Roolit | ✅ | `UserRole` enum: `superadmin`, `admin`, `user`, `api_client` |
| 4 | Autentikointi | ✅ | login, password reset, session, API-key, 2FA, lockout, CSRF |
| 5 | 2FA superadminille | ✅ | TOTP + varakoodit + QR-koodi + 2FA-pakotus ennen kriittisiä toimintoja |
| 6 | API | ✅ | `/api/v1/*`, Bearer + X-API-Key, scopes, hashatut avaimet, yhtenäinen JSON-envelope, `/api/v1/health`, `/api/v1/me`, OpenAPI + Swagger UI `/api/v1/docs` |
| 7 | Mailgun | ✅ | Service-kerros, jono, retry, pohjat DB:ssä, esikatselu + testilähetys superadminin UI:ssa |
| 8 | Backupit | ✅ | Päivittäinen, retention, S3-offsite (optio), palautus 2FA + safe-copy + audit |
| 9 | Settings-taulu | ✅ | `app/settings/` keskitetty service, salaiset Fernet-salattuna |
| 10 | Tietoturva | ✅ | Hashatut salasanat & API-avaimet, CSRF, Flask-Limiter, syötteen validointi, ORM, XSS-suoja, CORS, secure cookies, CSP-nonce |
| 11 | Audit-loki | ✅ | `app/audit/`, kaikki kriittiset tapahtumat (login, 2FA, API-key, asetukset, backup, sähköposti, payment, webhook, calendar, lock) |
| 12 | Monitenantti | ✅ | `organization_id` joka entityssä, backendissä tarkistus |
| 13 | Käyttöliittymä | 🟡 | Toiminnallisuus täydellinen; visuaalinen modernisointi 1–2 iteraatiota lyhyt |
| 14 | Suorituskyky | ✅ | Indeksit, sivutus, taustatyöt APScheduler, rate limit |
| 15 | Virheenkäsittely | ✅ | 400/401/403/404/429/500, JSON-envelope |
| 16 | Testit | ✅ | pytest, 80 % coverage gate (lähde: `pytest.ini` + `.coveragerc`) |
| 17 | README | ✅ | 350+ riviä, kattava |
| 18 | Env-muuttujat | ✅ | `.env.example` kaikki vaaditut + lisät dokumentoitu |
| 19 | CLI | ✅ | `create-superadmin`, `backup-create`, `backup-restore`, `rotate-api-key`, `send-test-email`, `db upgrade`, `seed-email-templates`, `seed-demo-data`, `invoices-mark-overdue`, `cleanup-expired-tokens`, `vacuum-audit-logs`, `payments-test-stripe`, `payments-test-paytrail` |
| 20 | Periaatteet | ✅ | Service-kerros routejen sijaan, oikeustarkistukset, validointi, salaisuudet env:istä, migraatiot, JSON-envelope, audit, Docker, palautus |
| 21 | Ensimmäisen version minimi | ✅ | Kaikki listatut kohdat täyttyvät |
| 22 | Hyväksymiskriteerit | ✅ | Sovellus käynnistyy yhdellä komennolla, migraatiot toimivat, superadmin CLI:llä, 2FA pakollinen, API toimii avaimella, avaimet hashattuina, Mailgun-testi, pohjat muokattavissa, päivittäinen backup, palautus, audit, testit, README |
| 23 | Yksinkertaisuus | ✅ | Modulit erotettu mutta koodi on luettavissa |

**Yhteenveto: 22/23. Ainoa osittainen kohta on §13 (UI), ja sekin koskee vain visuaalista viimeistelyä, ei toiminnallisuutta.**

---

## 3. Maksuintegraatio — nykytila täydellisesti kuvattuna

### 3.A Mitä on toteutettu (ja toimii)

**Tarjoajat:**

- **Stripe Checkout** — kansainväliset kortit (Visa, Mastercard, Amex jne.)
- **Paytrail Payment Page** — suomalaiset verkkopankit (Nordea, OP, Danske, Handelsbanken), MobilePay, kotimaiset kortit

**Arkkitehtuuri:**

- `app/payments/providers/base.py` — abstrakti `PaymentProvider`
- `app/payments/providers/stripe.py` — Stripe Checkout-sessiot, refund, webhook-parsinta
- `app/payments/providers/paytrail.py` — Paytrail HMAC-allekirjoitus (sentit kokonaislukuna), refund, query-allekirjoituksen verifiointi
- `app/payments/services.py` — `create_checkout`, `handle_webhook_event`, `refund`, `get_payment_for_org`, idempotency, refund-kokonaissummat
- `app/payments/models.py` — `Payment` (UNIQUE provider+provider_payment_id, idempotency_key, organization_id, invoice_id, reservation_id, status, currency, return/cancel_url, metadata_json) + `PaymentRefund`
- `app/payments/routes.py` — `/api/v1/payments/checkout`, `/api/v1/payments/<id>`, `/api/v1/payments/<id>/refund`
- `app/webhooks/routes.py` — `/api/v1/webhooks/stripe` (POST), `/api/v1/webhooks/paytrail` (GET)

**Vieraan maksupolku (portal):**

1. Vieras kirjautuu `/portal` (sähköposti+salasana TAI magic link sähköpostilla)
2. `/portal/invoices` näyttää avoimet laskut
3. `/portal/invoices/<id>/pay` → provider-valinta lomakkeella
4. POST → `payment_service.create_checkout(...)` (`app/portal/routes.py`)
5. Service:
   - tarkistaa tenant-isolaation (invoice.organization_id == vieraan org)
   - generoi idempotency-keyn (`checkout-{invoice.id}-{timestamp}` tai header `Idempotency-Key`)
   - luo `Payment` tilaan `pending`
   - kutsuu providerin `create_checkout(...)`-metodia
6. Provider:
   - **Stripe:** `stripe.checkout.Session.create(...)` line itemsillä (subtotal_excl_vat + vat_amount erikseen), customer_email, metadata invoice_id+organization_id, idempotency_key
   - **Paytrail:** POST `{api_base}/payments` HMAC SHA-256-allekirjoituksella, kaikki summat senteissä (`*100`)
7. Vieras ohjataan `redirect_url`:iin (Stripe Checkout / Paytrail Payment Page)
8. Vieras maksaa hostatulla sivulla → provider redirektoi `return_url` tai `cancel_url`
9. Webhook tulee taustalla:
   - **Stripe:** POST `/api/v1/webhooks/stripe` `Stripe-Signature` -headerilla → `stripe.Webhook.construct_event(...)` verifioi
   - **Paytrail:** GET `/api/v1/webhooks/paytrail` query-parametreilla (`checkout-*` + `signature`) → HMAC verifiointi
10. `payment_services.handle_webhook_event(...)`:
    - Resolvaa Payment-rivin (provider_payment_id tai provider_session_id)
    - Jos `payment.succeeded` ja status ei jo succeeded → status=`succeeded`, completed_at=now, method=card
    - `billing_service.mark_invoice_paid(...)` → Invoice.status=`paid`
    - Audit `payment.received` (SUCCESS)
    - Julkaisee outbound webhookin `invoice.paid` subscribereille
    - Lähettää `payment_received`-sähköpostin vieraalle (queue)
11. `payment.failed` ja `refund.succeeded` -tapahtumat hoidetaan vastaavasti

**Refund-flow:**

1. Admin avaa laskunäkymästä → "Hyvitä"
2. POST `/api/v1/payments/<id>/refund` body `{amount, reason}` + `Idempotency-Key`
3. `services.refund(...)`:
   - vain admin/superadmin (oikeustarkistus)
   - tenant-isolation
   - vain succeeded/partially_refunded -tilainen Payment
   - refund-summa ≤ outstanding (payment.amount − sum(succeeded refunds) − sum(pending refunds))
   - luo `PaymentRefund` tilaan `pending` + idempotency_key
   - kutsuu `provider.refund(...)`
   - audit `payment.refund_initiated`
4. Provider lähettää webhookin (Stripe `charge.refunded`, Paytrail callback) → service päättelee Payment.status:
   - 0 < refund < total → `partially_refunded`
   - refund == total → `refunded`

**Tietoturva ja PCI-DSS:**

- **PCI-DSS SAQ-A** (minimaalinen laajuus) — sovellus EI koskaan käsittele kortin numeroa, CVV:tä eikä expiryä
- API-avaimet ja webhook-secretit hashattuina/Fernet-salattuina (`webhooks.stripe.secret`, `webhooks.paytrail.secret` settings-taulussa, `is_secret=true`)
- Idempotency-suojaus sekä luonnissa että refundissa (UNIQUE-rajoitus + IntegrityError-handling)
- Webhook-allekirjoituksen verifiointi pakollinen — invalid → 401 + audit
- Audit-loki kaikilla kriittisillä tapahtumilla: `payment.checkout_created`, `payment.received`, `payment.failed`, `payment.refund_initiated`, `payment.refund_completed`, `payment.refund_failed`, `webhook.invalid_signature`, `webhook.unknown_provider`, `webhook.payload_too_large`, `webhook.invalid_payload`

**Konfiguraatio (pakolliset env-muuttujat ProductionConfigissa):**

- Stripe: `STRIPE_ENABLED=1` → vaaditaan `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY` (muuten RuntimeError startilla)
- Paytrail: `PAYTRAIL_ENABLED=1` → vaaditaan `PAYTRAIL_MERCHANT_ID`, `PAYTRAIL_SECRET_KEY`, `PAYMENT_CALLBACK_URL`
- Yhteiset: `PAYMENT_RETURN_URL`, `PAYMENT_CALLBACK_URL`

**Testitilat dokumentoitu** README:n osiossa "Maksuintegraation manuaalitesti": Stripe `4242 4242 4242 4242`, Paytrail `MERCHANT_ID=375917`, `SECRET_KEY=SAIPPUAKAUPPIAS`, Nordea Demo.

### 3.B Tarvitseeko maksuintegraatioiden eteen tehdä vielä jotain?

**Pakollisia avoimia töitä EI OLE.** Maksut toimivat tuotannossa, hyväksymiskriteerit täyttyvät, allekirjoitukset verifioidaan, refundit kirjautuvat, audit-loki on kattava, idempotency suojaa duplikaatit, PCI-DSS pidetään minimissä.

**Ammattitason puutteet (UX/operaatio, ei estä toimintaa):**

| # | Puute | Vaikutus | Työmäärä |
|---|-------|----------|----------|
| 1 | Stuck-pending payments — `pending`-tilan Payment-rivi voi jäädä roikkumaan jos vieras ei palaa eikä webhook tule (verkkokatko, providerin viive). `app/payments/scheduler.py` on **tyhjä rumpu** — ei expiry-jobia. | Likainen data, manuaalinen siivous | XS — APScheduler-job, esim. expiry 24 h jälkeen → status `expired` + audit |
| 2 | Provider-virhe checkout-luonnissa — jos `provider.create_checkout` heittää (verkko alas, väärä avain, providerin häiriö), nykyrivi 5xx ja vieras ei näe selkeää viestiä `/portal/invoices/<id>/pay`-sivulla. | UX-virhe, supportin lisätyö | XS — `try/except PaymentServiceError` portaaliin + flash-viesti |
| 3 | Maksun status-polling paluusivulla — vieras palaa `return_url`:iin mutta webhook saapuu hetkeä myöhemmin → portaalissa lasku näyttää vielä `open`, kunnes vieras lataa sivun manuaalisesti. | UX, "maksoinko vai en" -kysymys | S — JS-polling 2 s välein 30 s ajan tai server-side wait + spinner |
| 4 | Partial refund -UI — service tukee partial-refundia (osittainen `payment_amount`), mutta admin-UI ei näytä erottelua "hyvitettävissä jäljellä X €" eikä mahdollista osittaisen summan syöttämistä. | Operaatio-puute, joudutaan SQL:llä | S — admin-laskunäkymään input + "outstanding"-laskenta |
| 5 | Refund-failure retry — jos providerin refund epäonnistuu (esim. Stripe palauttaa `failed`), refund jää `failed`-tilaan eikä admin näe selkeää "yritä uudelleen" -nappia. | Operaatio-puute | S — admin-action `retry-refund` + uusi PaymentRefund samasta original-paymentista |
| 6 | Stripe-webhook async-fallback — pitkät käsittelyt (>4.5 s) palautetaan jo 200 OK ja jätetään processed=False, mutta dispatcher käsittelee uudelleen vasta seuraavalla synkronisella tapahtumalla, ei taustalla. Init-template §14 lupaa "raskaat tehtävät taustatyöksi". | Hidas webhook → Stripe yrittää uudelleen tarpeettomasti | S — APScheduler-job joka käsittelee `WebhookEvent.processed=False` rivit |

**Lisäksi pieniä pintapuolisia parannuksia (ei estä toimintaa):**

- `payment.checkout_session_created`-eventti outbound-webhookiin (asiakkaan integraatiolle "lasku-luotuna" -tieto)
- Kuittien PDF-arkistointi (toteutettu Prompt 7:ssä mutta ei kytketty Payment-näkymään ladattavana linkkinä)
- Email-pohja `payment_failed` (nykyisin vain queue-pohja `payment_received` automaattilähetyksessä)
- Settings-UI:hin Stripe/Paytrail-tilanäyttö ("Yhteys OK / Virhe / Pois käytöstä")
- CSV/XLSX-export `/admin/payments`-listaan (Prompt 8D:n export-mekanismi olemassa, ei kytketty)

**Yhteenveto §3.B:** Maksu-koodi on **tuotantokunnossa**, eikä init-template pakota mitään lisätyötä. Yllä luetellut 6 kohtaa ovat **ammattitasoa varten** — niitä ei ole pakko tehdä, mutta jos sovellus on kaupallisessa käytössä, ne kannattaa lisätä yksi tai kaksi kerrallaan.

---

## 4. Booking.com / Airbnb -yhteydet — nykytila

### 4.A Mitä on toteutettu

Toteutus on **vain iCal-pohjainen** — yksisuuntainen + read-only export.

**Komponentit:**

- `app/integrations/ical/client.py` — HTTP-haku (timeout, virheenkäsittely)
- `app/integrations/ical/adapter.py` — ICS-parsinta (`icalendar`-paketti) → `{uid, summary, start_date, end_date}`
- `app/integrations/ical/service.py` — kolme operaatiota:
  - `export_unit_calendar(unit_id)` — generoi yksikön varauksista ICS-feedin (Booking/Airbnb voi lukea)
  - `create_feed(...)` — superadmin/admin lisää tuontisyötteen (Airbnb/Booking ICS-URL)
  - `sync_all_feeds(...)` — APScheduler ajaa, hakee syötteet, tallentaa `ImportedCalendarEvent`-rivit
  - `detect_conflicts(...)` — tarkistaa onko sama yksikkö varattu sekä sisäisesti (`Reservation`) että ulkoisesti (`ImportedCalendarEvent`)
- `app/integrations/ical/scheduler.py` — APScheduler IntervalTrigger (oletus 15 min, `ICAL_SYNC_INTERVAL_MINUTES`)
- `app/integrations/ical/models.py` — `ImportedCalendarFeed` (yksikkökohtainen URL) + `ImportedCalendarEvent` (parsittu data)
- HMAC-allekirjoitettu URL omalle export-feedille (`ICAL_FEED_SECRET`) — Booking/Airbnb ei pääse muiden tenantien dataan

**Käyttötapaus joka toimii nyt:**

1. Asiakas lisää `https://www.airbnb.com/calendar/ical/...ics` syötteen yksikölle X
2. APScheduler hakee 15 min välein
3. Pindora-kalenterissa näkyy "Airbnb-varaus 2026-06-01 → 2026-06-05"
4. Jos sama jakso on varattu sisäisesti → konfliktivaroitus audit-lokissa (`calendar.conflict_detected`)
5. Asiakas voi julkaista oman `Reservation`-feedin Booking-Airbnb:lle URL:ssa `/api/v1/units/<id>/calendar.ics?token=<hmac>`

**Audit-tapahtumat:** `calendar.imported`, `calendar.conflict_detected`

### 4.B Mitä booking/airbnb-puolelta puuttuu

**Tämä on aito PMS-puute.** iCal on monitorointi, ei kanavasynkki.

| Vaatimus | iCal nyt | Aito channel manager |
|----------|----------|----------------------|
| Varauksen tuonti | ✅ (luku) | ✅ (push) |
| Varauksen vienti | ⚠️ (ICS-feed-tasolla, ei push) | ✅ |
| Hinnan synkronointi (rate sync) | ❌ | ✅ |
| Saatavuuden synkronointi (instant) | ❌ (15 min viive) | ✅ |
| Peruutuksen havaitseminen | ❌ (epäluotettava) | ✅ |
| Overbooking-suoja | ❌ | ✅ |
| Booking-numeron mappaus | ❌ | ✅ |
| Channel-spesifit kentät (Airbnb-notes, vieraan ID) | ❌ | ✅ |
| Vieraan maksu kanavan kautta vs. pos | manuaalinen | automaattinen |

**Riskiskenaariot nykyisellä iCal-toteutuksella:**

1. **"Vieras varaa Airbnb:n kautta"** → Airbnb päivittää ICS:n → Pindora hakee 15 min sisällä → varaus näkyy. **OK, mutta 15 min ikkuna jossa joku voi tehdä päällekkäisvarauksen.**
2. **"Vieras peruuttaa Booking.com:ssa"** → Booking poistaa eventin ICS:stä → Pindora ei aina huomaa muutosta luotettavasti (riippuu siitä lähettääkö Booking eventin uudelleen vai poistaako sen feedistä). **Riski: peruttu varaus jää järjestelmään.**
3. **"Asiakas päivittää hinnan"** → muutos pitää tehdä **erikseen jokaisessa kanavassa manuaalisesti**. Pindora ei pysty pushaamaan hintaa Booking/Airbnb:lle.
4. **"Saman yksikön samalle viikolle tulee varaus sekä Airbnb:stä että Booking.com:sta 14 min sisällä"** → molemmat kanavat näyttävät yksikön vapaana → overbooking. iCal ei suojaa tältä.

**Valmiit ratkaisuvaihtoehdot:**

(a) **Suorat integraatiot Booking.com Connectivity API + Airbnb Channel API** — vaatii sertifikaatin Booking.comilta (~6 kk hakemus + auditointi), Airbnb hyväksyy yleensä nopeammin mutta vaatii myös API-pääsyhakemuksen. **Työläin polku, mutta ilmaisin pitkällä aikavälillä.**

(b) **Välipalvelu (channel manager middleware)**:
- **Channex** (Hostaway/Lodgify-tyyppinen) — yksi REST-API joka avautuu Bookingiin, Airbnb:hin, Vrbo:hon. Kustannus tyypillisesti 30–80 €/kohde/kk.
- **Hostaway** — vahva PMS-tason kilpailija, mutta heillä on myös pelkkä connector-API.
- **Lodgify** — vastaava.
- **Etu:** yksi integraatio, monta kanavaa, sertifikaatit valmiina.
- **Haitta:** kuukausimaksu skaalautuu kohdemäärän mukaan.

(c) **Hybridi**: aloita iCal:lla, lisää Booking.com Connectivity API ensin (suurin kanava), Airbnb myöhemmin → tämä on käytännössä nopein "markkina-kelpoisuus" -polku jos asiakas tähtää Suomen B&B-markkinaan.

**Asiakaskysymyksiä ennen päätöstä:**

1. Mitkä kanavat ensisijaisia? (Booking, Airbnb, Vrbo, Expedia, suorat?)
2. Suora-integraatio vai välipalvelu? (sertifikaatti vs. kuukausimaksu)
3. Real-time push vai 15 min polling?
4. Keskitetty hinnoittelu (master Pindorassa) vai per-channel?
5. Budjetti välipalvelulle (jos valittu): 30–100 €/kohde/kk × kohdemäärä

---

## 5. Punch list: kaikki muu mitä tarvitaan aitoon PMS:ään

Seuraava lista on koottu nykyisestä koodista, AUDIT_FULL_v2.md:stä, init-templaten vaatimuksista ja PMS-toimialan käytännöistä. Prioriteetit: **K**=kriittinen, **Y**=ylempi, **A**=alempi.

### 5.A Toiminnalliset puutteet

| # | Ominaisuus | Prioriteetti | Työmäärä | Huomio |
|---|-----------|--------------|----------|--------|
| 1 | **Channel manager (Booking.com + Airbnb push)** | K | XL | Ks. §4.B — vaatii asiakkaan päätöksen integraattorista |
| 2 | **Hinnoittelusäännöt** (sesonki, viikonloppu, min/max nights, vähimmäisyöt) | K | L | Suunnittelussa CHATGPT_PROMPTS_VISUAL_PRO.md:ssa kohtana 8G, ei vielä toteutettu |
| 3 | **Ennakkomaksu (deposit) maksuflowiin** | Y | M | Esim. 30 % varauksen yhteydessä, loput X päivää ennen check-iniä; Stripe + Paytrail tukevat tätä Payment Intentilla / kahdella checkoutilla |
| 4 | **Kuvagalleria kohteille** | Y | M | Vaatii object storagen (S3/R2/Backblaze) — AWS S3-tuki on jo `BACKUP_S3_*` env:eissä, samaa rakennetta voi kierrättää |
| 5 | **Vieraskommunikaatio-automaatio** (check-in-ohjeet, check-out-muistutus, palautekysely) | Y | M | Email-pohjat olemassa, tarvitaan trigger-pohjaiset jobit (varaukseen kytketty) |
| 6 | **Monikielisyys (i18n)** — fi/en/sv | Y | L | Suomen markkina vaatii ainakin fi+en. Flask-Babel + `_("...")` -kierrätys templateissa |
| 7 | **Saavutettavuus (a11y) — WCAG 2.1 AA** | Y | M | EU-vaatimus (Saavutettavuusdirektiivi); aria-labelit, kontrastit, keyboard nav |
| 8 | **GDPR-export-formaatit (PDF + CSV erikseen)** | Y | S | `app/gdpr/` olemassa, lisättävä formaatti-valinta |
| 9 | **RFQ — yhteyspyyntö-lomake vieraille** (lead generation) | A | S | Julkinen "kysy lisätietoja" -lomake → notification owner:lle |
| 10 | **Asiakaspalvelu / chat-integraatio** | A | S | Tawk.to (ilmainen) tai Intercom (maksullinen) — pelkkä JS-snippet |
| 11 | **Booking-lähde-tilastot** (mistä kanavasta varaus tuli, conversion rate) | A | M | Reservation.source-kenttä + report-näkymä; tarvitaan vasta channel managerin yhteydessä |
| 12 | **Owner statements** (omistajan kuukausiraportti — bruttotulot, palkkiot, netot) | Y | M | `app/owner_portal/` runko olemassa, raporttien generointi puuttuu |
| 13 | **Varauksen muutos-/peruutuskäsittely vieraan portaalissa** (eikä vain admin-UI:ssa) | Y | S | Liiketoimintasäännöt: peruutusehto, refund-laskenta |

### 5.B Maksuintegraation viimeistely (toistettu §3.B:stä)

14. Pending-payment expiry-job (XS)
15. Provider-virhe → vieraan portaaliin selkeä viesti (XS)
16. Maksun status-polling return-sivulla (S)
17. Partial refund -UI admin-paneeliin (S)
18. Refund-retry-painike (S)
19. Outbound async webhook-handler taustatyönä (S)

### 5.C UI/UX-modernisointi (init-template §13 — ainoa osittainen)

20. **Visuaalinen viimeistely** — design-järjestelmä on lisätty Prompt 8A:lla, mutta kokonaisilme kaipaa 1–2 iteraatiota (typografia, spacing, värimaailma, dashboard-graafien viimeistely)
21. **Mobile-first responsiviinen admin-näkymä** (vieraan portaali on jo OK)

### 5.D Tekninen velka / siivous

22. **Käyttämättömien moduulien siivous tai dokumentointi**:
    - `app/subscriptions/` — ei selkeää routea/UI:ta
    - `app/status/` — pääosin debug-näkymä
    - `app/owner_portal/` — owner-roolinen portaali, käyttötarkoitus epäselvä
    - **Toimenpide:** kukin moduuli (a) dokumentoidaan READMEhen tai (b) poistetaan migraatiolla
23. **Yksi TODO-kommentti**: `app/admin/routes.py:122` — "If a safe, explicit superadmin cross-tenant override is introduced". Joko poista kommentti tai luo issue.
24. **Duplikoituva tenant-tarkistus**: monessa route-tiedostossa toistuu `if entity.organization_id != current_user.organization_id: abort(403)`. Ekstrahoi `@require_tenant_access(model)` -dekoraattori `app/core/decorators.py`:hin.
25. **Pindora-lukon endpoint-pathit on placeholderia** (`app/integrations/pindora_lock/client.py`: kommentit "Placeholder endpoint path; replace once vendor docs are confirmed"). Vahvista vendor-dokumentaatiosta.
26. **Coverage-gate 80 % vs. todellinen 77.5 %** (CURSOR_PROMPT_PAYMENTS_HARDEN.md:n mukaan). Tarkista nykytila ja paikkaa puuttuvat haarat (`pytest --cov=app --cov-report=term-missing`).

### 5.E Operatiiviset/compliance-asiat

27. **Lainmukainen majoituslainsäädäntö Suomessa**:
    - Vieraan rekisteröinti (poliisille) — kotimaisten ja ulkomaisten majoittujien tiedot. Onko tämä tarpeellinen? Riippuu liiketoimintamuodosta.
    - ALV-erittely laskussa — Invoice-mallissa on `vat_rate` ja `vat_amount`, OK.
28. **Kuvitellut vakiokäytännöt**: cancellation policy, house rules, deposit/security deposit -tekstit per-yksikkö.
29. **Sentry on jo wired up** mutta DSN:t pitää asettaa tuotannossa (`SENTRY_DSN`, `SENTRY_TRACES_SAMPLE_RATE` env:issä).
30. **Backup-recovery-harjoitus** — tee aito palautusharjoitus tuotanto-kopiosta kerran kvartaalissa (init-template §22 hyväksymiskriteeri kattaa toiminnallisuuden, ei harjoituksen).

---

## 6. Suositeltu toteutusjärjestys

Vaiheistus suosittelee aloittamaan pienestä:

**Vaihe 1 (1–2 viikkoa, kustannus pieni, riski pieni)**
- Tekninen velka (kohdat 22–26)
- Maksuintegraation viimeistely §3.B / 5.B (kohdat 14–19) — kaikki XS/S
- §13 UI-viimeistely 1 iteraatio

**Vaihe 2 (2–3 viikkoa)**
- Hinnoittelusäännöt (kohta 2)
- i18n fi+en (kohta 6)
- Saavutettavuus a11y (kohta 7)
- Owner statements (kohta 12)
- GDPR-export-formaatit (kohta 8)

**Vaihe 3 (vaatii asiakkaan päätöksen, 4–8 viikkoa)**
- Channel manager (kohta 1) — joko suorat integraatiot tai välipalvelu
- Ennakkomaksu (kohta 3) — kun channel manager on selvä, jotta deposit-säännöt voidaan synkata kanaviin

**Vaihe 4 (ulkonäön ja markkinoinnin viimeistely)**
- Kuvagalleria + object storage (kohta 4)
- Vieraskommunikaatio-automaatio (kohta 5)
- Booking-lähde-tilastot (kohta 11)
- RFQ + chat (kohdat 9, 10)

---

## 7. Mitä asiakkaalta on hyvä kysyä ennen seuraavaa työtä

1. **Channel manager**: suora-integraatio (Booking.com Connectivity API + Airbnb Channel API) vai välipalvelu (Channex, Hostaway, Lodgify)? Budjetti välipalvelulle 30–100 €/kohde/kk.
2. **Aktiiviset kanavat**: Booking, Airbnb, Vrbo, Expedia? Jokin muu?
3. **Hinnoittelustrategia**: master Pindorassa vai per-channel?
4. **Saatavuussynkki**: real-time vai 15 min polling?
5. **Monikielisyys**: fi+en pakolliset, sv/de/ru/no/da tarpeen mukaan?
6. **Kuvagalleria-storage**: AWS S3, Cloudflare R2, Backblaze, Render-volyymi?
7. **Chat**: Tawk.to (ilmainen) vai Intercom?
8. **Ennakkomaksukäytäntö**: prosentti varauksesta, milloin loppuosa veloitetaan?
9. **Onko vieraan rekisteröinti poliisille tarpeen** (riippuu majoituspalvelumuodosta)?
10. **Sentry-tilaus on auki** — kannattaako se ottaa käyttöön tuotannossa? DSN ja sample rate.

---

## 8. Lopputulos

**Sovellus täyttää init-templaten 22/23 pykälää, hyväksymiskriteerit täyttyvät, maksut toimivat tuotannossa eikä mitään pakollista työtä ole maksuintegraation eteen jäljellä.**

**Aidoksi PMS:ksi (kaupallisesti kilpailukykyiseksi) puuttuu kuitenkin selvästi yksi iso pala: kahdensuuntainen channel manager Booking.com / Airbnb -kanaviin.** Nykyinen iCal on kelpo monitorointi mutta ei suojaa overbookingilta eikä tue hinta-/saatavuussynkkiä. Tämä on suurin yksittäinen päätös ennen seuraavia kehitysvaiheita, koska sen valinta (suora vs. välipalvelu) vaikuttaa moniin alemman tason ratkaisuihin.

Maksupuolella jäljellä on **6 ammattitason hiomista** (UX ja operaatio), ei pakollisia töitä. Muuten työlistan kärki on hinnoittelusäännöt → i18n → a11y → channel manager.

---

*Selvitys laadittu repon tilanteesta 6.5.2026. Lähteet: `app/`-koodit, `README.md`, `.env.example`, `AUDIT_FULL_v2.md`, `CHATGPT_PROMPT_9_PAYMENTS.md`, `CURSOR_PROMPT_PAYMENTS_HARDEN.md`, `CHATGPT_PROMPTS_VISUAL_PRO.md`.*
