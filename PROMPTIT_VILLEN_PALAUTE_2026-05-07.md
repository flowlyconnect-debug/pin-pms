# Promptit Villen palautteen kuittaamiseksi (10/10)

**Tarkoitus:** kymmenen itsenäistä ChatGPT-syötettä — yksi per Pekan/Villen
palautekohta. Käytä työnkulkua **Sinä → ChatGPT → Cursor**:

1. Kopioi yksi prompti kerrallaan ChatGPT:lle.
2. Anna ohje: *"Hio tästä Cursorille syötettävä tarkka tehtävänanto.
   Säilytä konteksti, toimenpiteet ja hyväksymiskriteerit. Älä lisää
   skooppia."*
3. Vie ChatGPT:n hiottu versio Cursoriin ja anna sen toteuttaa.
4. Aja `pytest -v` jokaisen promptin jälkeen ennen kuin etenet seuraavaan.

**Suoritusjärjestys:** 7 → 10 → 4 → 2 → 6 → 5 → 1 → 8 → 9 → 3.
(Bugifix ensin, lokalisaatio toiseksi, sitten näkymät & ominaisuudet,
viimeisenä verifikaatiot.)

Jokainen prompti on rajattu **yhteen kohtaan kerrallaan** — ei
sivuvaikutuksia muille moduuleille. Älä yhdistele promptteja.

---

## Prompti 1 — Maksutapojen savutestaus (Pekan kohta 1)

> **ChatGPT-syöte → Cursor-toteutus.** Lyhyt verifikaatio, ei uutta koodia.

```
Tehtävä: Lisää automaattinen savutesti joka todentaa että Stripe ja
Paytrail toimivat testitilassa Pindora-PMS:ssä.

Konteksti:
- Repo: Flask-pohjainen monikäyttäjä-PMS.
- README "Maksuintegraatio" listaa testitunnukset:
  - Stripe: testikortti 4242 4242 4242 4242
  - Paytrail: MERCHANT_ID=375917, SECRET_KEY=SAIPPUAKAUPPIAS
- CLI:t `flask payments-test-stripe --invoice-id <id>` ja
  `flask payments-test-paytrail --invoice-id <id>` ovat olemassa
  (`app/cli.py`).
- Asiakas Pekka raportoi 2026-05-06 että Stripe + Paytrail näyttävät
  toimivan käyttöliittymässä, mutta verifikaatiotestit ovat manuaalisia.

Toimenpiteet:
1. Lisää `tests/test_payments_routes.py`:n yhteyteen tai uuteen
   tiedostoon `tests/test_payments_smoke.py`:
   - Mockaa Stripe SDK:n `checkout.Session.create` ja Paytrailin HTTP-
     vastaus (käytä `responses`- tai `requests-mock`-kirjastoa, jos
     repon konvention mukainen).
   - Testit:
     a) `test_stripe_checkout_returns_redirect_url` — `create_checkout`
        Stripelle palauttaa `redirect_url`-stringin.
     b) `test_paytrail_checkout_returns_redirect_url` — sama Paytrailille.
     c) `test_stripe_webhook_marks_invoice_paid` — kutsu
        `/api/v1/webhooks/stripe` mockatulla allekirjoituksella;
        vastaava lasku saa `paid`-statuksen ja audit-rivi syntyy.
     d) `test_paytrail_callback_marks_invoice_paid` — sama Paytrailille.
2. Lisää README:n "Maksuintegraation manuaalitesti"-osion alle
   "Automaattinen savutesti" -alaosio joka kertoo:
   `pytest tests/test_payments_smoke.py -v`
3. Älä muuta tuotantokoodia (`app/payments/`-puuhun).

Hyväksymiskriteerit:
- Uudet testit menevät läpi.
- Olemassa olevat `tests/test_payments_*.py` eivät rikkoudu.
- Mockit eivät tee verkkokutsuja (verifioi `pytest-socket`-disablella,
  jos käytössä, tai kommentilla).

Älä koske webhookien allekirjoitustarkistuksiin tai
`PaymentProvider`-rajapintaan.
```

---

## Prompti 2 — Päivän/viikon "Mitä on vapaana?" -pikahaku (Pekan kohta 2)

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Lisää Pin PMS:n hallintapaneelin yläpalkkiin pikahaku
"Mitä on vapaana tänään / huomenna / X-päivän aikana", joka palauttaa
listan vapaista huoneista yhdellä klikkauksella.

