# Vastaus Villen palautteeseen — toimintasuunnitelma

**Päivämäärä:** 5.5.2026
**Lähde:** Ville (Pekka Rintamäen tiimistä) testasi PMS:n

## Villen palautteen luokittelu

### KRIITTISET (estävät käytön — korjaa heti)

| # | Puute | Vaikutus |
|---|-------|----------|
| 1 | **Saatavuus-näkymä puuttuu** — ei pysty näkemään helposti mikä huone on vapaana / varattu | Asiakaspalvelu mahdotonta puhelimessa |
| 2 | **Huoltopyyntö rikki** — kriittisyys-dropdown vain englanniksi (low/medium/high jne.) | Käyttäjä ei pysty luomaan huoltopyyntöä |
| 3 | **500-virhe kalenterisynkkaus-näkymässä** | Sivu kaatuu |

### TÄRKEÄT (UX-ongelmia — hidastaa työtä)

| # | Puute | Vaikutus |
|---|-------|----------|
| 4 | **Kielet sekaisin** suomi/englanti UI:ssa | Sekoittaa käyttäjää |
| 5 | **Kalenterimerkinnät** klikattavissa vain pienestä ikonista rivin päästä | Hidasta käyttöä |
| 6 | **Kohteet/huoneet liian niukka data** — ei sijaintia, neliöitä, ominaisuuksia | Myyjä ei voi kuvata kohdetta |

### LAAJENNUKSET (vaaditaan ammattitasolle, mutta eivät estä nykyistä käyttöä)

| # | Puute | Vaikutus |
|---|-------|----------|
| 7 | **Raportit liian simppelit** — ei kassavirtaa, ei kuluja | Ei nähdä taloutta |
| 8 | **Sopparit yksinkertaisia** — riittääkö "ammattimaiseen kiinteistöhallintaan"? | Riippuu segmentistä |

---

## Strateginen kysymys: kenelle tämä on?

Villen kommentti on tärkeä:

> "Riippuu mitä haetaan, mutta on tuossa aihio molempiin ja varmaan tarkoitus ei ollut rakentaa airbnb hostille vaan JM Suomi tyyppiselle asiakkaalle?"

JM Suomi -tyyppiset asiakkaat = **pitkäaikaisvuokraus** (asuntoja, kämppäkohteita yritysvuokraukseen). Tämä eroaa lyhytaikaismajoituksesta (Airbnb / Booking.com) merkittävästi:

|  | Lyhytaikainen (Eviivo-tyyppi) | Pitkäaikainen (Tampuuri-tyyppi) |
|---|---|---|
| Vuokra-aika | 1-30 yötä | 6 kk – useita vuosia |
| ALV | Kyllä (10 % majoitus) | EI (vapautettu) |
| Channel manager | Kriittinen (Booking, Airbnb) | Ei tarvita |
| Hinnoittelu | Dynaaminen (kausi, viikonloppu) | Kuukausivuokra + indeksi |
| Sopimukset | Lyhyt vahvistus | Kompleksi vuokrasopimus + lisäliitteet |
| Maksut | Etukäteen kortilla | Kuukausilaskutus tilisiirrolla |
| Saatavuus | Reaaliaikainen | Vuokrasuhteet kestävät pitkään |
| Vieras-portaali | Self-check-in | Vuokralais-portaali (ilmoita vika, lue tiedotteet) |
| Huolto | Siivous-keskeinen | Korjaukset, putkistovuoto, jne. |
| Raportit | Occupancy %, ADR, RevPAR | Kassavirta, ALV-erottelua ei, indeksitarkistukset |

**Pindora PMS toteutetussa muodossa on hybridi joka kallistuu lyhytaikaiseen** (Stripe/Paytrail-maksut, Channex-suunnitelma, ALV-erittely). Mutta jos asiakas (Pekka/JM Suomi) on **pitkäaikaiseen tähdättynä**, useita pitkä-roadmapin promptiajatuksia (8H Channel manager, dynaaminen hinnoittelu) ovat **väärin priorisoituja**.

### Mitä kysytään asiakkaalta

Lähetä Pekkalle vastaus jossa:

