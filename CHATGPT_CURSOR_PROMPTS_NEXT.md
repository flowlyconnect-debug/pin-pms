# Promptit seuraavaan kehitysvaiheeseen — ChatGPT-rikastus + Cursor-toteutus

**Päivämäärä:** 6.5.2026
**Tausta:** Selvitys `SELVITYS_PMS_TILA_2026-05-06.md` listasi 30 työkohtaa. Tässä tiedostossa nämä on ryhmitelty 9 toteutuspakkaukseen prioriteetin ja loogisen yhteyden mukaan.

## Käyttöohje

Jokainen pakkaus on rakennettu kahdella tavalla käytettäväksi:

**Vaihtoehto A — ChatGPT-rikastus → Cursor**
1. Liitä koko pakkauksen sisältö ChatGPT:lle (otsikon alta loppuun saakka, koodilohkot mukaan lukien)
2. Muistuta tarvittaessa Prompt 0:n (init-template) säännöistä jos keskustelu on vaihtunut
3. Pyydä ChatGPT:tä palauttamaan rikastettu, valmis Cursor-prompti samassa rakenteessa
4. Liitä ChatGPT:n vastaus Cursoriin

**Vaihtoehto B — Suoraan Cursoriin**
- Liitä **vain sisempi koodilohko** (`Tehtävä Cursorille: ...`) suoraan Cursoriin

Suositus: **käytä A-vaihtoehtoa kun pakkaus on iso (L/XL)** ja **B-vaihtoehtoa kun pakkaus on pieni (XS/S)**. Iso pakkaus hyötyy ChatGPT:n tarkennuksesta (file-pathit, edge cases, testit), pieni ei vaadi sitä.

## Pakkausten yhteiset säännöt (Prompt 0 -muistutus)

Kaikki Cursor-promptit noudattavat init-templaten 23 pykälää:

- §1 Tekniikkapino: Flask + PostgreSQL + SQLAlchemy + Alembic + APScheduler
- §2 Service-kerros: routet ohuet, logiikka serviceen
- §3 Roolit + §4 Auth + §5 2FA superadminille
- §6 API: `/api/v1/*`, JSON-envelope `{success, data, error}`
- §10 Tietoturva: hashaus, CSRF, rate limit, validointi, ORM, XSS, CORS
- §11 Audit-loki kaikilla kriittisillä tapahtumilla
- §12 Multi-tenant: `organization_id` joka entityssä
- §16 Testit: pytest, coverage gate 80 %
- §18 Env-muuttujat dokumentoidaan `.env.example`:hin
- §20 Migraatiot Alembicilla, ei suoria DDL-muutoksia
- §22 Hyväksymiskriteerit: testit läpi, README päivittyy

**Ei kovakoodattuja salaisuuksia.** **Ei UI-only-rajoituksia** — backend tarkistaa aina.

---

## Pakkauspolku (suositusjärjestys)

| # | Pakkaus | Prio | Työmäärä | ChatGPT-rikastus suositus |
|---|---------|------|----------|---------------------------|
| 1 | Tekninen velka + maksu-viimeistely | K | M (yhdistetty) | Ei pakollinen |
| 2 | Hinnoittelusäännöt (8G) | K | L | Suositeltu |
| 3 | Channel manager (8H) | K | XL | **Pakollinen** |
| 4 | Ennakkomaksu + vieraan peruutus | Y | M | Suositeltu |
| 5 | Monikielisyys i18n (8I) | Y | L | Suositeltu |
| 6 | Saavutettavuus a11y (8J) | Y | M | Suositeltu |
| 7 | Vieraskommunikaatio-automaatio (8K) | Y | M | Suositeltu |
| 8 | Kuvagalleria + owner statements (8L) | Y | M | Suositeltu |
| 9 | Pikaviimeistelyt: GDPR-export, RFQ, chat, booking-lähteet, UI-polish | A | M | Ei pakollinen |

---

# Pakkaus 1 — Tekninen velka + maksu-viimeistely

**Ryhmä:** §3.B / §5.B / §5.D selvityksestä — kaikki yhteen ajoon, koska XS/S-luokan tehtäviä jotka eivät vaadi suunnittelua.

> Liitä ChatGPT:lle TAI suoraan Cursoriin. Sisältää 11 pientä tehtävää.