Konteksti:
- Pekka kommentoi 2026-05-06: "Jos puhelimessa hustlaisin toimistoa
  jollekin, niin helpottaisi nähdä mitä on vapaana missäkin." Nykyinen
  /admin/availability on matriisi mutta vaatii sivun lataamisen.
- /admin/calendar tarjoaa FullCalendarin, mutta ei suoraa "vapaa nyt"-
  vastausta.
- Käyttöliittymässä on jo `app/components/layout/CommandPalette.tsx`
  (mahdollisesti — varmista) ja `admin-search.js`-globaali haku.

Toimenpiteet:
1. Lisää admin-yläpalkkiin (`app/templates/admin/base.html` tai
   vastaavaan layout-templateen) pikapainike "Vapaat huoneet" jonka
   takana on dropdown:
   - "Tänään"
   - "Huomenna"
   - "Tämä viikonloppu" (la–su)
   - "Seuraavat 7 päivää"
2. Toteuta backend-endpoint
   `GET /admin/availability/quick?range=today|tomorrow|weekend|7d`
   joka palauttaa JSON:in:
   ```
   {
     "success": true,
     "data": {
       "range": "today",
       "start_date": "2026-05-07",
       "end_date": "2026-05-07",
       "free_units": [
         { "property": "Aleksanterinkatu 1", "unit": "A12",
           "free_days": 1, "next_reservation_in_days": 3 },
         ...
       ]
     }
   }
   ```
   - Käytä olemassa olevaa `app/properties/services.py`/availability-
     logiikkaa — älä duplikoi varauspoliittisuutta.
   - Rajaa `organization_id`-tarkistuksella (tenant-isolaatio).
3. Renderöi tulos popoverissa tai modaalissa pikalinkillä uuteen
   varaukseen kullekin riville (esitäytetty unit_id + päivämäärät).
4. Lisää testit:
   - `tests/test_admin_availability_quick.py`:
     a) Testitili näkee vain oman organisaationsa rivit.
     b) "Tänään" palauttaa vain ne yksiköt, joilla ei ole varausta
        kyseisenä päivänä.
     c) "Seuraavat 7 päivää" laskee `free_days` oikein.
5. Päivitä README:n "Admin UI usage"-osio mainitsemaan pikahaku.

Hyväksymiskriteerit:
- Painike näkyy admin-layoutissa kaikilla rooleilla joilla on pääsy
  /admin/properties:iin.
- Endpoint palauttaa max 100 ms keskimäärin paikallisella demo-
  datalla (lisää indeksi reservations(unit_id, start_date, end_date),
  jos sitä ei vielä ole).
- Pytest vihreä, ei muutoksia muihin admin-näkymiin.

Älä rakenna uutta SPA:ta — käytä server-rendered Jinjaa tai pientä
JS-komponenttia.
```

---

## Prompti 3 — Vapaiden huoneiden quick-card etusivulle (Pekan kohta 3 jatko)

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Korvaa Pin PMS dashboardin nykyinen "Yksiköiden tilanne tänään"
-listalle kompakti kortti "Vapaat huoneet juuri nyt", jossa näkyvät
ensimmäiset 10 vapaata + linkki täyteen näkymään.

Konteksti:
- Asiakkaan kommentti: "Etusivulta löytyy listana ja siinä on aika
  plärääminen, kun huoneita ja kohteita on paljon."
- `app/templates/admin/dashboard.html` rivit 87–100 renderöivät
  nykyisen listan.

Toimenpiteet:
1. Muokkaa `app/admin/services.py`:n dashboard-summary-funktiota
   palauttamaan myös:
   ```
   "free_units_now": [
     { "unit_label": "Aleksanterinkatu 1 / A12",
       "link": "/admin/units/42",
       "next_reservation_label": "Vapaa kunnes 9.5." },
     ...
   ]
   ```
   Rajaa max 10 riviä, tilaa sarakkeessa lyhyt selite.
2. Päivitä `dashboard.html`:n osio `Yksiköiden tilanne tänään`
   tilalle:
   ```html
   <section class="card content-card" aria-labelledby="free-now-h">
     <div class="card-header">
       <h2 id="free-now-h">Vapaat huoneet juuri nyt
         ({{ summary.free_units_now|length }} / {{ summary.total_units }})</h2>
       <a class="btn btn-secondary btn-sm"
          href="{{ url_for('admin.availability_page') }}">
         Avaa täysi näkymä
       </a>
     </div>
     {% if summary.free_units_now %}
       <ul class="dashboard-upcoming-list">
         {% for row in summary.free_units_now %}
           <li>
             <a href="{{ row.link }}"><strong>{{ row.unit_label }}</strong></a>
             <span class="meta">{{ row.next_reservation_label }}</span>
           </li>
         {% endfor %}
       </ul>
     {% else %}
       <p class="empty-state"><em>Ei vapaita huoneita juuri nyt.</em></p>
     {% endif %}
   </section>
   ```
3. Lisää testit `tests/test_admin_dashboard.py`:
   a) Kortin otsikko sisältää vapaiden lukumäärän.
   b) Listalla on max 10 riviä.
   c) "Avaa täysi näkymä"-linkki vie `/admin/availability`-polulle.

Hyväksymiskriteerit:
- Pytest vihreä.
- `tests/test_ui_finnish.py` ei valita uusia englanninkielisiä
  jäänteitä.
- Kortti ei aiheuta enempää tietokantakyselyjä kuin nykyinen lista
  (mittaa `flask shell`-komennolla `db.engine.echo = True` lokaalisti).

Älä poista "Tänään saapuu / Tänään lähtee" -kortteja.
```