1. **Vahvista segmentti**: "Onko ensisijainen asiakaskunta lyhytaikamajoittajat vai pitkäaikaisvuokraajat (esim. JM Suomi -tyyppinen)?"
2. Jos pitkäaikainen → roadmap muuttuu radikaalisti: ei tarvita Channex/Booking.com, ei dynaamista hinnoittelua. Sen sijaan keskitytään: **vuokrasopimusten kompleksoittaminen, indeksitarkistus, kuukausilaskutus, kassavirta-raportit, vuokralais-portaali**.
3. Jos hybridi → segmentoitava per organisaatio settings-tasolla, tehdään molempia rinnakkain.

Älä aloita Prompt 8H:ta (Channel manager) tai 8G:tä (dynaaminen hinnoittelu) ennen tätä vastausta — ne voivat olla väärää työtä.

---

## Korjausjärjestys

Tee SEGMENTISTÄ RIIPPUMATTA nämä ensin (kaikki segmentit hyötyvät):

### Vaihe 1 — Pikakorjaukset (1 päivä Cursorilla)

1. **Prompt FIX-1: Suomennus + 500-virhe** — kaikki UI suomeksi, kalenterisynkkaus-virhe selvitetty + korjattu
2. **Prompt FIX-2: Saatavuus-näkymä** — visuaalinen huone × päivä -matriisi etusivulle / kalenterille

### Vaihe 2 — UX-paranteet (2-3 päivää)

3. **Prompt FIX-3: Kohteen ja huoneen lisäkentät** — sijainti, neliöt, ominaisuudet (hissi, parveke, keittiö, kylpyhuone, jne.)
4. **Prompt FIX-4: Kalenteri klikattava koko rivin alueelta**

### Vaihe 3 — Raportit (riippuu segmentistä)

5. **Prompt FIX-5: Kassavirta + tulot/kulut-raportit** (sama kummallekin segmentille)
6. **Prompt FIX-6: Sopparipohja-järjestelmä** (segmentti-spesifit pohjat)

### Vaihe 4 — vasta sitten roadmappia jatketaan

Kun yllä olevat ovat tehty + asiakas on vahvistanut segmentin, päätetään 8H/8I/8J/8K/8L-järjestys.

---

## Cursor-promptit kriittisille korjauksille

### PROMPT FIX-1 — Suomennus + 500-virhe kalenterisynkkauksessa

