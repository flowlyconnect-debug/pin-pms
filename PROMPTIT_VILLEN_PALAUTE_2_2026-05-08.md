# Promptit Villen palautteen toinen kierros (2026-05-08)

**Tarkoitus:** neljä itsenäistä ChatGPT-syötettä uusiin epäkohtiin, jotka
löydettiin ensimmäisen korjauskierroksen jälkeen 2026-05-08.

**Työnkulku:** Sinä → ChatGPT (*"Hio tästä Cursorille syötettävä tarkka
tehtävänanto, älä lisää skooppia"*) → Cursor → `pytest -v`.

**Suoritusjärjestys:** **A → B → C → D**.
A ja D ovat bugifixejä (notifikaatio-500 ja matriisin päällekkäisyys),
B on kalenterilokalisointi (UI-näkyvä), C on accessibility-sivun
teemautus.

**Havaintojen lähde:** käyttöliittymäkuvakaappaukset 2026-05-08:
1. Kalenterin yläpalkin painikkeet (`today`, `month`, `week`, `list`,
   nuolet) ovat englanniksi ja kahdella eri sinisävyllä.
2. Availability-matriisin solut renderöityvät päällekkäin
   ("Ville Testaaja/ille Testaaja…" leikkautuu ja kaikki teksti on
   punaisella).
3. `/accessibility`-sivu näyttää selaimen oletustyylillä, ei admin-
   teemalla. Ääkköset ovat myös rikkoutuneet (`Tama`, `jarjestelman`,
   `valttamatta` jne.).
4. `/admin/notifications` palauttaa **500 Internal Server Error**.

---

## Prompti A — `/admin/notifications` 500-virheen korjaus

> **ChatGPT-syöte → Cursor-toteutus.** Aja ensin — sivu on rikki.

```
Tehtävä: Reproduce ja korjaa Pin PMS:n /admin/notifications -sivun
500 Internal Server Error.

Konteksti:
- Selain näyttää 2026-05-08: "500 Internal Server Error — Something
  went wrong on our side. The error has been recorded."
- Reitti rekisteröidään blueprintissa app/notifications/routes.py
  ja palvelukerros on app/notifications/services.py.
- Malli on app/notifications/models.py.
- Tämä on todennäköisesti sama luokka virhe kuin aiemmin korjatussa
  iCal-kalenterisynkronointinäkymässä — käsittelemätön exception
  joko service-kutsussa tai templaten renderöinnissä.

Toimenpiteet:
1. Reproduce paikallisesti:
   - docker compose up --build -d
   - flask db upgrade
   - flask seed-demo-data
   - Kirjaudu superadminina, mene /admin/notifications
2. Tarkista lokit:
   - docker compose logs web --tail=200
   - Etsi viimeisin "Traceback" stack trace.
   - Tallenna stack trace tiedostoon BUG_500_NOTIFICATIONS_2026-05-08.md
     repon juureen.
3. Yleisimmät juurisyyt joita tutkia järjestyksessä:
   a) Templatessa (app/templates/admin_notifications.html tai
      app/templates/admin/notifications/list.html) viitataan
      kenttään, jota mallissa ei ole (esim. row.read_at, row.severity).
   b) services.py:ssä iteroidaan None-arvoa
      (Notification.organization_id puuttuu seedistä).
   c) Migraatio puuttuu — tarkista
      `docker compose exec web flask db heads` vs
      `docker compose exec web flask db current`.
   d) Jinja-filtteriä `status_label` (lisätty kohdassa 10) ei ole
      rekisteröity ennen kuin tämä template renderöityy.
4. Korjaa virhe minimaalisesti:
   - Älä piilota poikkeusta try/except-blokkiin.
   - Lisää nullable-tarkistukset palvelukerrokseen.
   - Lisää testit ennen korjausta (TDD).
5. Lisää regressiotestit `tests/test_notifications.py`:
   a) test_notifications_index_renders_when_table_empty — GET
      /admin/notifications palauttaa 200 myös tyhjällä taululla.
   b) test_notifications_index_renders_with_seed_rows — yksi
      seed-rivi → 200.
   c) test_notifications_index_handles_null_optional_fields — rivi
      jossa optional-kenttä on None → 200, ei 500.
6. Käy läpi muut samankaltaiset admin-listanäkymät ja varmista
   että vastaava virhe ei ole odottamassa:
   - /admin/audit
   - /admin/email-queue
   - /admin/webhooks
   - /admin/api-keys
   Lisää smoke-testit `tests/test_admin_pms.py`:n yhteyteen joka GET-
   metodilla varmistaa 200/302-vastauksen jokaiselle reitille
   superadminina.
7. Päivitä BUG_500_NOTIFICATIONS_2026-05-08.md: alkuperäinen virhe,
   juurisyy, korjauksen commit-sha, regressiotestin nimi.

Hyväksymiskriteerit:
- /admin/notifications palauttaa 200 paikallisesti.
- Kaikki uudet ja olemassa olevat testit menevät läpi.
- BUG_500_NOTIFICATIONS_2026-05-08.md dokumentoi syyn ja korjauksen.
- Sentry / Sentry-mock ei kerää uutta poikkeusta tällä reitillä.

Älä lisää uusia kenttiä Notification-malliin tämän promptin sisällä.
Älä koske notifikaatioiden taustatyölogiikkaan (scheduler), vain
admin-näkymä.
```

---

## Prompti B — Kalenterin yläpalkin lokalisointi ja yhtenäinen tyyli

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Suomenkielistä Pin PMS:n /admin/calendar-näkymän FullCalendar-
yläpalkin painikkeet ja yhtenäistä niiden tyylit.

Konteksti:
- Kuvakaappaus 2026-05-08 näyttää: vasemmalla "<", ">" ja "today"-
  painikkeet — kaksi nuolta ovat tummansiniseen, "today" on
  vaaleampaan harmaaseen tyyliin. Oikealla "month / week / list" -
  napit ovat tummalla sinisellä taustalla. Sekä englanninkieliset
  tekstit ("today", "month", "week", "list") että epäkonsistentti
  väritys.
- Asiakas Pekka 2026-05-06: "Kielet suomi-englanti sekaisin."
- Käytössä on FullCalendar v6 (cdn.jsdelivr.net/npm/fullcalendar@6.1.15)
  joka tukee `locale: 'fi'` ja `buttonText`-overridea.
- Konfiguraatio on app/static/js/admin-calendar.js, headerToolbar
  rivillä noin 98–102.

Toimenpiteet:
1. Lisää FullCalendar-kalenteriin suomi-lokaali. Kaksi vaihtoehtoa:
   a) Lataa locale-fi-tiedosto CDN:stä:
      `<script src="https://cdn.jsdelivr.net/npm/fullcalendar@6.1.15/locales/fi.global.min.js"></script>`
      ja konfiguroi `locale: 'fi'`.
   b) Tai inlinee buttonText:
      ```js
      buttonText: {
        today: "Tänään",
        month: "Kuukausi",
        week:  "Viikko",
        day:   "Päivä",
        list:  "Lista"
      },
      locale: "fi"
      ```
   Suositus: vaihtoehto (a) — tämä korjaa myös kuukausien ja
   viikonpäivien nimet samalla.