---

## Prompti 4 — Kohteen ja huoneen rikkaiden tietojen UI (Pekan kohta 4)

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Tuo Property- ja Unit-mallien jo olemassa olevat kuvailevat
kentät täysimääräisesti admin-UI:n muokkaus- ja katselunäkymiin.

Konteksti:
- Migraatiot ovat jo tuoneet kentät tietokantaan:
  Property: street_address, postal_code, city, latitude, longitude,
  year_built, has_elevator, has_parking, has_sauna, has_courtyard,
  has_air_conditioning, description, url
  Unit: area_sqm, floor, bedrooms, max_guests, unit_type, has_kitchen,
  has_bathroom, has_balcony, has_terrace, has_dishwasher,
  has_washing_machine, has_tv, has_wifi, description,
  floor_plan_image_id
- Pekka 2026-05-06: "Myyjää helpottaisi, jos olisi oma slotti huoneen
  sijainnille, neliöille ja muut kohteen tai huoneen ominaisuudet
  (hissit, keittiöt tms.)."

Toimenpiteet:
1. Tarkista admin-templatet:
   - `app/templates/admin/properties/new.html`
   - `app/templates/admin/properties/edit.html`
   - `app/templates/admin/properties/detail.html`
   - `app/templates/admin/units/new.html`
   - `app/templates/admin/units/edit.html`
   - `app/templates/admin/units/detail.html`
   Listaa kunkin kentän tila: a) lomakkeessa, b) detail-näkymässä,
   c) puuttuu.
2. Lisää lomakkeisiin puuttuvat kentät loogisina osioina:
   - Property: "Sijainti" (street_address, postal_code, city,
     latitude, longitude), "Rakennus" (year_built, has_elevator,
     has_parking, has_sauna, has_courtyard, has_air_conditioning),
     "Lisätiedot" (description, url).
   - Unit: "Mitat" (area_sqm, floor, bedrooms, max_guests, unit_type),
     "Varustelu" (has_kitchen, has_bathroom, has_balcony, has_terrace,
     has_dishwasher, has_washing_machine, has_tv, has_wifi),
     "Lisätiedot" (description, floor_plan_image_id).
   Käytä `<fieldset>` + `<legend>` selkeyden vuoksi.
3. Lisää detail-näkymiin sama ryhmittely lukutilassa (`<dl>`-listat
   tai `.detail-grid`).
4. Päivitä `app/admin/forms.py` (jos käytössä) ja palvelukerros
   (`app/properties/services.py`) hyväksymään ja validoimaan kentät:
   - Numerot: `area_sqm` 0–10 000, `floor` -5 – 200, `year_built`
     1800–2100, `bedrooms` 0–50, `max_guests` 0–200.
   - URL-kenttä: validoi `urllib.parse.urlparse` + scheme http/https.
   - Boolean-kenttiä ei tarvitse validoida erikseen.
5. Lisää testit:
   `tests/test_admin_property_unit_fields.py`:
   a) POST /admin/properties luo rivin kaikilla kentillä.
   b) GET edit-näkymä esittää kaikki kentät.
   c) POST /admin/units validoi area_sqm-rajan.
   d) Detail-näkymässä booleanit näkyvät "Kyllä/Ei"-tekstinä, ei
      raw `True/False`.

Hyväksymiskriteerit:
- Pytest + olemassa olevat property/unit-testit vihreät.
- Mikään API-vastauksen JSON-rakenne ei muutu (taaksepäin
  yhteensopiva).
- `tests/test_ui_finnish.py` ei valita.