```
Tehtävä Cursorille: Korjaa kielet (UI sekaisin suomi/englanti), suomenna huoltopyyntö-kriittisyys-dropdown, ja tutki/korjaa 500-virhe kalenterisynkkausnäkymässä.

Tausta: Ville (asiakas-tester) raportoi:
1. UI:n kielet sekaisin (suomi/englanti samalla sivulla)
2. Huoltopyyntöä ei voi tehdä koska kriittisyys-dropdown näyttää englanninkielisiä termejä (low/medium/high) ja käyttäjä odottaa suomea
3. /admin/calendar-sync-conflicts (tai vastaava) heittää 500-virheen

Init-template §13 (UI selkeä), §15 (virheenkäsittely).

Vaihe 1: Kalenterisynkkaus-virheen tutkinta
1. Avaa /admin/calendar-sync-conflicts (tai vastaava — käytäjä mainitsi "kalenterisynkkausnäkymä")
2. Aja paikallisesti: flask run, kirjaudu superadminina, navigoi ko. sivulle
3. Tarkista konsolista (terminal) traceback
4. Tarkista myös /api/v1/health/ready ja /api/v1/health
5. Korjaa juurisyy:
   - Mahdollinen syy 1: tyhjä iCal-feed listaus → loop kaatuu
   - Mahdollinen syy 2: organization-isolation puuttuu jonkin kyselyn yhteydessä
   - Mahdollinen syy 3: scheduler-job ei ole käynnissä mutta UI yrittää lukea sen tilaa

Vaihe 2: UI-kieli-sekaisin
1. Aja: grep -rn "Cancel\|Save\|Delete\|Edit\|Create\|Submit\|Reset\|Confirm\|Send\|Loading" app/templates/ | head -30
2. Listaa kaikki englanninkieliset napit/labelit
3. Suomennoksia (käytä yhtenäisiä):
   - Cancel → Peruuta
   - Save → Tallenna
   - Delete → Poista
   - Edit → Muokkaa
   - Create → Luo
   - Submit → Lähetä
   - Reset → Tyhjennä
   - Confirm → Vahvista
   - Send → Lähetä
   - Loading → Ladataan
   - Yes → Kyllä
   - No → Ei
   - Search → Hae
4. Tarkista myös: päivämääräformaatti pitää olla "5.5.2026" eikä "5/5/26"

Vaihe 3: Huoltopyynnön kriittisyys-dropdown
1. Etsi: app/maintenance/models.py — MaintenanceRequest-malli
2. Etsi: priority/severity/criticality-enum
3. Jos arvot ovat esim. ["low", "medium", "high", "urgent"] niin:
   - Joko a) suomenna template-tasolla {% if request.priority == "low" %}Matala{% endif %}
   - Tai b) tallenna enum-arvojen rinnalle suomi-näyttönimi
4. Suositus: tee mallille label-property:
   PRIORITY_LABELS = {
       "low": "Matala",
       "medium": "Keskitaso",
       "high": "Korkea",
       "urgent": "Kiireellinen",
   }
   ja templateissa käytä {{ request.priority_label }}
5. Form-näkymässä dropdown:
   <select name="priority">
     <option value="low">Matala</option>
     <option value="medium">Keskitaso</option>
     <option value="high">Korkea</option>
     <option value="urgent">Kiireellinen</option>
   </select>

Vaihe 4: Audit kaikista templaateista
- Käy läpi KAIKKI app/templates/admin/maintenance/*.html — varmista että UI on suomeksi
- Sama portal-puolella

Vaihe 5: Testit
- tests/test_ui_finnish.py (uusi):
  - test_admin_pages_have_finnish_buttons (haetaan tavallisin button-tekstit, varmistetaan että ne ovat suomeksi)
  - test_maintenance_priority_dropdown_in_finnish
  - test_calendar_sync_page_does_not_500
- tests/test_calendar_sync.py (laajennus jos olemassa):
  - test_calendar_sync_view_renders_when_no_feeds
  - test_calendar_sync_view_renders_when_scheduler_disabled

Tiedostot:
- app/templates/**/*.html (suomennokset)
- app/maintenance/models.py (priority labels)
- app/templates/admin/maintenance/new.html, edit.html (suomennettu dropdown)
- app/admin/routes.py (jos kalenterisynkkauksen korjaus tarvitsee koodia)
- tests/test_ui_finnish.py (uusi)

ÄLÄ:
- Älä käännä tietokantakenttiä (priority="low" pysyy tietokannassa, vain UI-näyttö suomennetaan)
- Älä riko olemassa olevia testejä jotka oletettavasti olettavat englanninkielisiä arvoja
- Älä käännä koodikommentteja tai muuttujanimiä

Aja lopuksi:
1. pytest -v --cov=app --cov-fail-under=80
2. Manuaalitesti: avaa /admin/calendar-sync-conflicts → ei 500-virhettä
3. Manuaalitesti: yritä luoda huoltopyyntö → kriittisyys-dropdown näkyy suomeksi
4. Manuaalitesti: navigoi 5 admin-sivulla → ei englantia näkyvissä
```

---

### PROMPT FIX-2 — Saatavuus-näkymä (huone × päivä -matriisi)

