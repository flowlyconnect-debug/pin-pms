# Cursor-prompt: Pin PMS – ammattitason PMS:n täydennys (Lista 2)

> **Varoitus realismista:** Lista 2 on käytännössä useiden henkilötyö-
> kuukausien kokoinen kehitysprojekti, ei viikon tehtävä. Älä yritä antaa
> tätä koko prompttia Cursorille kerralla — se ei johda mihinkään
> tuotantokelpoiseen. Tämä dokumentti on **vaiheistus + per-tehtävä-
> prompt**, jossa jokainen vaihe on oma noin 1–3 viikon urakkansa.
>
> Suositeltu kulku: tee Lista 1 ensin loppuun → valitse tästä yksi vaihe
> (suositus M1) → kopioi vain sen vaiheen prompt Cursoriin → testaa
> tuotannossa pilottiasiakkaalla → seuraava vaihe.

---

## Vaiheistus ja prioriteetit

| Vaihe | Sisältö | Liiketoiminta-arvo | Riski |
|-------|---------|--------------------|-------|
| M1 | Maksaminen + laskutus tuotantoon (Stripe/Paytrail, Finvoice, kirjanpitoexport) | KRIITTINEN — ilman tätä PMS ei ole myyntikelpoinen | Keski |
| M2 | Smart lock + online check-in (Pindora-integraatio, automaattiset koodit) | KORKEA — tuotteen erottautumistekijä | Keski |
| M3 | Channel manager + iCal-synkronointi (Booking.com, Airbnb) | KORKEA — pakollinen lyhytvuokrille | Korkea |
| M4 | Operatiiviset moduulit (siivous, huolto-laajennus, lisäpalvelut) | KESKI | Matala |
| M5 | Tekninen kovettaminen (Redis/Celery, Sentry, OpenAPI, GDPR-eksportit) | KORKEA — pakollinen ennen skaalausta | Matala |
| M6 | Kanssaviestintä (SMS, two-way messaging, automaatiot) | KESKI | Matala |
| M7 | Compliance + viranomaisilmoitukset (matkustajailmoitus, ALV-raportit, DPA) | KORKEA Suomessa — vaatii lakitarkistuksen | Korkea |
| M8 | UX-loppuhionta (i18n, mobile, branding, onboarding-wizardi) | KESKI | Matala |

**Älä aloita M2–M8 ennen kuin Lista 1 on valmis ja M1 toimii pilotissa.**
Maksaminen rikkoutuu hiljaa ja kalliisti — kaikki muu rakennetaan sen päälle.

---

## Yhteiset pelisäännöt kaikille vaiheille

Lue ja noudata näitä koko Lista 2 -työn ajan. Liimaa nämä jokaisen
vaihe-promptin alkuun.

```
KOKO LISTA 2 -TYÖN PELISÄÄNNÖT:

- Lista 1 (CURSOR_PROMPT_LIST1.md) PITÄÄ olla valmis ja pytest vihreänä
  ennen kuin tämän vaiheen koodia kirjoitetaan.
- Älä riko olemassa olevaa toiminnallisuutta. pytest pysyy vihreänä.
- Kaikki uudet ulkoiset integraatiot menevät uuden moduulin alle:
  app/integrations/<vendor>/. Ei suoria HTTP-kutsuja routejen sisältä.
- Jokainen integraatio rakennetaan client + service + adapter -mallilla:
    client.py:   raaka HTTP, retry, rate limit, autentikaatio
    service.py:  liiketoimintalogiikka, audit, db-tallennus
    adapter.py:  vendor-payloadin muunnos meidän malliin (pure functions)
  Tämä mahdollistaa mockauksen testeissä ja vendorin vaihtamisen.
- Kaikki ulkoiset salaisuudet env-muuttujina, koskaan ei kovakoodattuna.
- Kaikki webhookit tarkistavat allekirjoituksen (HMAC tai vendorin
  oma menetelmä). Ei IP-pohjaista whitelistia ainoana suojana.
- Jokainen rahaa liikuttava operaatio kirjautuu audit-lokiin
  käyttäjäkontekstilla, määrällä, valuutalla ja korreloinnilla
  ulkoiseen ID:hen (Stripe charge id, pankkiviite, jne.).
- Idempotenssi: kaikki POST-kutsut, jotka liikuttavat rahaa tai
  varauksia, ottavat asiakkaalta idempotency-keyn ja palauttavat
  saman tuloksen samasta avaimesta. Tallenna avain tietokantaan.
- Webhook-vastaanottajat kirjoittavat raakapayloadin
  webhook_events-tauluun ennen prosessointia (replay-mahdollisuus).
- Jokainen integraatio dokumentoidaan: docs/integrations/<vendor>.md
  joka kertoo mitä endpointteja käytetään, mitkä env-muuttujat,
  miten saa testitilin, miten ajaa lokaalisti.
- Pytest: jokaiselle integraatiolle vähintään client- ja
  adapter-testit mockatuilla vastauksilla (vcr.py tai responses-lib).
- Mitään tuotannolle vapautettua ennen end-to-end -testiä
  pilotti-asiakkaalla testitilillä.
```