Älä koske `migrations/`-tiedostoihin — kentät ovat jo siellä.
```

---

## Prompti 5 — Sopparityökalun seuraava taso (Pekan kohta 5)

> **ChatGPT-syöte → Cursor-toteutus.** Suurempi kokonaisuus —
> jaa Cursorille tarvittaessa kahteen PR:ään.

```
Tehtävä: Nosta Pin PMS:n vuokrasopimustyökalu (Lease) ammattikiinteistön-
hallinnan tasolle. Kolme tasoa: (A) sopimuspohjat, (B) generoitu PDF +
e-allekirjoituslähetys, (C) automaattinen jatko/laskutuskytkentä.

Konteksti:
- Nykyinen `Lease`-malli (`app/billing/models.py`) tukee elinkaarta
  draft → active → ended/cancelled, billing_cycle, rent_amount,
  deposit_amount, notes.
- Asiakas: "Yksinkertaisen sopparin luominen helppoa, mutta riittääkö
  ammattimaisessa kiinteistönhallinnassa?"
- Sähköpostipohjat ovat jo olemassa (`app/email/`), Mailgun toimii.

Toimenpiteet (taso A — sopimuspohjat):
1. Luo uusi taulu `lease_templates` (Alembic-migraatio):
   - id, organization_id, name, description
   - body_markdown (vakiolausekkeet ja muuttujat,
     esim. `{{ tenant_name }}`, `{{ rent_amount }}`)
   - is_default (boolean), created_at/updated_at
2. Lisää superadmin-näkymä /admin/lease-templates jossa voi:
   - listata, luoda, muokata, asettaa oletuksen (yksi default per
     organisaatio).
3. Renderöinti-helper `render_lease_template(template_id, lease_id)`
   joka syöttää muuttujat vuokrasta + huoneesta + asiakkaasta.

Toimenpiteet (taso B — PDF + e-allekirjoitus):
4. Käytä olemassa olevaa `app/billing/pdf.py`-kirjastoa (tai vastaavaa
   reportlab/pdfkit) ja generoi sopimuspdf vuokraan
   `/admin/leases/<id>/pdf`.
5. Lisää sähköpostipohja `lease_sign_request` (subject + body) ja
   reitti `POST /admin/leases/<id>/send-for-signing` joka:
   - generoi PDF:n,
   - tallentaa sen tilapäiseksi liitteeksi (uploads-hakemistoon, niin
     että backup kattaa sen),
   - lähettää sähköpostin asiakkaalle Mailgunin liitteenä,
   - merkkaa Lease.status = "pending_signature" (uusi enum-arvo).
6. Lisää reitti `GET /lease/sign/<signed_token>` (julkinen) joka näyttää
   sopimuksen ja kirjaa hyväksynnän:
   - signed_at-timestamp,
   - signed_ip,
   - signed_user_agent.
   Allekirjoituksen jälkeen Lease.status = "active".

Toimenpiteet (taso C — automaattilaskutus, valinnainen jos aikaa):
7. Hyödynnä olemassa olevaa `INVOICE_OVERDUE_SCHEDULER`:ää: lisää
   sisarjob "lease-cycle-billing" joka generoi `Invoice`-rivin Lease-
   billing_cyclen mukaan (kuukausittain/viikoittain/kertaluonteinen).
8. Lisää `tests/test_lease_billing_cycle.py`-testit:
   a) Aktiivisesta kuukausilease:sta syntyy joka kuukauden 1. päivä
      lasku.
   b) Päättynyt lease ei tuota uusia laskuja.
   c) Allekirjoittamaton lease ei laskuta.

Audit-loki (KAIKKI tasot):
9. Kirjaa audit-rivi tapahtumille:
   - lease.template.created/updated/deleted
   - lease.signed
   - lease.cycle_invoice.created

Hyväksymiskriteerit:
- Migraatio onnistuu nollaan kantaan.
- Testit (uudet + olemassa olevat lease-/invoice-testit) vihreitä.
- README:hen "Lease lifecycle" -osio joka kuvaa A/B/C-vaiheet.
- Manuaalitesti: superadmin luo template → admin luo lease →
  lähettää allekirjoitukseen → asiakas allekirjoittaa →
  ensimmäinen lasku syntyy automaattisesti.