```
Tehtävä Cursorille: Toteuta visuaalinen saatavuus-näkymä jossa näkyy yhdellä silmäyksellä mikä huone on vapaa, varattu tai huollossa, koko organisaation huonemäärällä.

Tausta: Ville (asiakas-tester) raportoi:
- "ainakaan vielä en löytänyt helppoa näkymää mitkä huoneet ovat vapaana tai varattuna"
- "huone-status löytyy Etusivulta, mutta vain listana ja siinä on aika plärääminen"
- "jos vaikka puhelimessa hustlaisin toimistoa jollekin, niin helpottaisi nähdä mitä on vapaana missäkin"

Tämä on KRIITTINEN puute — moderni PMS näyttää saatavuuden visuaalisesti GANTT-tyylisenä matriisina (huoneet rivinä, päivät sarakkeena).

Init-template §13 (UI), §14 (suorituskyky), §20 (service-kerros).

Vaihe 1: Service-funktio (app/reservations/services.py)
- Uusi funktio:
  def availability_matrix(*, organization_id: int, start_date: date, end_date: date, property_id: int | None = None) -> dict
- Palauttaa:
  {
    "properties": [
      {
        "id": 1, "name": "Talo A",
        "units": [
          {
            "id": 10, "name": "101", "type": "double",
            "days": [
              {"date": "2026-05-05", "status": "free"},
              {"date": "2026-05-06", "status": "reserved", "guest": "Matti M.", "reservation_id": 42},
              {"date": "2026-05-07", "status": "reserved", "guest": "Matti M.", "reservation_id": 42},
              {"date": "2026-05-08", "status": "checkout"},   # vain check-out-päivä
              {"date": "2026-05-09", "status": "maintenance", "request_id": 7},
              ...
            ]
          },
          ...
        ]
      },
      ...
    ],
    "date_range": ["2026-05-05", ..., "2026-05-19"]  # 14 päivää
  }
- Status-arvot: "free", "reserved", "checkout" (saapuu uusi vieras samana päivänä), "checkin" (vieras lähtee), "maintenance", "blocked"
- Tehokas SQL-kysely: yksi query per organization_id, hae varaukset date-overlap-ehdolla

Vaihe 2: Reitti (app/admin/routes.py)
- @admin_bp.route("/availability")
- @require_admin_pms_access
- Parametrit URL:ssa: ?from=2026-05-05&days=14&property_id=...
- Default: from = today, days = 14
- Renderöi templates/admin/availability.html

Vaihe 3: Template (templates/admin/availability.html)
- Otsikko: "Saatavuus" + päivämääräväli
- Päivämäärävalitsin yläpuolella + "Edellinen 7 päivää" / "Seuraava 7 päivää" -painikkeet
- Property-suodatin (jos useita kohteita)
- Iso taulukko:
  - Vasen sarake: Kohde / Yksikkö (sticky)
  - Yläsarake: Päivät (Ti 5.5, Ke 6.5, ...)
  - Solut: värikoodattu status
    - Vihreä = Vapaa
    - Punainen = Varattu (näkyy vieraan nimi)
    - Keltainen = Check-in/out -päivä
    - Harmaa = Huolto
    - Tumma = Estetty (admin-blokki)
  - Klikkaus solua → ohjautuu varaukseen tai lomakkeeseen luoda uusi varaus
- Tooltip solussa: vieraan nimi, varaus-ID, klikkaa-tieto

Vaihe 4: Kytke etusivu (dashboard)
- Lisää "Tämän viikon saatavuus" -widget dashboardille (kuten KPI-kortit)
- Pieni preview-versio (top 3 kohdetta × 7 päivää)
- Linkki → täysi /admin/availability

Vaihe 5: Mobiili-ystävällinen
- Mobiilissa: scrollattava sivuttain (ei kasaan litistettynä)
- Sticky vasen sarake (yksikkö-nimi näkyy aina)

Vaihe 6: Performance
- Käytä CSS Grid + lazy-loading
- Päivien lukumäärä rajoitettu (max 31 päivää kerrallaan)
- Caching session-tasolla 30 sekuntia (varaukset eivät muutu sekunnin tasolla)

Vaihe 7: Testit (tests/test_availability.py)
- test_availability_returns_only_own_org
- test_availability_marks_reserved_days
- test_availability_marks_maintenance_days
- test_availability_handles_overlapping_reservations
- test_availability_route_requires_admin_role

Vaihe 8: Sidebar-linkki
- Lisää sivupalkkiin uusi linkki "Saatavuus" (esim. ennen "Kalenteri")
- Käytä esim. emoji 🗓 tai ikoni

Tiedostot:
- app/reservations/services.py (availability_matrix)
- app/admin/routes.py (uusi reitti)
- app/templates/admin/availability.html (uusi)
- app/templates/admin/dashboard.html (widget)
- app/templates/admin/base.html (sidebar-linkki)
- app/static/css/admin.css (saatavuus-matriisi-tyylit)
- app/static/js/admin-availability.js (drag-to-create-feature, vapaaehtoinen)
- tests/test_availability.py (uusi)

ÄLÄ:
- Älä lataa kaikkia varauksia memoryyn — käytä SQL-aggregaatteja
- Älä tee N+1-kyselyä per yksikkö (yksi kysely per pyyntö)
- Älä unohda tenant-isolaatiota
- Älä unohda päivämäärävyöhykettä (käytä organisaation timezone-asetusta)
- Älä piilota cancelled-varauksia jos käyttäjä haluaa nähdä ne (lisää suodatin)

Aja lopuksi:
1. pytest tests/test_availability.py -v
2. Manuaalitesti: luo 3 varausta eri yksiköihin, avaa /admin/availability, näe värikoodattu matriisi
3. Mobiilitesti: pitäisi olla scrollattava ja luettavissa
```

