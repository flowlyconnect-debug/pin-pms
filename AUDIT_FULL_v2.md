# Pindora PMS — Täysauditointi v2 (Promptit 1–9 valmiina)

**Päivämäärä:** 5.5.2026
**Tilanne:** Render-deploy onnistui, sovellus tuotannossa.

## Lyhyesti — yhteenveto

| Alue | Tila |
|------|------|
| Init-template noudatus (23 pykälää) | 22/23 ✅ — vain §13 (UI-modernisointi) on osittain |
| Maksuintegraatio (Stripe + Paytrail) | Toimii, pieniä UX-puutteita |
| iCal-tuonti | Toimii (yksisuuntainen) |
| Booking.com / Airbnb -kahdensuuntainen sync | **Puuttuu kokonaan** |
| Hyväksymiskriteerit §22 | Täyttyvät |
| Audit-loki | Kattava |
| GDPR | Toteutettu, voi laajentaa export-formaatteja |

---

## A. Mikä toimii ja täyttää init-templatea

**Kaikki ydinpykälät täyttyvät:**

- §1 Tekniikkapino — Flask + Gunicorn + Nginx + PostgreSQL + SQLAlchemy + Alembic + APScheduler + Sentry
- §2 Moduulirakenne — auth, admin, api, users, email, backups, core + lisämoduulit
- §3 Roolit — `UserRole` enum (SUPERADMIN, ADMIN, USER, API_CLIENT)
- §4 Auth — login, password reset, session, API key, 2FA superadminille
- §5 2FA — TOTP + varakoodit
- §6 API — `/api/v1`, Bearer + X-API-Key, hashatut, scopes, JSON-rakenne
- §7 Mailgun — service-kerros, queue, retry, pohjat tietokannassa
- §8 Backupit — päivittäinen, palautus 2FA + audit
- §9 Settings-taulu — keskitetty service, salaisten arvojen maskaus
- §10 Tietoturva — CSRF, rate-limit, validointi, ORM, XSS, CORS, cookies, CSP-nonce
- §11 Audit-loki — kaikki kriittiset tapahtumat
- §12 Multi-tenant — `organization_id` joka entityssä
- §14 Suorituskyky — APScheduler taustatyöt
- §15 Virheet — 400/401/403/404/429/500
- §16 Testit — pytest, 80 % coverage gate
- §17 README + .env.example — kattavat
- §18 Env-muuttujat — kaikki dokumentoidut
- §19 CLI-komennot — create-superadmin, backup-create/restore, rotate-api-key, send-test-email, db upgrade, jne.
- §20 Service-kerros — routet ohuet, logiikka servicessä
- §21 Ensimmäisen version minimivaatimus — täyttyy
- §22 Hyväksymiskriteerit — täyttyvät
- §23 Yksinkertaisuus — pidetty

§13 (UI) on osittain valmis: design-järjestelmä lisätty Prompt 8A:lla, mutta visuaalinen modernisointi voisi viedä vielä 1-2 iteraatiota.

---

## B. Miten maksut toimivat sisäisesti

**Vieraan polku:**

1. Vieras kirjautuu vieras-portaaliin → `/portal/invoices` näyttää laskut
2. Klikkaa "Maksa" laskussa → `/portal/invoices/<id>/pay`
3. Sivu näyttää provider-valinnan: Stripe (kortit) tai Paytrail (kotim. verkkopankit, MobilePay)
4. Klikkaus → POST `/api/v1/payments/checkout` (JSON: invoice_id, provider, return_url, cancel_url)
5. `app/payments/services.py:create_checkout()`:
   - Tarkistaa invoice.organization_id == vieraan org (tenant-isolation)
   - Generoi idempotency-key (`f"checkout-{invoice.id}-{int(time.time())}"`)
   - Luo Payment-rivin tilaan "pending"
   - Kutsuu `provider.create_checkout(...)`