---

## Vaihe M1 — Maksaminen, laskutus tuotantoon

**Tavoite:** asiakas voi maksaa varauksen kortilla, raha päätyy
tilille, lasku menee kirjanpitoon.

**Aloita Cursorissa erikseen jokainen alikohta. Älä anna kaikkia
yhdellä kertaa.**

### M1.1 — Stripe-maksuintegraatio

```
Lue ensin: app/billing/models.py, app/billing/services.py,
app/api/routes.py (invoices-endpointit), README.md (billing-osio).

Tehtävä: lisää Stripe-pohjainen kortinkäsittely Pin PMS:ään.

Toteuta:

1. Riippuvuus: lisää requirements.txt:hen `stripe`.
2. Env-muuttujat .env.example:een:
   STRIPE_SECRET_KEY=
   STRIPE_PUBLISHABLE_KEY=
   STRIPE_WEBHOOK_SECRET=
   STRIPE_ENABLED=0
3. Luo app/integrations/stripe/ -moduuli (client.py, service.py,
   adapter.py). client.py kapseloi stripe-SDK:n, lisää retry +
   exponential backoff verkkohäiriöille.
4. Uusi malli app/billing/models.py:hin: Payment
   (id, organization_id, invoice_id, amount, currency,
   provider='stripe', provider_charge_id, provider_intent_id,
   status='pending|succeeded|failed|refunded', failure_code,
   failure_message, created_at, succeeded_at, refunded_at,
   raw_payload_json). Migraatio.
5. Reitti POST /api/v1/invoices/<id>/payment-intent -
   luo Stripe PaymentIntent, palauttaa client_secretin frontille.
   Idempotency-key tulee headerista, tallenna IdempotencyKey-
   tauluun (uusi malli).
6. Reitti POST /webhooks/stripe - vastaanottaa Stripe-eventit.
   Tarkista signature stripe.Webhook.construct_event:llä.
   Käsittele: payment_intent.succeeded -> Payment.status=succeeded,
   Invoice.status=paid, Invoice.paid_at=now, audit-rivi.
   payment_intent.payment_failed -> Payment.status=failed.
   charge.refunded -> Payment.status=refunded, Invoice.status=
   cancelled (tai 'refunded', valitse), audit.
7. Webhook-vastaanottaja kirjoittaa aina raakapayloadin
   webhook_events-tauluun (uusi malli: id, provider, event_type,
   payload_json, signature, received_at, processed_at, error)
   ENNEN prosessointia. Replay-tuki.
8. Admin-UI /admin/payments -lista, suodatus statuksen mukaan,
   refund-painike (vaatii 2FA + audit).
9. Testit: tests/integrations/test_stripe_client.py (mocked
   responses), tests/test_payments_webhook.py
   (signature-validointi, idempotency, status-siirtymät).

Älä koskaan hyväksy webhook-eventiä ilman signature-tarkistusta.
Älä logita full payload jossa on PAN tai CVC (Stripe ei lähetä
niitä, mutta defensiivinen filtteri silti).
```

### M1.2 — Paytrail (Suomen-spesifi vaihtoehto)