---

### PROMPT FIX-3 — Kohteen ja huoneen lisäkentät

```
Tehtävä Cursorille: Lisää kohteille ja huoneille puuttuvat kentät jotta myyjä voi kuvata kohdetta.

Tausta: Ville: "Kohteista ja huoneista voi kertoa nyt aika vähän. Myyjää mahdollisesti helpottaisi, jos olisi oma slotti huoneen sijainnille, neliöille ja muut kohteen tai huoneen ominaisuudet: hissit, keittiöt tms."

Vaihe 1: Property-malliin uusia kenttiä
- city (string 100, indexed) — esim. "Helsinki"
- postal_code (string 10) — esim. "00100"
- street_address (string 200) — koko osoite
- latitude, longitude (Numeric, nullable) — kartta-näkymälle myöhemmin
- year_built (integer, nullable)
- has_elevator (bool, default False)
- has_parking (bool, default False)
- has_sauna (bool, default False)
- has_courtyard (bool, default False)
- description (text, nullable) — vapaa kuvaus
- url (string 500, nullable) — kohteen oma sivusto

Vaihe 2: Unit-malliin uusia kenttiä
- floor (integer, nullable) — kerros (0 = pohjakerros, -1 = kellari)
- area_sqm (Numeric 6,2) — neliöt
- bedrooms (integer, default 0)
- has_kitchen (bool, default False)
- has_bathroom (bool, default True)
- has_balcony (bool, default False)
- has_terrace (bool, default False)
- has_dishwasher (bool, default False)
- has_washing_machine (bool, default False)
- has_tv (bool, default False)
- has_wifi (bool, default True)
- max_guests (integer, default 2) — montako voi yöpyä
- description (text, nullable)
- floor_plan_image_id (FK PropertyImage, nullable) — pohjapiirros (myöhemmin Prompt 8L)

Vaihe 3: Migraatio
- flask db migrate -m "add_property_and_unit_descriptive_fields"

Vaihe 4: Lomakkeet (admin-UI)
- app/templates/admin/properties/new.html, edit.html — lisää kentät
- app/templates/admin/units/new.html, edit.html — lisää kentät
- Ryhmittele:
  - "Sijainti" (city, postal_code, street_address, lat/lng)
  - "Tiedot" (year_built, description)
  - "Ominaisuudet" (has_*-checkboxit)
  - "Mitat" (area_sqm, bedrooms, max_guests)
- Validointi: WTF-forms

Vaihe 5: Detail-näkymät
- app/templates/admin/properties/detail.html — näytä kaikki kentät
- app/templates/admin/units/detail.html — sama
- Vieras-portaalissa unit-detail-näkymässä näkyvät vieraan kannalta relevantit kentät (ei admin-vain-kenttiä kuten cleaning_notes)

Vaihe 6: API-skeemat
- app/api/schemas.py — lisää kentät PropertySchema ja UnitSchema:hen
- API-kutsuissa GET /api/v1/properties/<id> palauttaa kaikki uudet kentät

Vaihe 7: Hakua laajennus
- Hae voi etsiä kaupungista ("Helsinki"), katuosoitteesta, jne. (Prompt 8D:n laajennus)

Vaihe 8: Testit
- test_property_create_with_all_fields
- test_unit_with_features_serialized_correctly
- test_property_search_by_city
- test_unit_max_guests_validation

Tiedostot:
- app/properties/models.py
- migrations/versions/*.py
- app/templates/admin/properties/*.html
- app/templates/admin/units/*.html
- app/templates/portal/unit_detail.html
- app/api/schemas.py
- app/admin/forms.py
- tests/test_properties_extended.py

ÄLÄ:
- Älä riko olemassa olevia varauksia (uusi sarake nullable=True ja default-arvot)
- Älä unohda lokalisoituja merkintöjä (sauna käännetään myöhemmin Prompt 8I:ssä — älä kovakooda "Sauna" käännösfunktion ulkopuolelle)

Aja lopuksi:
1. flask db upgrade
2. pytest -v
3. Manuaalitesti: luo Property kaikilla kentillä, varmista että detail-näkymä näyttää ne
```