Älä poista olemassa olevia status-arvoja — vain lisää uusia.
Älä integroi Docusignia tai vastaavaa kolmannen osapuolen palvelua
tässä vaiheessa — sisäinen "klikkaa ja vahvista"-allekirjoitus
riittää MVP:lle.
```

---

## Prompti 6 — Kassavirtaraportin laajennus (Pekan kohta 6)

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Laajenna Pin PMS:n kassavirtaraporttia käyttöasteen ja
ennakoidun laskutuksen kanssa, jotta ammattilaisvuokraaja saa rahasta
ja täyttöasteesta yhdellä silmäyksellä kattavan kuvan.

Konteksti:
- Asiakas Pekka 2026-05-06: "Käyttöasteraportti ja varausraportti
  aika simppelit, toivoisin rahaan ja kassavirtaan liittyvää dataa."
- Olemassa olevat raportit:
  app/templates/admin/reports/cash_flow.html
  app/templates/admin/reports/income_breakdown.html
  app/templates/admin/reports/expenses_breakdown.html
  app/templates/admin/reports/occupancy.html
  app/templates/admin/reports/reservations.html
- `app/reports/services.py` palauttaa nykyiset rivit.

Toimenpiteet:
1. Laajenna kassavirtaraportin (cash_flow.html) datasettejä:
   - Tulot per kohde / per huone (pivotattuna).
   - Tulot per maksutapa (Stripe / Paytrail / Manuaalinen).
   - Erääntyneet saatavat ikäluokittain (0–30, 31–60, 61–90, 90+ pv).
   - Ennakoitu kassavirta seuraaville 30/60/90 päivälle (käytä
     `Lease`-rivien ja `Reservation`-hintojen tietoja).
2. Lisää uusi raportti
   /admin/reports/profitability "Kannattavuus per kohde":
   - Sarakkeet: Kohde, Tulot, Kulut, Netto, Käyttöaste %.
   - Suodattimet: päivämääräväli, kohde.
   - CSV/XLSX-vienti olemassa olevaa export-helperia hyödyntäen.
3. Päivitä Dashboard-KPI:t:
   - Lisää "Erääntyneet saatavat (0–30/31–60/60+)" -mini-kortti
     ikäluokituksella.
   - Lisää "Ennakoitu kassavirta seur. 30 pv" -kortti.
4. Päivitä `app/reports/services.py`:
   - `compute_cash_flow_breakdown(start, end, organization_id)`
   - `compute_aging_receivables(organization_id, as_of)`
   - `compute_forecasted_cash_flow(organization_id, days_ahead)`
   - `compute_profitability_by_property(start, end, organization_id)`
5. Testit `tests/test_cash_flow_extended.py`:
   a) Aging-luokat laskeutuvat oikein rajoilla 30/60/90.
   b) Ennakoitu kassavirta käyttää vain `active`-leaseja ja
      `confirmed`-varauksia.
   c) Profitability-raportti ei vuoda toiseen organisaatioon.

Hyväksymiskriteerit:
- Olemassa oleva `tests/test_cash_flow.py` vihreä.
- Uudet testit vihreitä.
- Raporttien latausaika alle 1 sekunti 1 000 varausta + 1 000 laskua
  -datalla (mittaa `flask shell`-aikamerkinnöillä).
- CSV/XLSX-viennit toimivat uusille raporteille.

Älä koske maksuintegraatioon (`app/payments/`) — vain raportointi.
```

---

## Prompti 7 — 500-virheen jäljitys ja korjaus kalenterisynkkausnäkymässä (Pekan kohta 7)

> **ChatGPT-syöte → Cursor-toteutus.** **Aja ensin** — bugifix
> ennen muuta kehitystä.