6. Provider:
   - **Stripe:** `stripe.checkout.Session.create()` — line items VAT-erittelyllä (subtotal_excl_vat, vat_amount)
   - **Paytrail:** `POST /payments` HMAC-allekirjoituksella (sentit kokonaislukuna, ei euroja)
7. Palautus: `{redirect_url}` joka avaa hostatun maksusivun
8. Vieras maksaa
9. Provider redirektoi `return_url` (success) tai `cancel_url` (cancel)
10. Pindora näyttää kuitin (Prompt 7:n PDF-service liitteenä) ja kiitos-sivun

**Webhook-flow:**

1. **Stripe:** POST `/api/v1/webhooks/stripe`
   - Header: `Stripe-Signature` (HMAC SHA-256 key=STRIPE_WEBHOOK_SECRET)
   - `stripe.Webhook.construct_event(payload, sig_header, secret)`
2. **Paytrail:** GET `/api/v1/webhooks/paytrail` (Paytrail käyttää GET-callbackia!)
   - Query-parametrit sisältävät kaikki `checkout-*`-arvot + `signature`
   - HMAC lasketaan headers + body samalla algoritmilla kuin lähetyksissä
3. Allekirjoitus OK → `payment_services.handle_webhook_event()`:
   - Idempotency-tarkistus (Prompt 7B): jos sama provider_payment_id käsitelty → no-op
   - Päivittää Payment.status normalized_event.type-arvon mukaan
   - Jos succeeded:
     - Status="succeeded", completed_at=now()
     - `mark_invoice_paid()` → Invoice.status="paid"
     - Audit: `payment.received`
     - Sähköposti `payment_received` (queue, retry-suojattu Prompt 7G:llä)
     - Webhook publisher julkaisee `invoice.paid` -eventin asiakas-subscribereille (Prompt 7F)
     - Generoi PDF-kuitti (Prompt 7) liitteenä
4. Allekirjoitus epäonnistuu → 401 + audit FAILURE (`webhook.invalid_signature`)

**Refund-flow:**

1. Admin avaa `/admin/invoices/<id>` → "Hyvitä"-painike (vain succeeded-tilan maksuille)
2. POST `/api/v1/payments/<payment_id>/refund` (body: amount, reason)
3. `services.refund()`:
   - Permission: vain admin/superadmin
   - Tenant-isolation
   - Luo PaymentRefund tilaan "pending"
   - Kutsuu `provider.refund(...)`
4. Provider lähettää charge.refunded webhookin asynkronisesti
5. Webhook tulee → PaymentRefund.status="succeeded", invoice updates
6. Audit: `payment.refund_initiated` → `payment.refund_completed`

**Mitä EI vielä toimi (edge cases):**

- Partial refund -UI (admin voi tehdä tietokannassa, mutta UI ei näytä erottelua)
- Payment-status polling vieraan paluusivulla (manuaalinen reload tarvitaan)
- Provider-virhe checkout-luonnissa: ei selkeää käyttäjälle näkyvää virhesanomaa
- Refund-failure retry: jos provider palauttaa virheen, admin ei voi auto-retrytä UI:sta

**PCI-DSS:**

Käytössä **vain hostatut maksulomakkeet** (Stripe Checkout, Paytrail Payment Page). Kortin numeroita, CVV:tä tai expiryjä **ei koskaan** tallenneta tietokantaan. Tämä pitää PCI-DSS-laajuuden minimissä (SAQ-A).

---

## C. iCal / Airbnb / Booking.com — nykytila

**Toteutettu:**

1. **iCal-tuonti** (`app/integrations/ical/service.py`)
   - Käyttäjä lisää iCal-feed-URL:n yksikkö-kohtaisesti
   - APScheduler hakee feedin säännöllisesti (`ICAL_SYNC_INTERVAL_MINUTES`)
   - Parsii ICS, luo `Reservation`-rivit ImportedCalendarEvent-tagilla