2. Päivitä `app/templates/admin/calendar.html` lisäämällä locale-
   skripti samaan `head_extra`-blockiin missä FullCalendar-core on
   ladattu, **ennen** admin-calendar.js-tiedostoa.
3. Yhtenäistä painikkeiden tyylit:
   - Tarkista app/static/css/fullcalendar-overrides.css (jos olemassa)
     tai lisää overridet app/static/css/admin.css-tiedostoon:
     ```css
     .fc .fc-button-primary,
     .fc .fc-button-primary:disabled {
       background-color: var(--color-primary);
       border-color: var(--color-primary);
       color: var(--color-primary-contrast, #fff);
     }
     .fc .fc-button-primary:hover {
       background-color: var(--color-primary-hover);
       border-color: var(--color-primary-hover);
     }
     .fc .fc-button-primary:not(:disabled).fc-button-active {
       background-color: var(--color-primary-active);
     }
     ```
     Tarkista käytetyt CSS-muuttujat src/styles/tokens.css tai
     app/static/css/tokens.css ja käytä niitä.
4. Tarkista myös päivien otsikot ("Mon", "Tue", …) renderöityvät
   suomeksi ("Ma", "Ti", …) locale-asetuksen ansiosta.
5. Lisää testit:
   `tests/test_admin_calendar.py`:
   a) test_calendar_template_loads_finnish_locale — HTML sisältää
      `fullcalendar/.../locales/fi` -script-srcn.
   b) test_calendar_template_uses_fi_locale_string — admin-calendar.js
      tai inline-koodi sisältää `locale: "fi"`.