```
Tehtävä: Reproduke ja korjaa Pin PMS:ssä havaittu 500-virhe
kalenterisynkkausnäkymässä, ja varmista että vastaava virhe ei
toistu.

Konteksti:
- Asiakas Pekka 2026-05-06 raportoi: "Jokunen 500 error sieltä tuli
  (etenkin kalenterisynkkausnäkymä)."
- Kyseessä on `/admin/units/<unit_id>/calendar-sync` -näkymä,
  template `app/templates/admin/units/calendar_sync.html`, näkyy
  myös `/admin/calendar/sync/conflicts` -konfliktilistassa.
- Repon juuressa `pin-pms-bugfix-plan.html` voi sisältää alustavaa
  analyysiä — lue se ja täydennä.

Toimenpiteet:
1. Reproduke paikallisesti:
   - `docker compose up --build -d`
   - `flask db upgrade`
   - `flask seed-demo-data`
   - Avaa /admin/units/<jonkin demo-unitin id>/calendar-sync
   - Lisää virheellinen iCal-URL (esim. http://example.com/missing)
   - Klikkaa "Tallenna lähde" → "Synkronoi nyt"
2. Lue Sentry/lokit (`logs/`, `journalctl -u pindora-web`, tai
   stdout) ja eristä exception. Tallenna stack trace
   `BUG_500_ICAL_2026-05-07.md`-tiedostoon repon juureen.
3. Korjaa virhe minimaalisesti:
   - Jos kyseessä on verkkovirhe: `requests.exceptions.*`-handler
     palvelukerroksessa (`app/integrations/ical/service.py`).
   - Jos kyseessä on parsintavirhe: vClass-objektin kentän puuttuminen
     → tarkista `if x is None`-haarat.
   - Jos kyseessä on tietokanta-vika: nullable-FK + commit-batchi.
4. Lisää regressiotesti
   `tests/test_ical_integration.py`:
   a) `test_sync_handles_unreachable_url_gracefully` — palvelu
      palauttaa virhe-stringin, ei nosta 500:ää.
   b) `test_sync_handles_malformed_ics_payload`.
   c) `test_admin_calendar_sync_view_renders_when_feed_has_errors` —
      template renderöityy vaikka feed.last_error olisi pitkä.
5. Lisää käyttöliittymään selkeä virhebanneri
   (`{{ feed.last_error }}` saa max 240 merkkiä), ja "Yritä
   uudelleen"-painike.
6. Käy läpi muut samankaltaiset reitit ja tarkista ettei sama
   poikkeus jää käsittelemättä:
   - `/admin/calendar/sync/conflicts`
   - `/admin/integrations/pindora-lock/*`
7. Päivitä `BUG_500_ICAL_2026-05-07.md` — viimeinen status, korjauksen
   commitin sha ja regressiotestin nimi.

Hyväksymiskriteerit:
- Reproduktio ei enää tuota 500:ää, vaan käyttäjälle näkyvän
  virheviestin Suomeksi.
- Uudet testit vihreät.
- Olemassa olevat ical/calendar-testit vihreät.
- `BUG_500_ICAL_2026-05-07.md` dokumentoi alkuperäisen virheen,
  juurisyyn ja korjauksen.
- Sentry/Sentry-mock ei kerää uusia "ICalSyncError unhandled"-
  rivejä reproduktiossa.

Älä piilota virhettä `try/except Exception: pass`-blokkiin — vie
tarkka virhe lokiin ja näytä käyttäjälle kohtuullinen viesti.
```

---

## Prompti 8 — Huoltopyyntölomakkeen prioriteettien verifikaatio (Pekan kohta 8)

> **ChatGPT-syöte → Cursor-toteutus.** Pieni verifikaatio + UI-hionta.

```
Tehtävä: Varmista että huoltopyyntölomakkeen prioriteetit näkyvät
suomeksi koko järjestelmässä (lomake, listat, suodattimet, raportit,
sähköpostit), ja lisää regressiotesti.

Konteksti:
- Asiakas Pekka 2026-05-06: "Huoltopyyntöä ei voi tehdä, koska
  kriittisyys pitää olla merkittynä lontoonkielisillä termeillä."
- `app/templates/admin/maintenance/new.html` rivit 44–49 näyttävät jo
  suomenkielisiä labeleita: Matala, Normaali, Korkea, Kiireellinen.
- `app/maintenance/models.py:MaintenanceRequest.PRIORITY_LABELS`
  mappaa low/normal/medium/high/urgent → fi.
- Tausta-arvot pysyvät englanniksi (low/normal/high/urgent), mikä on
  ok — ne ovat sisäisiä.

Toimenpiteet:
1. Käy läpi kaikki huoltoon liittyvät templatet ja näkymät:
   - `app/templates/admin/maintenance/list.html`
   - `app/templates/admin/maintenance/edit.html`
   - `app/templates/admin/maintenance/detail.html`
   - `app/templates/admin/maintenance/new.html`
   - `app/templates/portal/maintenance.html`
   - `app/templates/portal/maintenance_detail.html`
   Korvaa raw `{{ row.priority }}` → `{{ row.priority_label }}`
   (käyttää `MaintenanceRequest.priority_label`-propertya).
2. Tarkista listan suodattimet — dropdownien `<option>`-tekstit ovat
   suomeksi mutta arvot englanniksi.
3. Sähköpostit: jos `app/email/`-pohjat (`maintenance_*`) viittaavat
   `priority`-muuttujaan, käytä `priority_label`-versiota ja lisää
   sähköpostiseed:iin tämä muutos.
4. Lisää testit `tests/test_maintenance.py`:
   a) `test_maintenance_list_renders_priority_in_finnish` — GET
      /admin/maintenance ei sisällä strings "low", "normal", "high",
      "urgent" mutta sisältää "Matala", "Normaali", "Korkea",
      "Kiireellinen".
   b) `test_maintenance_create_form_submits_with_finnish_label_value` —
      varmista että lomake hyväksyy backend-arvot, ei käännöstekstejä
      (`priority=high` toimii, `priority=Korkea` palauttaa 400).
   c) `test_priority_label_for_unknown_value_returns_dash` —
      tuntematon arvo palauttaa "-" tai alkuperäisen merkkijonon.
5. Päivitä portal-näkymät niin, että vieraskäyttäjä ei näe muuta
   kuin omat huoltopyyntönsä, ja prioriteetti on suomeksi.

Hyväksymiskriteerit:
- Pytest vihreä.
- `tests/test_ui_finnish.py` ei valita uusia jäänteitä.
- Manuaalitesti `flask seed-demo-data` jälkeen: GET
  /admin/maintenance, /portal/maintenance — kaikki prioriteetit
  suomeksi.

Älä muuta tietokannan tai API:n raw-arvoja low/normal/high/urgent.
```

---

## Prompti 9 — Kalenterin klikattavuuden verifikaatio (Pekan kohta 9)

> **ChatGPT-syöte → Cursor-toteutus.** Pieni UX-verifikaatio.

```
Tehtävä: Varmista, että /admin/calendar -näkymässä koko
varausmerkinnän alue (sekä päiväsolu) on klikattava, ei vain pieni
ikoni rivin lopussa.

Konteksti:
- Asiakas Pekka 2026-05-06: "Esimerkiksi kalenterimerkinnät aukeaisi
  klikkaamalla mihin vain kohtaa saraketta eikä sieltä ihan rivin
  päästä pientä ikonia painamalla."
- `app/static/js/admin-calendar.js` käyttää FullCalendaria, joka jo
  reagoi `eventClick`:iin koko event-elementin alueella (rivi 141–144).
- Availability-matriisi (`app/templates/admin/availability.html`)
  käyttää `<a>`-tageja kokonaisten solujen sisällä.

Toimenpiteet:
1. Aja Playwright/Selenium-testi (jos repossa on UI-testikehys),
   muuten lisää Pythonin requests + BeautifulSoup -tasoinen testi:
   `tests/test_admin_calendar_clickable.py`:
   a) GET /admin/calendar palauttaa 200.
   b) Rendattu HTML sisältää `id="calendar"` -elementin.
   c) GET /admin/calendar/events.json palauttaa varausjonon (mock-
      datalla).
2. Lisää browser-tason E2E-savutesti
   `tests/integration/test_admin_calendar_e2e.py` (jos Playwright
   tai Chrome-headless saatavilla — muutoin skipataan):
   - Klikkaa varausta solun keskeltä → uusi sivu /admin/reservations/
     <id> avautuu.
   - Klikkaa tyhjää päivää → "Tyhjä päivä" -ilmoitus näkyy.
3. Tarkista CSS:stä että `.fc-event`-elementtien `cursor: pointer` on
   asetettu ja `pointer-events`-arvo ei ole `none`. Lisää tarvittaessa
   `app/static/css/admin.css`-tiedostoon:
   ```
   .fc-event { cursor: pointer; }
   .fc-event * { pointer-events: none; } /* lapset eivät syö klikkiä */
   ```
4. Lisää availability-matriisin solujen koko alueelle
   `display: block; height: 100%`-tyylit jos eivät jo löydy.

Hyväksymiskriteerit:
- Manuaalitesti: klikkaus solun keskellä avaa varauksen.
- Pytest vihreä.
- Ei muutoksia kalenterilogiikkaan tai event-sourceen.

Älä koske drag-and-drop -koodiin (`eventDrop`/`eventResize`).
```