2. **iCal-vienti** (`export_unit_calendar()`)
   - Generoi yksikön varaukset ICS-muodossa
   - Julkaistaan `/api/v1/units/<id>/calendar.ics?token=<signed>` (read-only)
   - Booking.com / Airbnb voivat lukea tätä feedinä

3. **Synkronointi-aikataulu** APScheduler

**Mitä PUUTTUU kahdensuuntaisesta channel managerista:**

Tämä on **iso aukko PMS:n näkökulmasta**. Pelkkä iCal on read-only -synkronointi joka ei tue:

| Vaatimus | iCal nyt | Channel manager |
|----------|----------|-----------------|
| Varauksen tuonti | ✅ (luku) | ✅ |
| Varauksen vienti | ⚠️ (vain ICS-feed-tasolla) | ✅ |
| Hinnan synkronointi | ❌ | ✅ |
| Saatavuuden synkronointi (instant) | ❌ (15 min viive) | ✅ |
| Peruutuksen havaitseminen | ❌ | ✅ |
| Ylikirjautumisen esto | ❌ | ✅ |
| Booking-numeron mappaus | ❌ | ✅ |
| Channel-spesifit kentät (Airbnb-notes) | ❌ | ✅ |

**Käyttötapaus-esimerkit:**

1. **"Vieras varaa Airbnb:n kautta"** → Airbnb päivittää oman iCal-feedin → Pindora hakee 15 min sisällä → varaus näkyy Pindora-kalenterissa (vain luku)
2. **"Vieras peruuttaa Booking.com:ssa"** → Booking.com poistaa eventin feedistä → Pindora ei välttämättä huomaa (riippuu siitä kummitteleeko event yhä) → **ristiriita**
3. **"Käyttäjä luo varauksen Pindora:ssa"** → varaus tulee export-feediin → Booking/Airbnb voivat lukea, mutta päivittävät vain jos käytetään external feed-pollingia

Käytännössä PMS toimii **monitorointityökaluna** ulkoisille kanaville, ei aitona channel managerina. Tämän korjaaminen vaatii joko:
- (a) Booking.com Connectivity API + Airbnb Channel API -integraatiot suoraan (työläs, kalliit, sertifikaattivaatimukset), tai
- (b) Välipalvelun käyttö (Channex, Hostaway, Lodgify) joka tarjoaa yhden API:n josta kanavat avautuvat

---

## D. Mitä siivotaan koodista

Pieniä huomautuksia (eivät rikko mitään):

1. **`app/admin/routes.py` rivi 122 — TODO-kommentti**
   - Sisältö: "TODO: If a safe, explicit superadmin cross-tenant override is introduced"
   - Korjaus: poista tai muuta dokumentoiduksi feature-issuella
2. **Käyttämättömät moduulit (mahdolliset)**
   - `app/subscriptions/` — listattuna mutta ei selkeää routea/UI:ta
   - `app/status/` — pääosin debug-näkymä
   - `app/owner_portal/` — owner-roolinen portaali, käyttö epäselvä
   - **Toimenpide:** käy ne läpi ja joko (a) dokumentoi niiden käyttö READMEsta tai (b) poista jos ei käytössä
3. **Duplikoituva tenant-tarkistus**
   - Useissa route-tiedostoissa toistuu `if entity.organization_id != current_user.organization_id: abort(403)`
   - **Toimenpide:** ekstrahoi `@require_tenant_access(model)` -dekoraattori `app/core/decorators.py`:hin
4. **localStorage-käyttö (jos jokin moduuli sitä käyttää)**
   - Tarkista grepillä: `Grep -r "localStorage\|sessionStorage" app/static/`
   - Init-template ei suoranaisesti kiellä, mutta turvallisin on käyttää http-only-cookieja käyttäjäkohtaisille mieltymyksille

---

## E. Mitä lisätään ammattitasoa varten

13 puutetta. Jaan ne seuraavasti:

**Suunnitelmissa (CHATGPT_PROMPTS_VISUAL_PRO.md, EI vielä toteutettu):**