6. Manuaalitesti: avaa /admin/calendar — painikkeet "Tänään / Kuukausi
   / Viikko / Lista", viikonpäivät ma–su, kuukauden nimi suomeksi
   (esim. "Toukokuu 2026").

Hyväksymiskriteerit:
- Kaikki painikkeet näkyvät yhdellä yhtenäisellä värillä (ei kahta
  sinisävyä).
- Tekstit suomeksi: "Tänään", "Kuukausi", "Viikko", "Lista", nuolet
  pysyvät symboleina.
- Pytest vihreä.
- tests/test_ui_finnish.py ei valita uusia jäänteitä.

Älä koske kalenterin event-sourceen tai drag-and-drop -koodiin.
Älä päivitä FullCalendar-versiota.
```

---

## Prompti C — Saavutettavuusseloste-sivu admin-/portal-teemaan

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Tee Pin PMS:n /accessibility -sivusta visuaalisesti
yhtenäinen muun sovelluksen kanssa ja korjaa rikkoutuneet ääkköset.

Konteksti:
- Kuvakaappaus 2026-05-08: sivu renderöityy selaimen oletustyylillä
  (Times New Roman, mustavalkoinen, ei marginaaleja eikä korttia).
  Tekstissä on rikkoutuneet ääkköset:
  "Tama seloste koskee Pin PMS -jarjestelman admin-paneelia ja
   vierasportaalia." pitäisi olla
  "Tämä seloste koskee Pin PMS -järjestelmän admin-paneelia ja
   vierasportaalia."
- Template on app/templates/accessibility.html. Se on **erillinen
  HTML-runko** (ei extendaa base-templatea), latauttaa vain portal.css
  ja skip-link.css.
- Muut portal-sivut (esim. app/templates/portal/dashboard.html)
  käyttävät app/templates/portal/base.html -pohjaa.

Toimenpiteet:
1. Korjaa template extendaamaan portal-base:
   ```jinja
   {% extends "portal/base.html" %}

   {% block title %}Saavutettavuusseloste · Pin PMS{% endblock %}

   {% block content %}
     <article class="content-card accessibility-statement">
       <h1>Saavutettavuusseloste</h1>
       <p>Tämä seloste koskee Pin PMS -järjestelmän admin-paneelia
          ja vierasportaalia.</p>

       <h2>Saavutettavuuden tila</h2>
       <p>Palvelu pyritään pitämään WCAG 2.1 AA -tason mukaisena.</p>

       <h2>Havaitut rajoitukset</h2>
       <p>Kaikkia yksittäisiä sivuja ei välttämättä ole vielä
          validoitu manuaalisesti ruudunlukijalla.</p>

       <h2>Palautekanava</h2>
       <p>Jos huomaat saavutettavuuspuutteen, ilmoita siitä
          sähköpostitse:
          <a href="mailto:support@pinpms.example">support@pinpms.example</a></p>

       <h2>Päivitys</h2>
       <p>Seloste päivitetty:
          {{ now().strftime('%Y-%m-%d') if now is defined else '2026-05-06' }}</p>
     </article>
   {% endblock %}
   ```
2. Varmista, että tiedosto tallennetaan **UTF-8 ilman BOMia**. Jos
   template editori on jossain vaiheessa kirjoittanut Latin-1:tä,
   tulos näkyy "Tama / valttamatta" -muodossa. Pakota UTF-8:
   - Lisää linterin tai pre-commit-hookin tarkistus
     `app/templates/**/*.html` -tiedostoille.
   - Tai aja kerran:
     `python -c "p='app/templates/accessibility.html'; data=open(p,'rb').read(); open(p,'wb').write(data.decode('latin-1').encode('utf-8'))"`
     vain jos diff näyttää järkevältä.
3. Tarkista, että reitti `/accessibility` on linkitetty portal-base:n
   alatunnisteessa (footer) tai admin-base:n alatunnisteessa.
4. Lisää testit `tests/test_accessibility.py`:
   a) test_accessibility_page_extends_portal_base — GET /accessibility
      sisältää portal-base:n yhteisen elementin (esim.
      `<nav class="portal-nav">` tai `<a class="skip-link">`).
   b) test_accessibility_page_has_correct_finnish_chars — vastaus
      sisältää merkkijonon "Tämä" ja "järjestelmän".
   c) test_accessibility_page_status_200 — GET palauttaa 200, ei
      vaadi kirjautumista.

Hyväksymiskriteerit:
- /accessibility renderöityy samalla teemalla kuin /portal/dashboard.
- Kaikki ääkköset renderöityvät oikein (ä, ö, å).
- Pytest vihreä.
- Manuaalitesti: avaa selaimessa, vertaa /portal/dashboard-sivuun —
  taustaväri, fontti, marginaalit ja kortin reuna ovat samat.

Älä muokkaa portal/base.html:ää tämän promptin alla.
Älä lisää uusia CSS-luokkia ennen kuin olet varmistanut että
portal-base:n .content-card riittää.
```