```
Tehtävä Cursorille: Aja tekninen velka pois ja viimeistele maksuintegraation UX/operaatio-puutteet.

Tausta: Sovelluksen runko on tuotantokunnossa (init-template 22/23). Maksut toimivat (Stripe + Paytrail) mutta UX/operaatio-puutteita on. Lisäksi pieniä siivouksia.

Init-template noudatus on pakollinen (§3, §10, §11, §12, §16, §20). Service-kerros, audit-loki, oikeustarkistus, tenant-isolation, ei kovakoodattuja salaisuuksia.

Vaihe 1 — Maksuintegraation viimeistely

a) Pending-payment expiry-job
- Lisää APScheduler-job tiedostoon app/payments/scheduler.py (nyt tyhjä)
- Job ajaa kerran tunnissa: kaikki Payment.status="pending" jotka ovat luotu yli 24 h sitten → status="expired", audit "payment.expired", commit
- Env: PAYMENT_PENDING_EXPIRY_HOURS=24, PAYMENT_EXPIRY_SCHEDULER_ENABLED=1
- Rekisteröi job init_scheduler-funktiossa kuten muut ajastimet
- Testi: tests/test_payments_expiry.py — luo pending Payment 25 h vanha, aja job, varmista status="expired" + audit-rivi

b) Provider-virhe portaalin paluuviestinä
- app/portal/routes.py pay_invoice POST: jos payment_service.PaymentServiceError nostetaan, käytä flash("...") + render_template uudelleen sen sijaan että 5xx
- Mappaa err.code → suomenkielinen viesti: provider_disabled="Maksuyhteys on tilapäisesti pois käytöstä, yritä uudelleen myöhemmin", validation_error="Tarkista syöttämäsi tiedot", forbidden="Et voi maksaa tätä laskua", muu="Maksun aloitus epäonnistui, yritä uudelleen"

c) Maksun status-polling paluusivulla
- app/portal/routes.py payment_return: lisää JS-polling joka hakee 2 s välein 30 s ajan /api/v1/payments/<id> ja päivittää tilan
- Käytä olemassa olevaa /api/v1/payments/<id>-endpointia; lisää portal-spesifi /portal/payments/<id>/status (vain oma tenant) jos halutaan välttää API-key-vaatimus
- Näytä "Vahvistetaan maksua…" -spinner kunnes status="succeeded"

d) Partial refund -UI admin-paneeliin
- app/templates/admin/invoices/detail.html: lisää refund-lomake jossa "Outstanding: X €" + amount-input
- Outstanding-laskenta: Payment.amount − sum(succeeded refunds) − sum(pending refunds) — käytä payments.services._refund_totals
- Validointi backendissä on jo paikoillaan, lisää vain UI-input
- Lisää testi: tests/test_admin_payments_refund_ui.py — partial refund 30 €, sitten toinen 20 €, varmista status="partially_refunded"

e) Refund-retry-painike
- Failed-tilaiselle PaymentRefundille admin-action POST /admin/invoices/<id>/refunds/<refund_id>/retry
- Service: app/payments/services.py uusi funktio retry_refund(refund_id, actor_user_id) — luo uusi PaymentRefund samasta payment_idstä samalla amount + reason, status="pending", actor_user_id=actor
- Audit: payment.refund_retried

f) Outbound async webhook-handler taustatyönä
- app/webhooks/scheduler.py on jo olemassa (WEBHOOK_DELIVERY_SCHEDULER_ENABLED) outbound-deliverylle
- Lisää uusi job inbound-eventeille jotka jäivät processed=False (timeout >4.5s tai poikkeus)
- Job: hae kaikki WebhookEvent.processed=False joiden created_at < now-30s, dispatch_handler(provider, event, payload), mark_processed
- Yritä korkeintaan 5 kertaa, sen jälkeen audit "webhook.handler_dead_letter"

Vaihe 2 — Tekninen velka

g) TODO-kommentti
- app/admin/routes.py:122 sisältää "TODO: If a safe, explicit superadmin cross-tenant override is introduced"
- Joko poista kommentti kokonaan tai muuta GitHub-issueksi (lisää linkki kommenttiin)

h) Duplikoituva tenant-tarkistus → dekoraattori
- Etsi grepillä: `entity\.organization_id != current_user\.organization_id`
- Ekstrahoi app/core/decorators.py uusi dekoraattori @require_tenant_access(model_class, id_param="id")
- Dekoraattori: lataa rivin id_param-perusteella, tarkistaa organization_id, abort(404) jos ei vastaa, lisää g.scoped_entity
- Korvaa duplikaattikoodi vähintään 5 routessa joista löytyy

i) Käyttämättömät moduulit
- Tutki: app/subscriptions/, app/status/, app/owner_portal/
- Jokaisesta:
  - jos käytössä → lisää lyhyt "## Tarkoitus" -osio README:hin (alle "Application purpose")
  - jos ei käytössä → poista, päivitä app/__init__.py blueprint-rekisteröinti, luo migraatio drop_unused_tables
- Älä poista app/owner_portal/ ennen kuin tarkistettu — se voi olla tarpeen Pakkaus 8:n owner statements -ominaisuudelle

j) Pindora-lukon placeholder-pathit
- app/integrations/pindora_lock/client.py: rivien 32 ja 47 kommentit "Placeholder endpoint path; replace once vendor docs are confirmed"
- Tarkista vendor-dokumentaatio, korjaa endpoint-pathit oikeiksi
- Jos vendor-dokumentaatiota ei ole saatavilla, jätä kommentit mutta merkitse RuntimeError("Pindora lock vendor endpoints not yet finalized") ja palaa myöhemmin

k) Coverage-gate vahvistus
- Aja: pytest --cov=app --cov-report=term-missing --cov-fail-under=80
- Jos alle 80 %, lisää testejä huonoimmin katettuihin tiedostoihin (todennäköisesti app/payments/services.py, app/webhooks/services.py)
- Tavoite: vihreä build, gate ≥ 80 %

Hyväksymiskriteerit:
- pytest -v --cov=app --cov-fail-under=80 → vihreä
- Pending Payment vanhenee 24 h jälkeen automaattisesti
- Provider-virhe näkyy portaalissa selkeänä viestinä, ei 500-sivuna
- Partial refund toimii admin-UI:sta osasummalla
- Refund-retry luo uuden PaymentRefund-rivin
- Tenant-tarkistus tehty dekoraattorilla vähintään 5 routessa
- README päivitetty käyttämättömien moduulien osalta
- Audit-loki sisältää uudet tapahtumatyypit: payment.expired, payment.refund_retried, webhook.handler_dead_letter
```

---

# Pakkaus 2 — Hinnoittelusäännöt (Prompt 8G)

**Tausta:** Suunniteltu CHATGPT_PROMPTS_VISUAL_PRO.md:ssa kohtana 8G, ei vielä toteutettu. Kriittinen channel managerin (Pakkaus 3) edellytys, koska hinnat synkataan kanaviin master-arvoista.

> Liitä ChatGPT:lle ensin (rikastus suositeltu), sitten Cursoriin.