```
Identtinen kaava kuin M1.1, mutta Paytrail-API:lla. Lue ensin
M1.1 valmiiksi koodattu osa (app/integrations/stripe/) jotta
pidät rakenteen identtisenä.

Eroavaisuudet:
- Paytrail käyttää HMAC-SHA256 -allekirjoitusta sekä headereissa
  että request bodyssa.
- Refund vaatii erillisen API-kutsun.
- Paytrail tukee suomalaisia maksutapoja (verkkopankki, MobilePay).
- Webhook saapuu success-redirectinä userille, ei suorana
  postauksena - käsittelyä on syytä tehdä myös backendin
  /payments/<id>/check -endpointissa joka kysyy Paytraililta
  statuksen ennen kuittaamista.

Toteuta app/integrations/paytrail/. Lisää Provider-enum
Payment-malliin: 'stripe' | 'paytrail'. Reititys (kumpi on käytössä)
asetuksesta payment_provider per organization (settings-taulu).
```

### M1.3 — Finvoice 3.0 e-laskugenerointi

```
Lue: app/billing/models.py, app/billing/services.py.
Tehtävä: tuota Invoice-rivistä Finvoice 3.0 -yhteensopiva XML.

Toteuta:
1. app/billing/finvoice.py: pure function build_finvoice(invoice)
   joka palauttaa bytes. Käytä lxml-kirjastoa ja Finvoicen
   virallista XSD:tä validointiin. Lisää lxml requirementsiin.
2. Reitti GET /admin/invoices/<id>/finvoice.xml - lataa XML.
3. Lisää PDF-versio (reportlab on jo deps:eissä):
   app/billing/invoice_pdf.py. PDF noudattaa suomalaista
   laskutuskäytäntöä: myyjä, ostaja, Y-tunnus, viitenumero,
   ALV-erittely. Reitti GET /admin/invoices/<id>/pdf.
4. Y-tunnus ja pankkitili tulevat Organization-mallista:
   lisää sarakkeet business_id, iban, bic, vat_number. Migraatio.
5. Viitenumero: generoi suomalainen viitenumeromuoto (RF-viite)
   jokaiselle invoicelle. Tallenna invoices.reference_number.
6. Testit: tests/test_finvoice.py validoi XML xsd:tä vastaan.

Älä yritä toteuttaa pankkiyhteyttä (TITO/camt.053) tässä vaiheessa
- se on M1.4.
```

### M1.4 — Pankkitiliotteen täsmäytys (camt.053)

```
Tehtävä: lue camt.053 -muotoinen XML-tiliote, täsmäytä
maksutapahtumat invoices-tauluun viitenumeron perusteella.

Toteuta:
1. app/billing/bank_reconciliation.py: parse_camt053(xml_bytes).
2. Reitti POST /admin/bank-statements (file upload, vain
   superadmin). Tallenna BankStatement-malli (id, filename,
   uploaded_by, uploaded_at, period_start, period_end, total_in,
   total_out, processed_at).
3. Jokainen tiliotteen tapahtuma -> BankTransaction-rivi:
   amount, currency, reference, party_name, value_date,
   matched_invoice_id (FK, nullable).
4. Auto-match: jos transaction.reference matches
   invoices.reference_number ja amount täsmää -> mark paid,
   audit.
5. Manuaalinen match -nappi UI:ssä epäselviin.

Älä unohda: ulkomaiset maksut tulevat ilman Suomen RF-viitettä,
ne pitää aina matchata käsin. Älä yritä älykästä fuzzy-matchausta
- riski liian suuri.
```

### M1.5 — Kirjanpitoexport

```
Tehtävä: päiväkirjan vientimuoto suomalaisiin
kirjanpitojärjestelmiin.

Toteuta vähintään ONE näistä, ja tee rakenne niin että muut
on helppo lisätä myöhemmin:

- Procountor: REST API + tositeexport
- Visma Netvisor: REST API
- Talenom: CSV-export

Suositus aloittaa Netvisorista koska se on rajapintapohjainen.

1. app/integrations/netvisor/ tavallisella client/service/adapter
   -rakenteella.
2. Cron-job (APScheduler) joka vie edellisen vuorokauden
   maksutapahtumat ja laskut Netvisoriin.
3. Audit jokaisesta synkistä.
4. Admin-UI /admin/accounting -nakymässä manuaalinen "sync now",
   virhelista, viimeisin sync-aika.
5. Env: NETVISOR_*-muuttujat .env.example:een.
6. Testit responses-libillä mockatuilla vastauksilla.
```