---

## Prompti 10 — Suomenkielistämisen läpikäynti (Pekan kohta 10)

> **ChatGPT-syöte → Cursor-toteutus.** Aja **toisena**, heti kohdan 7
> jälkeen — tämä on suuri laajuus mutta riskitön.

```
Tehtävä: Käy läpi koko Pin PMS:n käyttöliittymä ja varmista että
asiakkaalle näkyvä teksti on suomenkielistä, ei suomi-englanti
sekoitusta. Älä koske tietokantaan tai API:n raw-arvoihin.

Konteksti:
- Asiakas Pekka 2026-05-06: "Kielet suomi-englanti sekaisin."
- `tests/test_ui_finnish.py` valvoo osaa templateista, mutta ei
  kaikkea.
- Statuksen, prioriteetin yms. raw-arvot kannassa pysyvät englantina
  (esim. status="active", priority="high"). Vain käyttäjälle näkyvä
  label vaihtuu.

Toimenpiteet:
1. Listaus: aja
   ```
   grep -rn -E "(?i)\b(status|priority|active|pending|draft|cancelled|paid|overdue|created|updated|low|normal|high|urgent|new|in_progress|waiting|resolved)\b" \
     app/templates/ app/static/
   ```
   ja kerää englanninkieliset käyttäjälle näkyvät jäänteet listaksi.
   Vältä koodikenttiä (data-attribuutit, css-luokat, value-attribuutit).
2. Lisää keskitetty `app/core/i18n.py`-helper:
   ```python
   STATUS_LABELS_FI = {
       "draft": "Luonnos", "active": "Aktiivinen",
       "ended": "Päättynyt", "cancelled": "Peruttu",
       "pending": "Odottaa", "paid": "Maksettu",
       "overdue": "Erääntynyt", "open": "Avoin",
       "new": "Uusi", "in_progress": "Työn alla",
       "waiting": "Odottaa", "resolved": "Ratkaistu",
       "confirmed": "Vahvistettu", "checked_in": "Saapunut",
       "checked_out": "Lähtenyt",
   }
   def status_label(value): return STATUS_LABELS_FI.get((value or "").lower(), value or "-")
   ```
   Rekisteröi se Jinjaan filteriksi:
   `app.jinja_env.filters["status_label"] = status_label`.
3. Korvaa templateissa `{{ row.status }}` → `{{ row.status|status_label }}`
   kaikissa käyttäjälle näkyvissä paikoissa:
   - reservations, leases, invoices, maintenance, payments,
     backups (state-kenttä), webhook-deliveries.
   Älä koske data-attribuutteihin (esim. `data-state="{{ row.status }}"`).
4. Suodattimien dropdownit:
   `<option value="active">Aktiivinen</option>` -muotoon.
5. Sähköpostipohjat: tarkista `app/email/seed/`-pohjien tekstit,
   etenkin notifikaatiopohjat. Jos pohja viittaa `{{ priority }}`,
   vaihda `{{ priority_label }}`-muotoon (kts. Prompti 8).
6. Lokalisaatiotestit:
   `tests/test_ui_finnish.py`-laajennus:
   a) Iteroi listanäkymät (reservations, leases, invoices,
      maintenance, payments) ja varmista että niissä ei näy raw-
      enum-arvoja.
   b) Suodatindropdownit listoissa.
7. Päivitä tyyliopas `docs/ui_finnish_style.md` (luo jos ei ole):
   - Yhden lauseen ohje: "Käyttäjälle näkyvä teksti on suomeksi,
     raw-arvot pysyvät englanniksi."
   - Lista käytetyistä label-mappauksista (vie myös koodista).

Hyväksymiskriteerit:
- Pytest + ui_finnish-testit vihreitä.
- Mikään API-vastauksen JSON-rakenne ei muutu.
- Ulkoiset integraatiot (Stripe, Paytrail, Mailgun, iCal, Pindora
  Lock) eivät rikkoudu — vain käyttäjäteksti vaihtuu.

Älä käännä error-kooditasoa (esim. JSON-virhevastauksen `code`-
kentässä `"unauthorized"`-arvo pysyy). Vain `message`-kenttä on
suomeksi.
```

---

## Yhteenveto työnkulusta

1. **Ensin Prompti 7** — bugifix kalenterisynkkausnäkymästä.
2. **Sitten Prompti 10** — kielten siisteys läpi UI:n.
3. **Prompti 4** — kohteen ja huoneen rikkaiden kenttien UI.
4. **Prompti 2 + Prompti 3** — vapaiden huoneiden pikanäkymät.
5. **Prompti 6** — kassavirtaraportin laajennus.
6. **Prompti 5** — sopparityökalu (suurin, jaa kahteen PR:ään).
7. **Prompti 1** — maksutapojen savutestaus.
8. **Prompti 8 + Prompti 9** — pienet verifikaatiot.

**Hyväksymisportti koko paketille:**
- `pytest -v` vihreä jokaisen promptin jälkeen.
- `pytest tests/integration/ -v` vihreä projektin lopussa.
- README:n "Acceptance criteria"-lista käydään läpi käsin
  Docker-stackissa.
- Asiakkaan 10/10 palautekohta kuitattu: ks.
  SELVITYS_INIT_TEMPLATE_2026-05-07.md osio 2.