```
Tehtävä Cursorille: Toteuta hinnoittelusäännöt yksiköille (Prompt 8G).

Tausta: Pin PMS:llä on Unit-malli (app/properties/models.py) ja Reservation-malli (app/reservations/models.py), mutta varauksen hinta on tällä hetkellä manuaalisesti syötettävä. Ammattitason PMS vaatii dynaamisen hinnoittelun: perushinta + sesonki + viikonloppu + minimi-/maksimi-yöt + last-minute / early-bird -muutokset.

Init-template §11 (audit), §12 (tenant-isolation), §16 (testit), §20 (Alembic) noudatettava.

Vaihe 1 — Tietomalli (uusi migraatio)

Lisää app/properties/models.py:
- UnitBasePrice: id, unit_id (FK), currency (default EUR), base_price_per_night (Numeric 10,2), valid_from (Date, nullable), valid_until (Date, nullable), is_active, organization_id, timestamps
- UnitPricingRule: id, unit_id, name, rule_type (enum: seasonal, weekday, weekend, last_minute, early_bird, length_of_stay, custom), priority (int, lower=more specific), date_from, date_until, weekday_mask (string '1234567' bitsetti), nights_min, nights_max, days_before_checkin_min/max, adjustment_type (percent/fixed), adjustment_value (Decimal), is_active, organization_id, timestamps
- UnitStayConstraint: id, unit_id, min_nights, max_nights, no_arrival_weekdays (string), no_departure_weekdays (string), valid_from, valid_until, organization_id

Lisää db.Index unit_id-perusteella jokaisessa.

Vaihe 2 — Service-kerros

Luo app/properties/pricing.py:
- calculate_quote(unit_id, start_date, end_date, organization_id) → dict { base_total, applied_rules: [...], stay_constraint_violations: [...], final_total, currency, nights }
  - Hae UnitBasePrice voimassa
  - Iteroi yöt, päätä per-yö-hinta:
    - Lähtöhinta = base
    - Käy UnitPricingRule:t (priority asc.) ja sovita
    - Sovella adjustments (percent ennen fixed)
  - Tarkista StayConstraint (min/max nights, ei saapumis-/lähtöpäiviä)
- list_rules(unit_id, organization_id) — admin
- preview(unit_id, start_date, end_date) — vieras / portaalin "näytä hinta"

Tenant-isolation: kaikki kyselyt suodattavat organization_id:n.

Vaihe 3 — Reservation-kytkentä

app/reservations/services.py create_reservation:
- Jos pyyntö ei sisällä expliitti hintaa, kutsu pricing.calculate_quote()
- Tallenna lopullinen total_price + applied_rules_json (JSON-sarake) Reservation-malliin (uusi sarake migraatiossa)
- Hylkää varaus jos stay_constraint_violations ei tyhjä → 400 + selvä virheviesti

Vaihe 4 — Admin-UI

app/templates/admin/units/<unit_id>/pricing.html:
- "Perushinta" -lohko (UnitBasePrice CRUD)
- "Säännöt" -taulukko (UnitPricingRule CRUD), drag-and-drop priority
- "Oleskelusäännöt" (UnitStayConstraint CRUD)
- "Hintatesti" -lomake: anna pvm-väli, näytä laskenta yö yöltä

Routet: app/admin/routes.py uusi blueprint pricing tai jatka properties-blueprintia.

Vaihe 5 — API

GET /api/v1/units/<id>/pricing/quote?start=YYYY-MM-DD&end=YYYY-MM-DD
- API-key required, scope pricing:read
- JSON-envelope: { success, data: { nights, base_total, final_total, applied_rules: [...], constraint_violations: [...] }, error }

POST /api/v1/units/<id>/pricing/rules
- scope pricing:write
- Audit: pricing.rule_created / pricing.rule_updated / pricing.rule_deleted

Vaihe 6 — Vieraan portaali

app/templates/portal/units/<id>.html:
- "Tarkista hinta" -lomake (start, end → AJAX hae quote)
- Näytä erittely (perushinta + sesonki + alennus)

Vaihe 7 — Testit

tests/test_pricing.py:
- Perushinta yhdellä yöllä
- Viikonloppu-sääntö (lauantai-yö +20 %)
- Sesonki-sääntö (kesä +50 %)
- Last-minute (3 vrk ennen check-iniä, -15 %)
- Stay-constraint min_nights=3, varaus 2 yötä → constraint_violations
- Tenant-isolation (toisen organisaation sääntö ei vaikuta)
- Useita sääntöjä yhtä aikaa (priority)

Vaihe 8 — README

Lisää README:hin osio "Hinnoittelusäännöt" — selitä rule_typet, priority-järjestys, env-muuttujat (jos uusia, kuten PRICING_DEFAULT_CURRENCY).

Hyväksymiskriteerit:
- Migraatio ajaa puhtaasti
- Hintatesti admin-UI:sta laskee oikean lopputuloksen useimmissa testitapauksissa
- API quote palauttaa erittelyn ja constraint-violations
- Reservationin hinta lasketaan automaattisesti jos ei annettu
- pytest --cov=app uusi koodi 90 %+ katettu
```

---

# Pakkaus 3 — Channel manager (Prompt 8H)

**Tausta:** Selvityksen §4.B kriittinen aukko. Vaatii asiakkaan päätöksen integraattorista (suora vs. välipalvelu) ennen kuin Cursor voi aloittaa.

> **PAKOLLINEN ChatGPT-rikastus** — tämä prompti vaatii asiakkaan vastaukset ennen kuin Cursorille viedään. ChatGPT:llä rikastus = käy kysymykset läpi, valitse polku, päätä valmis Cursor-prompti.

```
Tehtävä ChatGPT:lle: Rikasta seuraava channel manager -prompti Cursoria varten.

Asiakaskysymykset jotka pitää saada vastattua ennen Cursor-toteutusta:

1. Polku: (a) suorat integraatiot Booking.com Connectivity API + Airbnb Channel API vai (b) välipalvelu (Channex / Hostaway / Lodgify)?
2. Aktiiviset kanavat: Booking, Airbnb, Vrbo, Expedia, joku muu?
3. Hinnoittelustrategia: master Pindorassa (push) vai per-channel (pull)?
4. Saatavuussynkki: real-time push vai 15 min polling?
5. Budjetti välipalvelulle: 30–100 €/kohde/kk × kohdemäärä?

Valitse vastausten perusteella yksi seuraavista poluista ja palauta valmis Cursor-prompti:

POLKU A — Booking.com Connectivity API + Airbnb Channel API (suora):
- Vaatii sertifikaatin (Booking.com ~6 kk hakemus + auditointi, Airbnb nopeampi)
- ChatGPT: kuvaile sertifikaattiprosessi + sandbox-tunnukset
- Cursor: implementoi app/integrations/booking_com/ ja app/integrations/airbnb/ (client + adapter + service + scheduler)

POLKU B — Channex (välipalvelu):
- Yksi REST-API kaikille kanaville
- ChatGPT: kuvaile Channex-sandbox + auth (api-key)
- Cursor: implementoi app/integrations/channex/ (client + adapter + service + scheduler)

POLKU C — Hostaway / Lodgify (välipalvelu):
- Vastaava kuin Channex, eri tarjoaja
- Cursor: implementoi app/integrations/<provider>/

YHTEISET VAATIMUKSET (kaikki polut):

Init-template §3 (roolit), §11 (audit), §12 (tenant), §16 (testit), §20 (migraatiot) noudatettava.

Vaihe 1 — Tietomalli
- ChannelMapping: id, organization_id, unit_id, channel_provider (enum), external_listing_id, external_room_id, is_active, last_synced_at, last_error
- ChannelReservation: id, organization_id, unit_id, channel_provider, external_reservation_id, external_status, external_currency, external_total, internal_reservation_id (FK Reservation), raw_payload (JSON), created_at, updated_at
- Migraatio Alembicilla, indexit external_id + (provider, external_reservation_id) UNIQUE

Vaihe 2 — Provider-abstraktio
- app/integrations/channels/base.py: ChannelProvider abstrakti luokka
- create_listing, update_availability, update_rates, fetch_reservations, ack_reservation
- Konkreetit toteutukset polun valinnan mukaan

Vaihe 3 — Synkki-suuntiin
- AVAILABILITY_PUSH: kun Pindora-Reservation luotu/päivitetty/peruttu → push channelille (heti, ei polling)
- RATE_PUSH: kun UnitPricingRule muuttuu → push hinnat 365 päivää eteenpäin
- RESERVATION_PULL: kanavan webhook tai 5 min polling → uusi varaus → luo Reservation Pindoraan, link ChannelReservation
- Overbooking-suoja: ennen RESERVATION_PULL Reservationin luontia tarkista onko sama unit jo varattu (lukko, db.session.with_for_update())

Vaihe 4 — Webhook-vastaanotto (jos provider tukee)
- /api/v1/webhooks/<channel_provider>
- HMAC-allekirjoitus app/webhooks/services.py:n kautta (kuten Stripe/Paytrail)
- Käytä idempotency_key=external_reservation_id

Vaihe 5 — Admin-UI
- /admin/channels: listaa ChannelMappings, "Kytke uusi" -nappi → pyytää external_listing_id
- /admin/channels/<id>: synkki-historia, manuaalinen "Force resync" -nappi
- /admin/reservations: ChannelReservation-rivit eroteltu omalla badgella (Airbnb / Booking)

Vaihe 6 — Testit
- tests/test_channel_<provider>.py: mock provider-API, varmista push/pull, idempotency, overbooking-suoja, audit-lokit
- Coverage uudessa koodissa 80 %+

Vaihe 7 — README + .env.example
- Env: <PROVIDER>_API_BASE, <PROVIDER>_API_KEY, <PROVIDER>_WEBHOOK_SECRET, CHANNEL_SYNC_ENABLED, CHANNEL_POLL_INTERVAL_SECONDS
- README-osio "Channel manager" — kytkentä, sandbox, prod-käyttö

Hyväksymiskriteerit:
- Reservation Pindorassa → näkyy kanavalla 30 s sisällä (push)
- Varaus kanavalta → tulee Pindoraan webhookilla / 5 min pollingilla
- Overbooking estetty samanaikaisuustestissä
- ChannelMappings hallittavissa admin-UI:sta
- pytest läpi, README + .env.example päivitetty
```