---

## Vaihe M2 — Smart lock + online check-in

**Tavoite:** vieras saa varauksesta automaattisesti ovikoodin,
joka toimii vain hänen olonsa ajan. Tämä on Pin PMS:n
erottautumistekijä — koska olet "Pindora", lukkointegraatio on
lähes nimi-velvollisuus.

```
Lue: app/reservations/models.py, app/portal/models.py,
app/portal/services.py.

Tehtävä: lisää Pindora-lukkojen API-integraatio + online-check-in.

Toteuta:

1. app/integrations/pindora_lock/ tavallisella rakenteella.
   Pindoran oikea API-dokumentaatio pitää selvittää erikseen -
   tämä prompt tekee placeholder-rakenteen, johon vendor-spesifit
   kutsut lisätään.

2. Uusi malli LockDevice (id, organization_id, unit_id,
   provider='pindora', provider_device_id, name, status,
   battery_level, last_seen_at). Migraatio.

3. Uusi malli AccessCode (id, reservation_id, lock_device_id,
   code_hash, valid_from, valid_until, is_active, revoked_at,
   revoked_by, created_at). Plaintext-koodi näytetään
   guestille kerran ja sähköpostissa, hash db:ssä.

4. Workflow:
   - Reservation aktivoituu -> luo AccessCode ja lähetä se
     guestille check-in-emaililla.
   - Reservation peruuntuu/lyhenee -> revoke koodi vendorista,
     audit.
   - Reservationin end + 1h -> auto-revoke.

5. Reitti /portal/check-in/<token> (magic link sähköpostissa):
   - Vieras antaa nimi, syntymäaika, henkilötodistuksen valokuva
     (uploads-kansioon, salattu levossa: lisää valinnainen
     kentta-tason salaus pgcrypto:lla tai Fernet:lla).
   - Hyväksyy talon säännöt (allekirjoitus → tallennetaan).
   - Saa ovikoodin näytölle ja sähköpostiin.

6. Audit: lock.code_issued, lock.code_revoked,
   guest.checked_in, guest.checked_out.

7. Mobile-friendly check-in -näkymä (Tailwind/CSS, ei React).

8. Testit mocked-Pindora-clientilla.

Tärkeää: AccessCode.code_hash ei saa palautua API:sta koskaan.
Vain plaintext-versio guestin kerta-näytössä + email.
```

---

## Vaihe M3 — Channel manager + iCal

**Tavoite:** Booking.com- ja Airbnb-varaukset valuvat sisään,
oma kalenteri synkronoituu kanaviin. Yliyökirjautumisen riski
poistuu.

```
Tämä on M-vaiheista RISKIN OSALTA SUURIN. Channel managerit
maksavat tyypillisesti, vendorin API:n laatu vaihtelee, ja
overbooking aiheuttaa asiakassuhteen menetyksen.

VAIHTOEHDOT:
A) Suora integraatio Booking.com Connectivity API:in (tarvitsee
   Booking.com:n hyväksynnän kumppaniksi - kuukausia)
B) Välittäjä (Hostaway, Hosthub, Smoobu) - REST-API yhdellä
   integraatiolla useaan kanavaan
C) Pelkkä iCal export/import - rajallinen, mutta tuotantokelpoinen
   parissa päivässä

SUOSITUS: aloita C:llä, lisää B myöhemmin jos liiketoiminta vaatii.

C-vaiheen toteutus:

1. Reitti GET /api/v1/units/<id>/calendar.ics - palauttaa
   iCal-feedin units.reservations:ista. Suojaus: signed token
   queryssa (HMAC unit_id+secret), ei autentikaatiota muuten.

2. Admin-UI /admin/units/<id>/calendar-sync - näyttää url:n
   jonka voi liimata Airbnb:n ja Booking.com:n kalentereihin.

3. Tuotu kalenteri: app/integrations/ical/. Cron-job pollaa
   organization-tasolla syötetyt iCal-urlit (admin syöttää),
   tuo kiireet ImportedCalendarEvent-tauluun.
   Conflicts-näkymä admin-UI:ssä jos meidän reservation osuu
   tuotuun blockiin.

4. Älä auto-luo reservationia tuodusta iCalista - se on
   tarkoituksellinen rajaus. iCal-blockit ovat vain
   "saatavuus-poissa" -tieto, eivät täysiä varauksia.

5. Audit: calendar.imported, calendar.conflict_detected.

6. Testit ical-libin parserilla.

Vaihe B (Hostaway tms.) on oma erillinen prompt sen jälkeen
kun olet valinnut välittäjän ja saanut sandbox-pääsyn.
```