---

## Prompti D — Availability-matriisin solujen päällekkäisyys

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Korjaa Pin PMS:n /admin/availability -matriisinäkymässä
solujen sisällön päällekkäisyys ja punainen virhetyyli normaaleille
varauksille.

Konteksti:
- Kuvakaappaus 2026-05-08 näyttää: kohteen "Pindora toimisto" rivillä
  varatun varauksen vieraan nimi "Ville Testaaja" on toistunut
  jokaisessa solussa ja teksti leikkaa edellisen ja seuraavan päivän
  solun läpi muodostaen "Ville Testaaja/ille Testaaja…" -ketjun.
  "Pindora varasto" -rivin "Vapaa"-tekstit ovat punaisella.
- Templaten lähde: app/templates/admin/availability.html
  rivit 76–110 (Vapaa/Varattu/Vaihto/Saapuu/Huolto/Estetty -solut).
- Tyylit: app/static/css/admin.css ja
  app/static/css/portal.css; mahdollisesti
  app/templates/admin/availability.html sisältää inline-tyylejä.
- Selitteet (Vapaa/Varattu/...) ovat "availability-legend"-blockissa
  rivit 46–53 ja niillä on omat värisävyt.

Toimenpiteet:
1. Tutki nykytila:
   - Lisää tilapäisesti `<style>` debugointikäyttöön ja varmista
     että solujen `<td>` saa luokan `availability-status-reserved`,
     `-free`, `-checkin`, `-checkout`, `-maintenance`, `-blocked`.
   - Tarkista app/static/css/admin.css ja portal.css:
     onko `.availability-status-*` -tyylejä määritelty?