---

# Pakkaus 4 — Ennakkomaksu (deposit) + vieraan peruutus

**Tausta:** Stripe Payment Intent + Paytrail tukevat split-paymenteja. Vieraan portaali tarvitsee myös peruutus/muutos-toiminnon (selvityksen kohta 13).

> Liitä ChatGPT:lle rikastusta varten, sitten Cursoriin.

```
Tehtävä Cursorille: Lisää ennakkomaksu maksuflow-ketjuun ja vieraan portaalin peruutustoiminto.

Tausta: Pin PMS:n maksu-flow on yksiosainen (Invoice → Stripe/Paytrail → maksettu). Tarvitaan kahdenosainen ennakkomaksu: 30 % varauksen yhteydessä, loput X päivää ennen check-iniä. Lisäksi vieraan portaali tarvitsee "Peruuta varaus" -toiminnon peruutusehdon mukaisella refund-laskennalla.

Init-template §3, §10, §11, §12, §16 noudatettava.

Vaihe 1 — Tietomalli (migraatio)

Lisää Reservation-malliin:
- deposit_percent (Numeric 5,2, default 0.00, esim. 30.00 = 30 %)
- deposit_due_at (DateTime, kun ennakko pitää maksaa)
- balance_due_at (DateTime, kun loppuosa pitää maksaa, esim. 14 vrk ennen check-iniä)
- cancellation_policy (enum: flexible, moderate, strict)

Lisää Invoice-malliin:
- invoice_kind (enum: regular, deposit, balance) — oletus regular
- parent_reservation_id (FK reservations) jo olemassa, ei muutosta

Vaihe 2 — Service-laajennus

app/billing/services.py:
- create_deposit_invoice(reservation_id, organization_id, percent) → Invoice (kind=deposit, total = reservation.total * percent / 100)
- create_balance_invoice(reservation_id, organization_id) → Invoice (kind=balance, total = reservation.total - sum(deposit invoices))
- Aikataulutus APSchedulerilla:
  - daily-job tarkistaa: jos Reservation.balance_due_at < now ja balance-Invoice ei vielä luotu → create_balance_invoice + lähetä payment_due-sähköposti

Vaihe 3 — Vieraan portaalin peruutusflow

app/portal/services.py:
- cancel_reservation(reservation_id, guest_id, organization_id) → dict { refund_amount, policy_applied }
  - Lataa Reservation, tarkista guest_id == reservation.guest_id (multi-tenant)
  - Laske refund cancellation_policy:n mukaan:
    - flexible: 100 % refund jos > 24 h ennen check-iniä, muuten 0 %
    - moderate: 50 % refund jos > 5 vrk ennen check-iniä, muuten 0 %
    - strict: 0 % refund alle 7 vrk ennen check-iniä, 50 % jos > 7 vrk
  - Aseta Reservation.status="cancelled"
  - Jos refund_amount > 0:
    - Hae viimeisin succeeded Payment reservationille
    - Kutsu payments.services.refund(payment.id, refund_amount, "Vieraan peruutus", actor_user_id=guest_id (?))
    - HUOM: refund-service vaatii admin/superadmin actorin → vaihtoehtoisesti luo system-user "portal_refund_robot" tai löysää validointi (cancellation_policy = system-perusteinen)
  - Audit: reservation.cancelled_by_guest, metadata { refund_amount, policy_applied }
  - Lähetä reservation_cancelled-sähköposti vieraalle ja owner-notification adminille

Vaihe 4 — Vieraan portaalin UI

app/templates/portal/reservation_detail.html:
- Lisää "Peruuta varaus" -nappi (vain ennen check-iniä)
- Klikkaus → näytä peruutusehto + "Saat refundin X € (Y % varauksesta)" -laskenta
- "Vahvista peruutus" -nappi → POST /portal/reservations/<id>/cancel
- Näytä success-flash + redirect listaan

Vaihe 5 — Admin-UI

app/templates/admin/reservations/detail.html:
- Lisää "Peruutusehto" -dropdown (flexible/moderate/strict)
- Lisää "Ennakkomaksu %" -syöte (default 30)
- Lisää "Loppuosan eräpäivä" -input (default 14 vrk ennen check-iniä)
- Näytä Reservationin alaosassa kaikki kytketyt Invoicet ja niiden tila

Vaihe 6 — Sähköpostit

Uudet pohjat (seed app/email/templates.py kautta):
- deposit_invoice_created — "Ennakkomaksu X €, eräpäivä Y, [Maksa-linkki]"
- balance_invoice_created — "Loppuosa X €, eräpäivä Y, [Maksa-linkki]"
- payment_due — "Maksu erääntyy Y vrk:n kuluttua"
- reservation_cancelled — "Varauksesi peruttu, refund X € palautetaan 5–10 arkipäivän kuluessa"

Vaihe 7 — Testit

tests/test_deposit_flow.py:
- Reservation luotu deposit_percent=30 → deposit-Invoice luodaan automaattisesti, total = 0.30 * reservation.total
- Daily-job luo balance-Invoicen kun balance_due_at saavutettu
- Sum(deposit + balance) == reservation.total

tests/test_cancellation.py:
- flexible-policy + > 24 h ennen → 100 % refund
- moderate-policy + 4 vrk ennen → 0 %
- strict-policy + 8 vrk ennen → 50 %
- audit-rivi reservation.cancelled_by_guest sisältää policy + refund_amount

Hyväksymiskriteerit:
- Migraatio ajaa
- Vieras voi peruuttaa varauksen portaalista, refund kirjautuu Payment-historiaan
- Ennakkomaksu-Invoice luodaan reservationin yhteydessä, balance-Invoice automaattisesti eräpäivän mukaan
- Sähköpostit toimivat jokaisessa flow-vaiheessa
- pytest läpi
```