---

## Vaihe M4 — Operatiiviset moduulit

```
Tehtävä: siivous-/turn-around-moduuli ja lisäpalvelut.

Toteuta:

1. CleaningTask-malli: id, organization_id, unit_id,
   reservation_id (FK), assigned_to_user_id (FK), scheduled_at,
   completed_at, status='pending|in_progress|done|skipped',
   notes, photo_paths_json. Migraatio.

2. Auto-create: kun reservation.end_date saapuu, luo
   CleaningTask seuraavan check-inin alle (jos sellainen on)
   tai vain unit.next_available -hetkelle.

3. Mobile-friendly siivoojan näkymä /cleaning (login: rooli
   'cleaner' - lisää UserRole-enumiin). Lista omat tehtävät,
   "aloita", "valmis"-napit, kuvien upload.

4. Lisäpalvelut: ServiceItem-malli (id, organization_id, name,
   description, price, currency, vat_rate, is_active).
   ReservationServiceItem (id, reservation_id, service_item_id,
   quantity, price_at_booking, vat_rate_at_booking).

5. Lisäpalvelut näkyvät invoice-rivien yhteydessä.

6. Admin-UI: /admin/cleaning, /admin/services.

7. Testit auto-create-logiikalle ja siivoojan workflow:lle.
```

---

## Vaihe M5 — Tekninen kovettaminen ennen skaalausta

```
Tehtävä: sovellus on tähän mennessä yhden VPS:n single-process.
M5 valmistelee skaalauksen ja tuotannon kestävyyden.

Tee jokainen seuraavista omana commitinaan:

5.1 Redis + Celery
- Lisää Redis docker-compose.yml:iin.
- Lisää requirements: celery, redis.
- Korvaa email scheduler (Lista 1 tehtävä 5) Celery-taskilla:
  send_outgoing_email.delay(email_id).
- Korvaa backup scheduler Celery beat:lla.
- Korvaa invoice-overdue-scheduler Celery beat:lla.
- Lisää celery worker -palvelu docker-composeen.
- CELERY_BROKER_URL, CELERY_RESULT_BACKEND env-muuttujat.

5.2 Sentry
- Lisää sentry-sdk[flask] requirementsiin.
- Init Sentry app/__init__.py:ssä jos SENTRY_DSN env on asetettu.
- Lisää release-tagi commitiin (CI vaiheessa).
- Älä lähetä Sentryyn user-PII:ta - asetä before_send-filtteri
  joka strippaa email/phone/ip jos mahdollista.

5.3 Prometheus-metriikat
- prometheus-flask-exporter. Endpoint /metrics suojattu
  basic-auth:lla (env: METRICS_USER, METRICS_PASS).
- Custom counterit: emails_sent_total, payments_succeeded_total,
  payments_failed_total, backups_created_total.

5.4 OpenAPI / Swagger UI
- (siirrettiin Lista 1:n tehtävästä 13 tähän jos jäi tekemättä)
- flask-smorest. /api/v1/docs.

5.5 Strukturoidut JSON-lokit
- structlog requirementsiin.
- Korvaa Python logging structlogilla joka rendaa JSON:in.
- Jokaiseen requestiin liitetään request_id-headerista
  (tai generoidaan) ja se tagaa kaikki saman pyynnön lokirivit.

5.6 GDPR-eksportit
- Reitti /portal/account/export (vaatii guestin login):
  zip-paketti, jossa kaikki data häneen liittyen
  (reservations, invoices, payments, audit-rivit joissa hän
  on subject) JSON-muodossa.
- Reitti /portal/account/delete: pyyntö admin-jonon kautta.
  Adminilla 30 vrk vahvistaa - sen jälkeen anonymize:
  email -> deleted-<id>@example.invalid, name -> "Deleted",
  ID-kuvat poistetaan, mutta laskut ja maksut säilytetään
  kirjanpitolain vaatimasta syystä (anonymisoituina).
- Audit kaikesta.
- Testit: tests/test_gdpr_export.py.

5.7 Backup-restoren testaus
- CI-job joka kerran viikossa vetää tuoreimman backup:n
  staging-DB:hen ja ajaa sanity-checkin (pytest osa-suite
  staging-asetuksilla).

5.8 Tietoturva-auditti
- Aja Bandit ja Semgrep CI:ssä.
- Aja pip-audit / safety dependencyille.
- Korjaa kaikki HIGH-tason löydökset.
```