---

### PROMPT FIX-4 — Kalenterimerkinnät klikattavissa koko rivin alueelta

```
Tehtävä Cursorille: Tee kalenterissa merkinnät klikattavaksi mistä tahansa solun alueelta, ei pelkästään pienestä ikonista.

Tausta: Ville: "kalenterimerkinnät aukeaisi klikkaamalla mihin vain kohtaa saraketta eikä sieltä ihan rivin päästä pientä ikonia painamalla"

Vaihe 1: Tutki nykyinen toteutus
1. app/templates/admin/calendar.html — etsi miten event renderöidään
2. app/static/js/admin-calendar.js — etsi click-handlerit
3. Onko FullCalendar käytössä? Onko event:lle määritelty eventClick?

Vaihe 2: Korjaa
- Jos FullCalendar: aseta options:
  eventClick: function(info) {
      window.location.href = '/admin/reservations/' + info.event.id;
  }
- Jos custom-toteutus: lisää click-handler koko event-elementtille (ei vain pienille ikoneille)

Vaihe 3: Mobiili-touch
- Tap-tuen on toimittava (touchstart-eventit eivät ole tarpeen FullCalendar:ssa, mutta varmista oma toteutus)

Vaihe 4: Hover-tooltip
- Kun kursori on event:n päällä → näytä tooltip jossa: vieraan nimi, varaus-ID, päivät
- Käytä title-attribuuttia tai HTML-tooltipia

Vaihe 5: Testit
- test_calendar_event_click_navigates_to_reservation_detail (Selenium tai vastaava — voit ohittaa jos liian raskas)
- Vähintään: test_calendar_renders_clickable_events (HTML sisältää data-href tai onclick)

Tiedostot:
- app/templates/admin/calendar.html
- app/static/js/admin-calendar.js

ÄLÄ:
- Älä riko olemassa olevia eventClick-toimintoja
- Älä unohda saavutettavuutta (event pitää olla saavutettavissa Tab-näppäimellä)

Aja lopuksi:
1. Manuaalitesti: avaa /admin/calendar, klikkaa varauksen mistä tahansa kohdasta → avautuu varaus-detail
```

---

### PROMPT FIX-5 — Kassavirta ja tulot/kulut-raportit