---

# Pakkaus 5 — Monikielisyys i18n (Prompt 8I)

> Liitä ChatGPT:lle, sitten Cursoriin.

```
Tehtävä Cursorille: Toteuta i18n suomi + englanti (sv myöhemmin valmiina avata).

Tausta: Pin PMS:n template-tekstit ovat suomeksi. Vientiin tarvitaan en, ja jossain vaiheessa sv. Mutkattomin polku Flaskissa: Flask-Babel + .po-tiedostot.

Init-template §16 (testit), §17 (README), §18 (.env.example) noudatettava.

Vaihe 1 — Riippuvuudet
- requirements.txt: + Flask-Babel
- requirements-dev.txt: + Babel (compile-msgcat)

Vaihe 2 — Konfiguraatio
- app/extensions.py: babel = Babel()
- app/__init__.py: babel.init_app(app, locale_selector=resolve_locale)
- resolve_locale: katso 1) URL ?lang= 2) g.user.preferred_language 3) Accept-Language header 4) default fi
- app/config.py: BABEL_DEFAULT_LOCALE = "fi", BABEL_SUPPORTED_LOCALES = ["fi", "en"], BABEL_TRANSLATION_DIRECTORIES = "translations"

Vaihe 3 — Käännösextraktio
- babel.cfg projektin juureen
- Aja: pybabel extract -F babel.cfg -k _l -o messages.pot .
- pybabel init -i messages.pot -d translations -l fi
- pybabel init -i messages.pot -d translations -l en

Vaihe 4 — Templatet
- Wrap kaikki staattinen teksti app/templates/**/*.html: {% trans %}Teksti{% endtrans %} TAI {{ _("Teksti") }}
- Käy kaikki templates läpi, älä unohda emaileja (app/email/templates.py)
- Python-koodissa flash, error-viestit: from flask_babel import lazy_gettext as _l, korvaa string-literaaleja

Vaihe 5 — Käännösten täyttö
- Aja pybabel update -i messages.pot -d translations
- Täytä translations/en/LC_MESSAGES/messages.po — jokainen msgstr
- Täytä translations/fi/LC_MESSAGES/messages.po — kopio msgid:stä (tai paranna)
- Aja pybabel compile -d translations

Vaihe 6 — Käyttäjän kielivalinta
- User-malliin uusi sarake preferred_language (string(8), default fi)
- Migraatio
- Profiilisivu (/profile tai /admin/users/<id>): kielivalinta dropdown

Vaihe 7 — URL-pohjainen kielenvaihto
- /<lang>/?... -prefix vaihtoehtoinen — ei pakollinen, mutta paranna SEO:ta
- Yksinkertaisin: ?lang=en query-parametrina vaihtaa session["locale"]:n

Vaihe 8 — Sähköpostipohjat
- Email-mallia laajennetaan: locale-sarake, jokaisesta pohjasta versio per locale
- Templates-seedeissä lisätään en-versiot (käännetään käsin)

Vaihe 9 — Testit
- tests/test_i18n.py: GET /?lang=en → "Login" näkyy, GET /?lang=fi → "Kirjaudu" näkyy
- Käännös ladattu oikein flash-viesteille
- Sähköpostipohja löytyy locale=en ja sisällössä "Welcome", locale=fi sisällössä "Tervetuloa"

Vaihe 10 — README + .env.example
- README "Monikielisyys" -osio: pybabel-komennot, kielen lisäys
- .env.example: BABEL_DEFAULT_LOCALE=fi (jos halutaan ohittaa)

Hyväksymiskriteerit:
- Sovellus näkyy fi ja en
- Käyttäjäprofiilissa kielivalinta säilyy
- Sähköpostit menevät käyttäjän kielellä
- Sv-locale lisättävissä yhdellä komennolla (pybabel init -l sv) ilman kooditätä
- pytest läpi
```

---

# Pakkaus 6 — Saavutettavuus a11y WCAG 2.1 AA (Prompt 8J)

> Liitä ChatGPT:lle, sitten Cursoriin.