---

## Vaihe M6 — Two-way messaging + automaatiot

```
Tehtävä: sähköposti- ja SMS-viestintä guestin kanssa,
ketjutettuna varaukseen, automaattiset triggerit.

Toteuta:

1. SMS-tuki: integroi Twilio (USA-lähtöinen, hyvät dokut) tai
   Telia/Sinch (suomalainen). Jälkimmäinen järkevämpi
   suomalaiselle kohderyhmälle.
   app/integrations/sms/<provider>/. SMS_ENABLED env.

2. Conversation-malli: id, organization_id, reservation_id,
   guest_id, channel='email|sms', subject, last_message_at.
   Message: id, conversation_id, direction='in|out',
   content, sender_user_id (nullable), provider_message_id,
   delivered_at, read_at, created_at.

3. Inbound webhook (Twilio/sähköposti): vastaanottaa viestin,
   yhdistää oikeaan conversationiin (puhelinnumero tai
   email-osoite).

4. Outbound: admin lähettää /admin/conversations/<id>:stä.

5. Automaatiot (AutomationRule-malli):
   - trigger_event: reservation.confirmed, day_before_arrival,
     day_of_arrival, day_of_departure, after_departure
   - template_key: viite EmailTemplateen tai SmsTemplateen
   - delay_hours, channel
   APScheduler/Celery beat tarkistaa joka tunti laukeavat säännöt.

6. Mallinnukset: pre-arrival ohjeet (osoite, ovikoodit),
   in-stay tervehdys, post-stay arvostelupyyntö.

7. Audit: message.sent, automation.triggered.

8. Testit.
```

---

## Vaihe M7 — Suomen markkinan compliance

```
KRIITTINEN: tähän kuuluu lakipohjaisia velvoitteita. Käytä
Cursoria koodin tekemiseen mutta TARKISTA sisältö lakimiehellä
tai tilitoimistolla ennen tuotantoa.

Toteuta:

1. Matkustajailmoitus (laki majoitus- ja ravitsemustoiminnasta
   308/2006, ja sen 6 §):
   - Jokaisesta yli 12 v. vieraasta tallennetaan: nimi,
     syntymäaika, kansalaisuus, henkilötodistuksen tyyppi+nro,
     osoite, saapumis- ja lähtöpäivä.
   - Tiedot pitää säilyttää 1 vuosi ja luovuttaa pyynnöstä
     poliisille.
   - Lisää RegistrationForm-malli ja autom. lomake check-in-
     prosessissa (M2.5).
   - Reitti /admin/police-export?from=...&to=... joka tuottaa
     CSV/PDF poliisin pyynnöstä.

2. ALV-raportit:
   - Reports-näkymä /admin/reports/vat: kuukausittainen ALV
     myynnistä ja ostoista (ostot tulee kirjanpidosta, joten
     vain myynti-puoli pakollinen aluksi).
   - Suomen ALV-kannat: 25,5 % yleinen, 14 % majoitus, 10 %
     muutamia.

3. Käyttöehdot ja sopimukset:
   - Sopimusgeneraattori: jokaisesta varauksesta PDF-sopimus
     reportlabilla (M-asetukset: peruutusehdot, vahingot, jne).
   - Tallennus reservation.contract_path.
   - Sähköinen allekirjoitus: aluksi click-through (käyttäjä
     täyttää nimen + IP+timestamp tallennetaan), myöhemmin
     ehkä Visma Sign / Dokobit.

4. Tietosuojaseloste:
   - Static-page /privacy, käännöskattava (i18n M8).
   - Cookie consent: yksinkertainen banneri, evästekategoriat,
     suostumuksen hash + ajankohta tallennetaan.

5. DPA (Data Processing Agreement):
   - PDF-template /admin/dpa-download, jonka asiakas voi
     allekirjoittaa kanssasi käyttöönotossa.

6. Audit: police_export.generated, contract.signed,
   privacy.consent_recorded.

LAKITARKISTUS PAKOLLINEN ENNEN TUOTANTOA. Älä julkaise näitä
"valmiina" ilman juridista review:tä.
```