2. Lisää tai korjaa CSS-säännöt (admin.css):
   ```css
   .availability-table { table-layout: fixed; width: 100%; }
   .availability-table th,
   .availability-table td {
     overflow: hidden;
     text-overflow: ellipsis;
     white-space: nowrap;
     padding: 0.4rem 0.5rem;
     border-bottom: 1px solid var(--color-border, #e5e7eb);
   }
   .availability-table .availability-sticky-col {
     position: sticky; left: 0; background: #fff; z-index: 1;
     min-width: 180px;
   }
   .availability-status-free      { background: #ecfdf5; color: #047857; }
   .availability-status-reserved  { background: #dbeafe; color: #1e40af; }
   .availability-status-checkin   { background: #d1fae5; color: #065f46; }
   .availability-status-checkout  { background: #fed7aa; color: #9a3412; }
   .availability-status-maintenance { background: #fef3c7; color: #92400e; }
   .availability-status-blocked   { background: #f3f4f6; color: #374151; }
   .availability-table a { color: inherit; text-decoration: none; }
   .availability-table a:hover { text-decoration: underline; }
   ```
   Värit on otettu legend-osion swatcheistä — tarkista että ne
   matchaavat (`.availability-legend-swatch--free` jne.).
3. Poista mahdollinen punainen `color: red` -overridelinja, jos
   sellainen on jäänyt CSS:ään virheviestien tyylistä.
4. Varmista että td:n sisällä oleva `<a>`-elementti ei vuoda solun
   yli: `display: block; width: 100%; height: 100%`.
5. Solun sisältö "Ville Testaaja"-tapauksessa: varaus-soluissa pitää
   näkyä vieraan nimi VAIN ensimmäisessä solussa varauksen alkaen,
   tai joka solu mutta ellipsin kanssa. Yksinkertainen ja luettava
   versio:
   ```jinja
   {% elif status == "reserved" %}
     <td class="{{ cell_class }}" title="{{ day.guest }} · Varaus #{{ day.reservation_id }}">
       <a href="{{ url_for('admin.reservations_edit', reservation_id=day.reservation_id) }}">
         {% if day.is_first_day %}{{ day.guest }}{% endif %}
       </a>
     </td>
   ```
   - Lisää backendin `compute_availability_matrix`-funktioon
     `is_first_day`-lippu (= start_date == day_iso).
   - Solun title-attribuutti pitää sisältää aina koko nimi
     (hover-tooltip).
6. Lisää testit:
   `tests/test_availability.py`:
   a) test_availability_matrix_marks_first_day_only — varaus 3 päivää,
      vain ensimmäisellä päivällä `is_first_day=True`.
   b) test_availability_view_renders_no_overlapping_text — GET
      /admin/availability palauttaa HTML:n jossa solujen sisäisten
      `<a>`-elementtien tekstipituus on max 24 merkkiä yhdellä
      rivillä. (Käytä BeautifulSoupia.)
7. Manuaalitesti:
   - flask seed-demo-data
   - Luo varaus jossa vieras "Ville Testaaja" 5 päiväksi
   - Avaa /admin/availability — vieraan nimi näkyy vain ensimmäisessä
     solussa, muut solut näyttävät tyhjää värisävyllä.
   - Punainen ei saa näkyä missään (paitsi mahdollisesti error-
     bannerissa, joka ei kuulu tähän näkymään).

Hyväksymiskriteerit:
- Solut eivät leikkaa toistensa yli.
- Värit vastaavat sivun yläosan legendiä (Vapaa = vihreä, Varattu =
  sininen, Saapuu = vihreä, Vaihto = oranssi, Huolto = keltainen,
  Estetty = harmaa).
- Pytest vihreä.

Älä rakenna uutta kalenterikomponenttia. Käytä olemassa olevaa
matriisi-templatea.
Älä muuta /admin/calendar (FullCalendar) -näkymää.
```

---

## Yhteenveto työnkulusta

1. **Prompti A — bugifix** (notifications 500). Aja ensin, sivu on
   rikki.
2. **Prompti D — bugifix** (matriisi). Aja toisena, koska
   asiakas-katselu on rikki visuaalisesti.
3. **Prompti B — kalenterin lokaali ja tyyli.**
4. **Prompti C — saavutettavuussivu teemaan.**

Jokaisen promptin jälkeen:
- `pytest -v`
- `pytest tests/integration/ -v` (jos Docker saatavilla)
- Manuaalinen savutesti relevantilla sivulla ennen seuraavaan
  promptiin siirtymistä.