```
Tehtävä Cursorille: Vie sovellus WCAG 2.1 AA -tasolle (EU:n saavutettavuusdirektiivi).

Tausta: Pin PMS:n UI on tällä hetkellä toiminnallinen mutta ei tarkistettu saavutettavuusvaatimuksia vasten. Saavutettavuusdirektiivi (EU 2016/2102 + Suomen laki digitaalisten palvelujen tarjoamisesta) edellyttää WCAG 2.1 AA -tasoa julkisissa palveluissa ja tietyissä yksityisissä palveluissa.

Vaihe 1 — Auditointi
- Aja: npm i -g axe-cli; axe http://localhost:5000/ (pyydä asiakkaalta lupa asentaa)
- Aja: npx pa11y http://localhost:5000/admin/...
- Listaa kaikki AA-tason rikkomukset

Vaihe 2 — Korjaukset templates/

a) Sememanttinen HTML
- Korvaa <div onclick> → <button>
- Käytä <nav>, <main>, <header>, <footer>, <aside>, <section>
- Otsikkohierarkia: yksi <h1> per sivu, ei hyppyjä h2 → h4

b) Aria-attribuutit
- aria-label kaikilla nappuloilla joiden teksti puuttuu (esim. ikoninapit)
- aria-required, aria-invalid lomakekenttiin
- role="alert" flash-viestien containeriin
- aria-live="polite" notification-toasteille
- aria-expanded dropdown-toggleihin
- aria-current="page" aktiiviseen nav-linkkiin

c) Kontrasti
- Tarkista kaikki teksti-tausta-yhdistelmät minimi 4.5:1 (normaaliteksti) tai 3:1 (>18pt / 14pt bold)
- Käytä työkalua https://contrast-ratio.com/

d) Fokus
- Kaikilla interaktiivisilla elementeillä näkyvä focus-rengas (outline 2px solid color)
- Tab-järjestys looginen
- Skip-link "Hyppää sisältöön" header-osioon (näkyy fokuksessa)

e) Lomakkeet
- Kaikilla input-kentillä <label for="..."> tai aria-labelledby
- Virhetiedotteet kentän yhteydessä, ei pelkkä punainen reuna
- aria-describedby kentässä virheilmoituksiin

f) Kuvat ja kuvakkeet
- alt-attribuutit (tyhjä alt="" jos koristekuva)
- SVG-ikoneilla aria-hidden="true" jos vieressä on tekstiä
- title ei riitä — käytä aria-label

Vaihe 3 — Keyboard navigation
- Modaalit: Trap fokus dialogin sisään, Esc sulkee, kohdistus takaisin avanneeseen elementtiin
- Datepicker-komponentti pitää olla nuolinäppäimillä käytettävissä
- Bulk-action-checkboxit Space-näppäimellä

Vaihe 4 — Screen reader -tuki
- Testaa NVDA (Windows) / VoiceOver (Mac):lla pääflowt:
  - Kirjautuminen
  - Reservation-listan selaaminen
  - Reservationin luonti
  - Maksun aloitus portaalissa

Vaihe 5 — Saavutettavuusseloste
- Pakollinen Suomen lain mukaan
- Lisää /accessibility-sivu, content tulee templateta WCAG-tason raportointivaatimuksesta
- Linkki footeriin

Vaihe 6 — CI-integraatio
- .github/workflows/ci.yml: lisää axe / pa11y -ajo (pakolliset päätason sivut)
- Vihreä build vain jos AA-tason rikkomukset = 0

Vaihe 7 — Testit
- tests/test_a11y.py: lataa kaikki templatet axe-corella, varmista 0 violations

Hyväksymiskriteerit:
- axe + pa11y AA-tasolla 0 violations päätason sivuilla
- Saavutettavuusseloste julkinen
- CI failaa jos uusia AA-rikkomuksia
- Manuaalinen NVDA-tarkistus dokumentoitu docs/a11y-test.md
```

---

# Pakkaus 7 — Vieraskommunikaatio-automaatio (Prompt 8K)

> Liitä ChatGPT:lle, sitten Cursoriin.

```
Tehtävä Cursorille: Lisää automaattinen vieraskommunikaatio (check-in/out, palautekysely).

Tausta: Pin PMS:llä on jo email-pohja-järjestelmä (app/email/) ja queue + scheduler. Ammattitason PMS lähettää automaattisesti:
- Booking confirmation (heti varauksen jälkeen) — jo olemassa?
- Pre-arrival -ohjeet (3 vrk ennen) — uutta
- Check-in instructions (saapumispäivänä klo 8) — uutta
- Welcome message (check-inin jälkeen) — uutta
- Check-out reminder (lähtöpäivänä klo 9) — uutta
- Post-stay feedback (1 vrk lähdön jälkeen) — uutta
- Review request (3 vrk lähdön jälkeen) — uutta

Init-template §7 (Mailgun), §11 (audit), §16 (testit) noudatettava.

Vaihe 1 — Tietomalli (migraatio)

Reservation-malliin:
- communication_settings (JSON, default {}) — per-reservation override
- check_in_time (Time, default 16:00)
- check_out_time (Time, default 11:00)

Uusi taulu ScheduledGuestEmail:
- id, organization_id, reservation_id, template_key, scheduled_at, sent_at, status (pending/sent/failed), last_error, idempotency_key UNIQUE
- Indexit: scheduled_at, status, reservation_id

Vaihe 2 — Sähköpostipohjat

Seed app/email/templates.py:
- guest_pre_arrival
- guest_checkin_instructions (key-code, address, parking, wifi)
- guest_welcome
- guest_checkout_reminder
- guest_feedback
- guest_review_request

Jokaisessa pohjassa muuttujat: {{ guest_name }}, {{ unit_name }}, {{ check_in_date }}, {{ check_out_date }}, {{ pin_code }}, {{ wifi_name }}, {{ wifi_password }}, {{ host_name }}, {{ host_phone }}.

Vaihe 3 — Service-kerros

app/notifications/guest_communication.py:
- schedule_for_reservation(reservation_id, organization_id) → list[ScheduledGuestEmail]
  - Laske ajankohdat:
    - pre_arrival: check_in_date − 3 vrk klo 10:00
    - checkin_instructions: check_in_date klo 08:00
    - welcome: check_in_date check_in_time + 2 h
    - checkout_reminder: check_out_date klo 09:00
    - feedback: check_out_date + 1 vrk klo 18:00
    - review_request: check_out_date + 3 vrk klo 12:00
  - Tallenna ScheduledGuestEmail-rivit tilaan pending
- cancel_for_reservation(reservation_id) — kun varaus peruttu

Vaihe 4 — Scheduler

app/notifications/scheduler.py uusi job (5 min välein):
- Hae ScheduledGuestEmail.status="pending" AND scheduled_at <= now
- Jokaiselle: kutsu email_service.send_template(template_key, to=guest.email, context={...})
- Jos onnistuu → status="sent", sent_at=now
- Jos epäonnistuu → status="failed", last_error, retry max 3 kertaa
- Audit: notification.guest_email_sent / notification.guest_email_failed

Vaihe 5 — Triggerit

app/reservations/services.py:
- create_reservation: kutsu schedule_for_reservation
- update_reservation (jos check_in_date muuttuu): cancel_for_reservation + schedule_for_reservation uudestaan
- cancel_reservation: cancel_for_reservation

Vaihe 6 — Admin-UI

/admin/reservations/<id>:
- Lisää alaosaan "Vieraskommunikaatio" -lohko jossa listataan ScheduledGuestEmail-rivit
- "Lähetä uudelleen" -nappi failed-rivein vieressä
- "Peruuta lähetys" -nappi pending-riveille

/admin/email-templates: olemassa oleva sivu — lisää uudet pohjat dropdowniin

Vaihe 7 — Vieraan portaali

app/templates/portal/reservation_detail.html:
- Näytä "Saapumisohjeet lähetetään X vrk ennen check-iniä" -info
- Linkki "Pyydä uudelleen check-in-ohjeet" jos pohjia on jo lähetetty

Vaihe 8 — Testit

tests/test_guest_communication.py:
- create_reservation luo 6 ScheduledGuestEmail-riviä oikeilla aikaleimoilla
- Scheduler ajaa, lähettää sähköpostit, status="sent"
- cancel_reservation poistaa pending-rivit
- Kuukauden kuluttua scheduler ei lähetä uudestaan (idempotency)

Hyväksymiskriteerit:
- Reservation luonti → 6 ajastettua sähköpostia
- Sähköpostit menevät oikeisiin aikoihin (Mailgun-mokattuna testissä)
- Admin näkee historian + voi peruuttaa/uudelleenlähettää
- pytest läpi
```