```
Tehtävä Cursorille: Lisää kassavirta- ja tulot-/kulut-raportit /admin/reports-näkymään.

Tausta: Ville: "Käyttöasteraportti ja varausraportti aika simppelit, toivoisin rahaan ja kassavirtaan liittyvää dataa"

Vaihe 1: Service (app/reports/services.py)
- cash_flow_report(organization_id, start_date, end_date, group_by='month'):
  Returns:
  {
    "groups": [
      {"label": "2026-01", "income": 12000, "expenses": 3000, "net": 9000},
      {"label": "2026-02", ...},
      ...
    ],
    "totals": {"income": 36000, "expenses": 9000, "net": 27000}
  }
- income_breakdown_report — tulojen erittely (laskutyypit: vuokra, palvelumaksut, depositit)
- expenses_breakdown_report (jos kuluja seurataan tällä hetkellä — todennäköisesti EI ole kuluja-mallia, lisää se):
  - Uusi malli Expense (id, organization_id, property_id, category, amount, vat, date, description, payee, attached_invoice_id)

Vaihe 2: Expense-malli + UI
- /admin/expenses — lista
- /admin/expenses/new — luo (kategoria, summa, ALV, päivämäärä, kuvaus)
- Kategoriat: cleaning, maintenance, utilities, insurance, taxes, marketing, other
- Migraatio

Vaihe 3: Raporttien UI
- /admin/reports — listaa kaikki raportit
- Per raportti: päivämääräväli, kohde-suodatin, näytä tuloksena taulukko + Chart.js-graafi
- Vienti CSV/XLSX

Vaihe 4: KPI-laajennus dashboardille
- Lisää KPI-kortit:
  - "Tulot tässä kuussa" (vrt. edellinen)
  - "Kulut tässä kuussa"
  - "Nettokassavirta"

Vaihe 5: Testit
- test_cash_flow_report_groups_by_month
- test_income_breakdown_excludes_cancelled_invoices
- test_expense_create_audits
- test_reports_tenant_isolation
- test_reports_export_csv

Tiedostot:
- app/reports/services.py (laajennus)
- app/expenses/ (uusi moduuli: __init__, models, services, routes)
- app/admin/routes.py
- app/templates/admin/reports/*.html
- app/templates/admin/expenses/*.html
- migrations/versions/*.py
- tests/test_cash_flow.py
- tests/test_expenses.py

ÄLÄ:
- Älä unohda ALV-erottelua (käytä Prompt 5:n vat_rate, vat_amount)
- Älä laske cancelled-laskuja tuloihin
- Älä unohda tenant-isolaatiota

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_cash_flow.py tests/test_expenses.py -v
3. Manuaalitesti: lisää kuluja, avaa /admin/reports/cash-flow, näe graafi
```

---

## Ehdotus järjestykseksi

Aja Cursorilla **YKSI prompti per kerta**, tuo tulokset minulle tarkistettavaksi ennen committia, ja siirry seuraavaan:

1. **Päivä 1:** Prompt FIX-1 (suomennus + 500-virhe)
2. **Päivä 1-2:** Prompt FIX-2 (saatavuus-näkymä) — TÄRKEIN, käytetään puhelinvastauksessa
3. **Päivä 2:** Prompt FIX-3 (kohde/huone-kentät) — myyjän työkalu
4. **Päivä 2:** Prompt FIX-4 (kalenterimerkinnät) — pieni mutta tärkeä UX
5. **Päivä 3:** Prompt FIX-5 (kassavirta + kulut) — mahdollistaa ammattitason

Sen jälkeen lähetä Pekkalle / Villelle uusi demo-pyyntö ja kysy:

1. "Korjasimme palautteenne — saatavuus-näkymä, suomennukset, huoltopyyntö, kohde-kentät, raportit. Voisitteko testata uudelleen?"
2. "Onko ensisijainen asiakaskuntanne lyhytaikamajoittajat (Eviivo-tyyppi) vai pitkäaikaisvuokraajat (Tampuuri-tyyppi)?" — tämä ohjaa seuraavat askeleet (channel manager vs. vuokrasopimukset)

---

## Yhteenveto

Villen palaute oli **erittäin arvokas**:
- Tunnisti 3 kriittistä bugia (saatavuus, suomennus, 500-virhe)
- Tunnisti 3 UX-puutetta (kentät, kalenteri, kielten yhtenäistys)
- Antoi strategisen vihjeen segmentistä (JM Suomi -tyyppi)

Tee ensin **5 quick fixiä** (FIX-1 → FIX-5). Sen jälkeen päätä segmentin perusteella seuraavat askeleet (Channel manager vs. vuokrasopimukset + indeksit).

Älä aloita Prompt 8H:ta tai 8G:tä ennen kuin segmentti on selvä — voit tehdä paljon väärää työtä jos suuntaat kohti lyhytaikamajoittajaa ja asiakas on pitkäaikaisvuokraaja.