---

## Vaihe M8 — UX-loppuhionta

```
Tämä on viimeisin vaihe — tehdään vasta kun core-toiminta on
vakaa.

Toteuta:

1. i18n: Flask-Babel.
   - Käännöskielet: fi (lähde), sv, en.
   - Kaikki templatit ja flash-viestit gettext-merkattuina.
   - Org-tason oletuskieli (organizations.default_locale).
   - Guest-portaalin kielenvalinta queryssä tai cookiesta.

2. Mobile-friendly admin:
   - Ei vaihdeta frameworkkiä, mutta lisätään Tailwind ja
     käytetään responsive-luokkia kaikkialla.
   - Listanäkymät -> kortteina mobiilissa, taulukoina
     desktopilla.

3. Custom branding per tenant:
   - Organization: logo_path, primary_color, accent_color,
     email_signature.
   - Logo näytetään admin-UI:n topbarissa ja sähköposteissa.
   - Sähköpostipohjat saavat {{ org.primary_color }}
     -muuttujan.

4. Onboarding-wizardi:
   - Uudella organisaatiolla ensimmäisellä superadmin-loginilla
     /onboarding-flow: 1) brand, 2) properties+units, 3) hinnat,
     4) maksuyhteydet, 5) sähköpostipohjat tarkistus.
   - Kukin askel tallentaa edistymän organizations.onboarding_step.

5. Status-sivu:
   - /status (julkinen): viimeisten 90 vrk uptime,
     päivystysilmoitukset.
   - Manuaalinen incident-syöttö admin-UI:stä.

6. PWA-versio guest-portaalista: manifest.json + service
   worker offline-perusnäkymälle (varauksen tiedot, ovikoodi).

7. Testit: visual regression on overkill — riittää että
   linkit ja flowt on smoke-testattu.
```

---

## Lopuksi

Lista 2:n läpivienti kestää realistisesti 6–18 kuukautta yhden
vaihtelevatehoisen kehittäjän voimin riippuen siitä, kuinka
montaa M-vaihetta ajetaan rinnakkain. Älä yritä lyhentää tätä
sanomalla Cursorille "tee koko Lista 2" — saat 5 000 riviä
puolivalmista koodia jota kukaan ei uskalla deployata.

Suositus järjestys:
1. Lista 1 valmiiksi (~1–2 viikkoa)
2. M1.1 Stripe pilottiin (~2 viikkoa)
3. M5.1 + M5.2 + M5.4 tuotantoon (~1 viikko)
4. M2 jos lukkointegraatio on tuotteen ydin (~3 viikkoa)
5. M1.3 + M1.5 ensimmäiselle suomalaiselle asiakkaalle (~2 viikkoa)
6. M7 ennen kuin asiakkaita on todella paljon (~2 viikkoa)
7. Loput priorisoinnin mukaan asiakaskysynnästä.

Pidä Cursor agent-tilassa ja anna sille **yksi M-aliosa
kerrallaan**. Pyydä aina lopuksi:
- "Aja pytest -q"
- "Tee yhteenveto, mitä lisättiin ja mihin tiedostoihin"
- "Listaa env-muuttujat jotka pitää asettaa ennen kuin tämä
  toimii"

Onnea matkaan.