---

# Pakkaus 8 — Kuvagalleria + Owner statements (Prompt 8L)

> Liitä ChatGPT:lle, sitten Cursoriin.

```
Tehtävä Cursorille: Lisää kuvagalleria yksiköille (object storage) ja omistajan kuukausiraportit.

Tausta: Vieraan portaalissa pitää näkyä yksikön kuvat. Omistajalla pitää olla kuukausiraportti (gross income, palkkiot, net) /owner_portal-puolella.

Init-template §10 (tietoturva — uploadit), §11 (audit), §12 (tenant), §16 (testit) noudatettava.

OSA A — Kuvagalleria

Vaihe 1 — Storage
- Käytä BACKUP_S3_* -muuttujien mallin mukaista konfiguraatiota mutta omilla muuttujillaan:
  - MEDIA_S3_ENABLED, MEDIA_S3_ENDPOINT_URL, MEDIA_S3_BUCKET, MEDIA_S3_ACCESS_KEY, MEDIA_S3_SECRET_KEY, MEDIA_S3_PREFIX
- Vaihtoehto local: MEDIA_LOCAL_DIR (jos S3 disabled)

Vaihe 2 — Tietomalli (migraatio)
- UnitImage: id, organization_id, unit_id, storage_key (s3 key tai local path), original_filename, content_type, byte_size, width, height, sort_order, is_cover, alt_text, created_at, uploaded_by_user_id

Vaihe 3 — Service
- app/properties/media.py:
  - upload_image(unit_id, organization_id, file_bytes, content_type, filename, uploaded_by) — validoi MIME (vain image/jpeg, image/png, image/webp), max 10 MB, generoi UUID-storage-key, lataa S3:lle tai lokaaliin tallennukseen, generoi thumbnail (PIL: 800x600 ja 200x150)
  - list_images(unit_id, organization_id) — admin
  - public_url(image_id, organization_id) — short-lived signed URL S3:lle TAI staattinen reitti lokaaliin
  - delete_image(image_id, organization_id, actor_user_id) — audit unit_image.deleted

Vaihe 4 — Admin-UI
- /admin/units/<id>/images — drag-drop upload, sort järjestys, "Aseta kansikuvaksi", alt-tekstit, poisto

Vaihe 5 — Vieraan portaali
- /portal/units/<id>: kuvagalleria (lightbox-tyyppinen, esim. <dialog>-pohjainen tai vanilla JS)

Vaihe 6 — Testit
- tests/test_unit_images.py: upload OK, suuri tiedosto reject (413), väärä MIME reject, multi-tenant ei voi nähdä toisen org:n kuvia
- Mock boto3 motolla (tests-dev-deppi jo paikoillaan)

OSA B — Owner statements

Vaihe 7 — Tietomalli (migraatio)
- OwnerStatement: id, organization_id, owner_id (FK Users), period_start, period_end, gross_income, fees_total, net_to_owner, currency, status (draft/issued/paid), pdf_storage_key (kun generoitu), generated_at, sent_at
- OwnerStatementLine: id, statement_id, reservation_id, gross, commission_rate, commission_amount, net

Vaihe 8 — Service
- app/owner_portal/statements.py:
  - generate_for_period(owner_id, organization_id, period_start, period_end) → OwnerStatement
  - Iteroi Reservationit jotka kuuluvat owner_id:n yksiköihin ja jotka ovat checked_out kyseisen kauden sisällä
  - Laske gross = sum(reservation.total), commission = gross * commission_rate (Owner-mallin sarake), net = gross - commission
  - Generoi PDF reportlabilla (käytä app/billing/pdf.py:n tyyliä mallina)
  - Tallenna PDF object storageen
- send_statement(statement_id, actor) — sähköposti omistajalle, audit owner.statement_sent

Vaihe 9 — Owner-portaali
- /owner_portal/statements: lista oman tilauksen kuukausiraporteista, latauslinkki PDF:lle
- /owner_portal/statements/<id>: yksityiskohdat

Vaihe 10 — Admin-UI
- /admin/owners/<id>/statements: superadmin/admin näkee kaikki, "Generoi kausi" -nappi (valitse kuukausi)
- Aikataulutettu: APScheduler ajaa kuukauden 1. päivänä klo 06:00 owners statements edellisestä kuukaudesta automaattisesti

Vaihe 11 — Testit
- tests/test_owner_statements.py: 3 reservationia, 2 owneria, varmista että jokainen statement laskee oikean summan ja sisältää vain oman ownerin reservationit

Vaihe 12 — README + .env.example
- README: "Kuvagalleria" + "Owner statements" -osiot
- .env.example: MEDIA_S3_*-muuttujat, OWNER_STATEMENTS_AUTO_GENERATE=1

Hyväksymiskriteerit:
- Yksikölle voi ladata kuvia, ne näkyvät vieraan portaalissa, järjestys ja kansikuva toimivat
- Owner-statementit generoituvat kuukausittain automaattisesti
- PDF näyttää oikean erittelyn
- pytest --cov=app läpi
```

---

# Pakkaus 9 — Pikaviimeistelyt: GDPR-export, RFQ, chat, booking-lähteet, UI-polish

**Tausta:** Pieniä alemman prioriteetin parannuksia yhdellä iteraatiolla. Voi viedä joko kerralla Cursoriin tai pilkkoa.

> Voit liittää suoraan Cursoriin (B-vaihtoehto) — pakkaus on jo riittävän pieni eikä vaadi rikastusta.