- 8A: Design-järjestelmä — osittain tehty
- 8B: Dashboard-paranteet (KPI, mini-graafit) — tehty?
- 8C: UI-helpers (toast, dialogit) — tehty
- 8D: Haku, filtterit, bulk-actions — tehty
- 8E: Notification center — tehty
- 8F: Tagit + kommentit — tehty
- 8G: Hinnoittelusäännöt — **ei vielä tehty**

**Vielä tarvitaan UUSI prompti:**

| # | Ominaisuus | Prioriteetti |
|---|-----------|--------------|
| 1 | **Channel manager kahdensuuntainen** (Channex- tai vastaava integraatio) | Kriittinen ammattitasolle |
| 2 | **Vieraskommunikaatio-automaatio** (check-in/out reminders, feedback survey) | Korkea |
| 3 | **Monikielisyys (i18n)** — fi/en/sv | Korkea (Suomen markkina) |
| 4 | **Saavutettavuus (a11y) — WCAG 2.1 AA** | EU-vaatimus |
| 5 | **Kuvagalleria kohteille** | Vieraan kannalta tärkeä |
| 6 | **Ennakkomaksu (deposit) maksu-flowiin** | Revenue-turva |
| 7 | **GDPR-export-formaatit (PDF, CSV)** | Compliance |
| 8 | **RFQ — yhteyspyynnöt vieraille** | Lead generation |
| 9 | **Asiakaspalvelu / chat-integraatio** | UX |
| 10 | **Hinnoittelusäännöt (Prompt 8G)** | Revenue optimization |
| 11 | **Yöpyä-rajoitukset (min/max nights)** | Sisältyy 8G:hen |
| 12 | **Booking-lähde-tilastot** | Sisältyy 8B:hen |
| 13 | **Koodin siivous** (todo-kommentit, käyttämättömät moduulit, duplikaattilogiikka) | Tekninen velka |

---

## F. Suositeltu järjestys

1. **Koodin siivous + Prompt 8G (hinnoittelu)** — pienempi työ, korjaa siisteyttä
2. **Channel manager (8H)** — iso ja kriittinen, mutta vaatii asiakkaan päätöksen integraattorista
3. **i18n (8I)** — keskikokoinen, parantaa myyntiä Pohjoismaihin
4. **Saavutettavuus (8J)** — oikeudellinen vaatimus
5. **Vieraskommunikaatio (8K)** — UX-parannus
6. **Kuvagalleria (8L)** — vaatii object storagea (S3 / vastaava)

---

## G. Mitä asiakkaalta kysytään

Ennen channel manager -työn aloittamista:

1. **Kanavavalinta:** Käytetäänkö (a) suoraa Booking.com Connectivity API + Airbnb API -integraatioita, vai (b) välipalvelua (Channex, Hostaway, Lodgify, jne.)? Suora-integraatio vaatii sertifikaatin Booking.comilta (~6 kk hakemus + auditointi).

2. **Aktiiviset kanavat:** Mitä kanavia asiakas käyttää nyt? (Booking.com, Airbnb, Vrbo, suorat varaukset)

3. **Hinnoittelu-strategia:** Haluaako keskitetyn hinnoittelun (Pindora master) vai per-channel-hintapäivityksen?

4. **Saatavuus:** Real-time-synkronointi (vaatii instant push) vai 15 min polling-malli?

5. **Booking.com Connectivity API -kustannus:** suora-integraatio voi olla ilmainen, mutta välipalvelut maksavat ~30-100 €/kohde/kk

Ennen muiden promptien aloittamista:

6. **Monikielisyys:** Mitkä kielet ensin? (fi, en, sv, de, ru, no, da)
7. **Kuvagalleria:** Object storage — Render-volyymi, S3, R2, Backblaze?
8. **Chat-integraatio:** Mikä työkalu? (Tawk.to ilmainen, Intercom maksullinen)