```
Tehtävä Cursorille: Viimeistele alemman prioriteetin parannukset yhdellä iteraatiolla.

Tausta: 5 pientä työtä jotka voi yhdistää: GDPR-export-formaatit, RFQ-yhteyspyyntölomake, chat-integraatio, booking-lähteet, UI-polish.

Init-template §11 (audit), §12 (tenant), §16 (testit) noudatettava.

Vaihe 1 — GDPR-export-formaatit

app/gdpr/services.py: olemassa oleva export tuottaa JSON. Lisää formaattivalinta:
- export_user_data(user_id, format) → format-arvot: json, csv, pdf
- CSV: yksi sarake per data-tyyppi (reservations, payments, audit), zip-paketti
- PDF: reportlab, ihmisluettava raportti
Admin-UI: /admin/users/<id>/gdpr-export → dropdown formaatille

Vaihe 2 — RFQ — yhteyspyyntölomake

Uusi blueprint app/leads/:
- LeadRequest-malli: id, organization_id, name, email, phone, message, source (string), unit_id (nullable), preferred_dates_from, preferred_dates_until, status (new/contacted/converted/lost), assignee_user_id, created_at
- Julkinen reitti: GET/POST /lead-form?unit_id=X
- POST → notify owner email + audit lead.received
- Admin: /admin/leads — lista, statuksen muutos
- ReCaptcha v3 spam-suoja (env: RECAPTCHA_SITE_KEY, RECAPTCHA_SECRET_KEY, valinnainen)

Vaihe 3 — Chat-integraatio (Tawk.to ilmainen)

- Settings-tauluun avain external.chat_widget_id (Fernet-salattu)
- Superadmin-asetussivulle "Chat-widget" -kenttä
- Layout-template: jos chat_widget_id asetettu, lisää Tawk.to embed-snippet asyncin loadilla
- Toggle env: CHAT_ENABLED=1

Vaihe 4 — Booking-lähde-tilastot

Reservation-malliin sarake: source (enum: direct, booking_com, airbnb, vrbo, other, default direct)
- Migraatio
- Reservation-luonnissa (sekä admin että channel manager) aseta source
- Admin /admin/reports: lisää kaavio "Varauslähteet" — count per source viimeisten 90 vrk:n ajalta
- Käytä Chart.js:ää (cdn-sallittu) tai ihan natiivi <progress>-pylväs

Vaihe 5 — UI-polish (init-template §13 viimeistely)

- Yhtenäistä spacing: 4/8/12/16/24/32 px -skaala app/static/css/main.css:ssä
- Typografia: yksi font-stack, 4 painokokoa (h1-h4 + body + small)
- Värit: max 6 päävärin paletti, kontrastit 4.5:1+
- Dashboardin KPI-kortit: yhtenäinen height, ikoni vasemmalle, numero suuremmaksi
- Mobile-first: tarkista admin-näkymät 375 px leveydellä, lisää responsiviiset breakpointit @media (max-width: 768px)
- Print-stylesheet laskutuotteille: piilota nav, raamit pois, korosta tärkeät rivit

Vaihe 6 — Testit ja README

- tests/test_gdpr_formats.py, tests/test_lead_request.py
- README-osiot: GDPR-formaatit, RFQ-lomake, chat-asetus, booking-lähde, UI-tyyliopas

Hyväksymiskriteerit:
- GDPR voidaan ladata 3 formaatissa
- Julkinen RFQ-lomake toimii ReCaptchan kanssa
- Chat-widget toimii kun chat_widget_id asetettu
- Source-tilasto näkyy raporteissa
- 4 pää-näkymää responsiviivisia 375 px leveydellä
- pytest --cov=app läpi
```

---

# Lisäys: Yleinen ChatGPT-rikastusprompti

Jos haluat yleisen rikastusrungon mihin tahansa Cursor-promptiin, tässä on copy-pasteable-rikastusprompti:

```
Olen rakentamassa Pin PMS -sovellusta init-templaten 23 pykälää noudattaen (Flask + PostgreSQL + SQLAlchemy + Alembic + Mailgun + APScheduler, multi-tenant organization_id:llä, 2FA superadminille, audit-loki kriittisistä toiminnoista, /api/v1-API hashatuilla avaimilla, JSON-envelope, päivittäiset backupit, 80 % coverage gate).

Alla on Cursor-prompti seuraavalle työlle. Rikasta se Cursoria varten:

1. Lisää konkreettiset tiedostopolut (esim. app/<moduuli>/<file>.py)
2. Tarkenna tietokantaschema (sarakkeet + tyypit + indeksit + UNIQUE-rajoitukset)
3. Listaa edge case -käsittely (tenant-isolation, idempotency, race conditions, validointi)
4. Listaa pakolliset audit-tapahtumat
5. Listaa pakolliset env-muuttujat ja niiden defaultit
6. Listaa testit jotka pitää lisätä (pytest-tiedostonimet + testattavat skenaariot)
7. Listaa README-päivitykset
8. Listaa hyväksymiskriteerit (mitä pitää toimia kun tehtävä on valmis)

Säilytä asiakkaan vastausviesti suomeksi. Palauta valmis Cursor-prompti samassa muodossa kuin alkuperäinen (otsikko + "Tehtävä Cursorille:" + vaiheet + hyväksymiskriteerit). ÄLÄ lisää tarinaa promptin ympärille — palauta vain päivitetty Cursor-prompti sellaisena että voin liittää sen suoraan Cursoriin.

Alla alkuperäinen prompti:

[liitä tähän pakkauksen Cursor-prompti]
```

Tämä on **universaali rikastin** — voit ottaa minkä tahansa pakkauksen Cursor-osan ja ajaa sen tämän läpi ChatGPT:llä saadaksesi paremmin täydellisen, edge-case-katetun version ennen Cursoriin viemistä.

---

## Yhteenveto

| Pakkaus | Reitti | Aika |
|---------|--------|------|
| 1 | Suoraan Cursoriin | 1–2 päivää |
| 2 | ChatGPT-rikastus → Cursor | 3–5 päivää |
| 3 | Asiakaspäätös → ChatGPT-rikastus → Cursor | 2–4 viikkoa |
| 4 | ChatGPT-rikastus → Cursor | 4–6 päivää |
| 5 | ChatGPT-rikastus → Cursor | 5–7 päivää |
| 6 | ChatGPT-rikastus → Cursor | 4–6 päivää |
| 7 | ChatGPT-rikastus → Cursor | 4–6 päivää |
| 8 | ChatGPT-rikastus → Cursor | 5–7 päivää |
| 9 | Suoraan Cursoriin | 3–4 päivää |

Suosittelen aloittamaan Pakkauksesta 1, sitten 2 (hinnoittelu) ennen Pakkausta 3 (channel manager) — channel manager hyödyntää hinnoittelusääntöjä master-arvoina.
