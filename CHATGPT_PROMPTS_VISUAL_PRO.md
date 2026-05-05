# Promptit — visuaalinen modernisointi + ammattitaso ennen maksuintegraatiota

Tehty tähän mennessä: 1–7 (CLI/scope/audit/turva/ALV/GDPR/PDF), 7B–7G (idempotency, webhook-runko, CSP-nonce, Sentry, webhook-publisher, email-jonotus). Maksuintegraatio (Prompt 8) odottaa asiakkaan vastausta.

Tämän paketin promptit ovat **irrallisia maksujärjestelmästä** ja noudattavat init-templatea 100 %. Ne tekevät PMS:stä visuaalisesti modernimman ja toiminnallisesti ammattitason.

> Liitä jokainen prompti ChatGPT:lle erikseen. Aja järjestyksessä — myöhemmät käyttävät aiempien tuloksia.

---

## Suositeltu järjestys

1. **Prompt 8A** — Design-järjestelmä (CSS-muuttujat, värit, typografia, komponentit, dark mode)
2. **Prompt 8B** — Dashboard-paranteet (KPI-kortit, mini-graafit, occupancy-meter)
3. **Prompt 8C** — UI-toimivuuspaketti (toast-notifikaatiot, tyhjät tilat, loading states, vahvistusdialogit)
4. **Prompt 8D** — Haku, filtterit ja bulk-actions
5. **Prompt 8E** — Notification center (admin-paneelin sisäinen tapahtumakeskus)
6. **Prompt 8F** — Tag-järjestelmä + kommentit (vieraille, varauksille, kohteille)
7. **Prompt 8G** — Hinnoittelusäännöt (kausi, viikonpäivä, min. yöt, last-minute)

---

## PROMPT 8A — Design-järjestelmä ja moderni visuaali

```
Tehtävä Cursorille: Modernisoi Pindora PMS:n admin-paneelin visuaali design-järjestelmällä joka noudattaa init-templatea.

Tausta: Init-template §13 (käyttöliittymä) sanoo: "yksinkertainen, selkeä, virheviestit selkeitä, vaaralliset toiminnot vaativat vahvistuksen". Nykyinen UI toimii mutta on vanhanaikainen — kortit ovat mata, painikkeet ovat oletustyylisiä, ei dark modea, mobiilinäkymä on perustasoa. Modernisointi pitää tehdä CSS-pohjaisena ilman raskaita kirjastoja (Tailwind/Bootstrap rajoitettuja, FullCalendar pidetään).

Vaihe 1: Design-tokenit (CSS-muuttujat)
- Päivitä app/static/css/admin.css:n :root-osio:

  :root {
    /* Pohjavärit (light mode) */
    --color-bg: #f8f6f2;
    --color-surface: #ffffff;
    --color-surface-2: #f4f1ec;
    --color-border: #e7e2da;
    --color-border-strong: #d4cec5;
    --color-text: #1a1814;
    --color-text-muted: #6b645c;
    --color-text-dim: #9a948a;

    /* Brand */
    --color-primary: #c62828;
    --color-primary-hover: #a31f23;
    --color-primary-soft: #fef2f2;

    /* Tilavärit */
    --color-success: #16a34a;
    --color-success-soft: #f0fdf4;
    --color-warning: #d97706;
    --color-warning-soft: #fffbeb;
    --color-danger: #dc2626;
    --color-danger-soft: #fef2f2;
    --color-info: #2563eb;
    --color-info-soft: #eff6ff;

    /* Typografia */
    --font-sans: -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", Roboto, sans-serif;
    --font-mono: "SF Mono", Monaco, "Cascadia Code", monospace;
    --fs-xs: 0.75rem;
    --fs-sm: 0.875rem;
    --fs-base: 0.9375rem;
    --fs-md: 1rem;
    --fs-lg: 1.125rem;
    --fs-xl: 1.375rem;
    --fs-2xl: 1.75rem;
    --fs-3xl: 2.25rem;

    /* Tila ja muoto */
    --r-sm: 6px;
    --r-md: 10px;
    --r-lg: 14px;
    --r-xl: 20px;
    --shadow-sm: 0 1px 2px rgba(17, 17, 17, 0.04), 0 1px 3px rgba(17, 17, 17, 0.06);
    --shadow-md: 0 4px 12px rgba(17, 17, 17, 0.06), 0 2px 4px rgba(17, 17, 17, 0.04);
    --shadow-lg: 0 12px 32px rgba(17, 17, 17, 0.08), 0 4px 12px rgba(17, 17, 17, 0.06);
    --shadow-focus: 0 0 0 3px rgba(198, 40, 40, 0.18);

    /* Animaatio */
    --t-fast: 0.12s ease;
    --t-md: 0.2s ease;
  }

- Säilytä olemassa olevat --admin-* -muuttujat taaksepäin yhteensopivuuden vuoksi (älä riko vanhoja luokkia).

Vaihe 2: Dark mode
- Lisää CSS:
  @media (prefers-color-scheme: dark) {
    :root {
      --color-bg: #0d0d0c;
      --color-surface: #18181a;
      --color-surface-2: #1f1f22;
      --color-border: #2a2a2e;
      --color-border-strong: #3a3a40;
      --color-text: #f5f5f3;
      --color-text-muted: #a8a39a;
      --color-text-dim: #6e6a62;
      --color-primary: #ef4444;
      --color-primary-hover: #f87171;
      --color-primary-soft: rgba(239, 68, 68, 0.12);
      --color-success-soft: rgba(34, 197, 94, 0.12);
      --color-warning-soft: rgba(217, 119, 6, 0.14);
      --color-danger-soft: rgba(220, 38, 38, 0.14);
      --color-info-soft: rgba(37, 99, 235, 0.14);
    }
  }
- Käyttäjä-asetus joka voittaa OS-preferenssin: settings-tauluun "ui.theme" (light/dark/auto), tallennetaan localStorageen myös toimimaan ennen sessiota
- HUOM: localStorage on KIELLETTY init-templatessa? Tarkista §10 — siellä ei suoraan kielletä, mutta turvallisuussyy on huomioitava. Käytä http-only-cookieä user_pref-asetukselle.

Vaihe 3: Komponenttipohjainen CSS
- Päivitä luokat tämän mallin mukaan (älä poista olemassa olevia, lisää uusia rinnalle):
  .card { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--r-lg); box-shadow: var(--shadow-sm); padding: 1.25rem; }
  .card-elevated { box-shadow: var(--shadow-md); }
  .card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
  .card-title { font-size: var(--fs-lg); font-weight: 600; color: var(--color-text); margin: 0; }

  .btn { display: inline-flex; align-items: center; gap: 0.5rem; padding: 0.55rem 1rem; border-radius: var(--r-md); font-weight: 500; transition: all var(--t-fast); border: 1px solid transparent; cursor: pointer; font-size: var(--fs-sm); }
  .btn-primary { background: var(--color-primary); color: white; }
  .btn-primary:hover { background: var(--color-primary-hover); transform: translateY(-1px); box-shadow: var(--shadow-md); }
  .btn-secondary { background: var(--color-surface); color: var(--color-text); border-color: var(--color-border-strong); }
  .btn-secondary:hover { background: var(--color-surface-2); }
  .btn-danger { background: var(--color-danger); color: white; }
  .btn-ghost { background: transparent; color: var(--color-text-muted); }
  .btn-ghost:hover { background: var(--color-surface-2); color: var(--color-text); }
  .btn-sm { padding: 0.35rem 0.75rem; font-size: var(--fs-xs); }
  .btn-icon { padding: 0.5rem; aspect-ratio: 1; }

  .badge { display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.2rem 0.55rem; border-radius: 999px; font-size: var(--fs-xs); font-weight: 500; }
  .badge-success { background: var(--color-success-soft); color: var(--color-success); }
  .badge-warning { background: var(--color-warning-soft); color: var(--color-warning); }
  .badge-danger { background: var(--color-danger-soft); color: var(--color-danger); }
  .badge-info { background: var(--color-info-soft); color: var(--color-info); }
  .badge-muted { background: var(--color-surface-2); color: var(--color-text-muted); }

- ÄLÄ riko olemassa olevia luokkia (.admin-*, .table-*, jne.) — lisää nämä rinnalle ja käytä uusissa templateissa

Vaihe 4: Lomakkeet
- Modernit input-tyylit:
  input[type="text"], input[type="email"], input[type="password"], input[type="number"], input[type="date"], input[type="datetime-local"], select, textarea {
    width: 100%;
    padding: 0.6rem 0.85rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border-strong);
    border-radius: var(--r-md);
    font-size: var(--fs-base);
    color: var(--color-text);
    transition: border-color var(--t-fast), box-shadow var(--t-fast);
  }
  input:focus, select:focus, textarea:focus {
    outline: none;
    border-color: var(--color-primary);
    box-shadow: var(--shadow-focus);
  }
  label {
    display: block;
    font-size: var(--fs-sm);
    font-weight: 500;
    color: var(--color-text);
    margin-bottom: 0.35rem;
  }
  .form-help { color: var(--color-text-muted); font-size: var(--fs-xs); margin-top: 0.3rem; }
  .form-error { color: var(--color-danger); font-size: var(--fs-xs); margin-top: 0.3rem; }

Vaihe 5: Taulukot
- Modernit taulukot:
  .data-table { width: 100%; border-collapse: separate; border-spacing: 0; background: var(--color-surface); border: 1px solid var(--color-border); border-radius: var(--r-lg); overflow: hidden; box-shadow: var(--shadow-sm); }
  .data-table thead th { padding: 0.85rem 1rem; background: var(--color-surface-2); font-size: var(--fs-xs); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--color-text-muted); text-align: left; border-bottom: 1px solid var(--color-border); }
  .data-table tbody td { padding: 0.85rem 1rem; border-bottom: 1px solid var(--color-border); font-size: var(--fs-sm); }
  .data-table tbody tr:last-child td { border-bottom: 0; }
  .data-table tbody tr:hover { background: var(--color-surface-2); cursor: pointer; }

- Lisää tyhjä-tila ja loading-skeleton
  .table-empty { padding: 3rem 1rem; text-align: center; color: var(--color-text-muted); }
  .table-empty-icon { font-size: 2.5rem; margin-bottom: 0.5rem; opacity: 0.5; }
  .skeleton { background: linear-gradient(90deg, var(--color-surface-2) 0%, var(--color-border) 50%, var(--color-surface-2) 100%); background-size: 200% 100%; animation: skeleton-load 1.5s infinite; border-radius: var(--r-sm); }
  @keyframes skeleton-load { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }

Vaihe 6: Sivupalkin parannus
- Modernit nav-linkit:
  - Aktivoidulle linkille: vasen 3px paksu väripalkki + light tausta
  - Hover-tila pehmeämmäksi
  - Ikonit isommat ja paremmin vertikaalisesti keskitetty
- Sivupalkin alaosaan käyttäjäpaneeli:
  - Avatar (ensimmäisten kirjaimien initialit)
  - Käyttäjän nimi + organisaatio
  - "Asetukset" + "Kirjaudu ulos" -linkit
  - Tämä korvaa nykyisen pelkän "Kirjaudu ulos" -linkin

Vaihe 7: Topbar (mobiilissa) ja desktop-topbar
- Lisää desktop-topbar (uusi):
  - Vasemmalla: sivun otsikko (block content title)
  - Keskellä: pikahaku-input (tyhjä toiminnallisuus, varataan Prompt 8D:lle)
  - Oikealla: notification-bell-ikoni (varataan Prompt 8E:lle), käyttäjä-avatar
- Mobile-topbar säilyy nykyisellään (hampurilainen + otsikko)

Vaihe 8: Vahvistusdialogit
- Korvaa kaikki vaaralliset toiminnot natiivin confirm() sijasta moderniilla modaalidialogilla
- Käytä <dialog> HTML5-elementtiä (tukee modaalia natiivisti)
- Lisää js/admin-confirm.js:
  function confirmAction({title, message, confirmLabel, dangerous}) → Promise<boolean>
  Renderöi <dialog>, palauttaa promisen jolla resolve(true) jos OK, resolve(false) jos peruutus
  Käytä init-templaten §13 kohtaa "vaaralliset toiminnot vaativat vahvistuksen"
- Päivitä esim. käyttäjän poisto, organisaation poisto, varmuuskopion palautus käyttämään tätä
- Säilytä natiivi confirm() varafalbackiksi jos JS ei lataudu

Vaihe 9: Tyhjät tilat (empty states)
- Jokainen lista jolla voi olla 0 riviä saa ystävällisen empty-staten:
  - Iso harmaa ikoni (esim. 📭 ✉️ 🛏 jne.)
  - Otsikkoteksti ("Ei vielä laskuja")
  - Selitys ("Lasku luodaan kun varauksen status muuttuu vahvistetuksi.")
  - Pääpainike toimintaan ("Luo lasku manuaalisesti")

Vaihe 10: Mobiilinäkymä parannuksia
- Card-grid kortteille mobiilissa: 1 sarake
- Taulukot mobiilissa muunnetaan kortti-listaksi:
  - Älä yritä ahtaa 8 saraketta yhteen
  - Renderöi jokainen rivi karttina jossa kentän nimi vasemmalla, arvo oikealla
  - Käytä @media (max-width: 640px) ja CSS Grid
- Painikkeet mobiilissa: täysleveys ja isompi (44x44 px touch target)
- Lomakkeet mobiilissa: input-fontti vähintään 16 px (estää iOS-zoom)

Vaihe 11: Animaatiot ja mikro-vuorovaikutukset
- Sivun siirtymä: fade-in 0.15 s
- Painikkeen hover: translateY(-1px) + shadow-md
- Kortin hover: shadow-md → shadow-lg
- Linkki underline-slide-in efekti
- Toast-notifikaatio liukuu yläoikealta (varataan Prompt 8C)
- Älä lisää liikaa — alle 0.2 s kaikkialla, ei distraktoivaa

Vaihe 12: Testit
- tests/test_admin_visual.py (uusi):
  - test_admin_dashboard_includes_card_class
  - test_admin_login_form_has_modern_input_styles_class
  - test_dark_mode_meta_color_scheme_present (HTML <meta name="color-scheme" content="light dark">)
- tests/test_admin_inline_scripts.py (jo olemassa Prompt 7D:stä) — pitäisi mennä edelleen läpi, älä riko sitä
- Älä lisää testejä jotka snapshot-vertaavat HTML:ää — niiden ylläpito on painajaista

Tiedostot:
- app/static/css/admin.css (suuri päivitys)
- app/templates/admin/base.html (käyttäjä-paneeli, desktop-topbar)
- app/templates/admin/**/*.html (käytä uusia luokkia kun mahdollista)
- app/static/js/admin-confirm.js (uusi)
- app/static/js/admin.js (theme-toggle)
- tests/test_admin_visual.py (uusi)

ÄLÄ:
- Älä asenna Tailwindiä, Bootstrap:ia, MUI:ta tai mitään isoa CSS-frameworkia (init-template §13: "ei raskasta design-järjestelmää")
- Älä riko olemassa olevia testejä
- Älä poista olemassa olevia CSS-luokkia (taaksepäin yhteensopivuus)
- Älä käytä localStoragea jos voit välttää (käytä server-side asetuksia ja cookiesia)
- Älä lisää 'unsafe-inline' CSP:hen
- Älä käytä JS:ää kun pelkkä CSS riittää (esim. dialogin näyttäminen, animaatiot)

Aja lopuksi:
1. pytest -v --cov=app --cov-fail-under=80
2. Manuaalitesti: avaa /admin, /admin/properties, /admin/reservations selaimessa — näyttää modernilta
3. Manuaalitesti dark mode: muuta selaimen prefers-color-scheme dark → sivu vaihtuu tummaksi
4. Manuaalitesti mobiili: avaa puhelimessa tai DevTools-emulaattorissa — kortit ja lomakkeet toimivat
5. Manuaalitesti: poistovahvistus-dialogi avautuu kun yrität poistaa käyttäjän
```

---

## PROMPT 8B — Dashboard-paranteet

```
Tehtävä Cursorille: Modernisoi /admin-etusivu KPI-korteiksi, mini-graafeiksi ja toimintaehdotuksiksi.

Tausta: Nykyinen /admin-etusivu (admin.admin_home) on perustaso. Modernit PMS:t näyttävät heti tärkeimmät mittarit visuaalisesti.

Vaihe 1: KPI-tiedonkeruu (app/admin/services.py dashboard_summary)
- Laajennna dashboard_summary palauttamaan:
  - "kpi": {
      "occupancy_today_pct": float (0-100),
      "occupancy_7d_avg_pct": float,
      "revenue_this_month": Decimal,
      "revenue_last_month": Decimal,
      "active_reservations": int,
      "checkins_today": int,
      "checkouts_today": int,
      "open_invoices": int,
      "overdue_invoices": int,
      "open_maintenance": int,
    }
  - "trend_revenue_30d": [{"date": "2026-04-05", "value": 1234.56}, ...]
  - "trend_occupancy_30d": [{"date": "...", "pct": 78.0}, ...]
  - "upcoming_arrivals": list[Reservation] (seuraavat 7 päivää, max 10)
  - "alerts": list[dict]  # esim. {type: "warning", message: "3 laskua erääntynyt", link: "/admin/invoices?status=overdue"}

Vaihe 2: Template (app/templates/admin/dashboard.html)
- Yläosa: 4 isoa KPI-korttia (käyttöaste, tulot, aktiiviset varaukset, avoimet laskut)
  - Iso luku, alla pieni delta-merkki ("+12 % vs. edellinen kuukausi")
  - Värikoodaus: vihreä jos paranee, punainen jos huononee
- Toinen rivi: 2 mini-graafi-korttia
  - Tulot 30 päivää (line chart)
  - Käyttöaste 30 päivää (area chart)
  - Käytä Chart.js (latataan jsdelivr CDN, jo whitelistissä CSP:ssä)
- Kolmas rivi: 2 saraketta
  - Saapuvat (seuraavat 7 päivää) — kortti per varaus, vieras + huone + päivä
  - Hälytykset / toimintaehdotukset — käyttäjä näkee mitä pitää tehdä

Vaihe 3: Chart.js-init (app/static/js/admin-dashboard.js)
- Hae embedded JSON sivulta: <script type="application/json" id="dashboard-data">{...}</script>
- Renderöi line chartin tulot-graafiin, area chartin käyttöasteeseen
- Käytä CSS-muuttujia värien hakemiseen (getComputedStyle)
- Älä laita värejä kovakoodattuna JS:hen — luetaan CSS:stä

Vaihe 4: Muotoilu
- KPI-kortin numero-fontti = monospace, korkea kontrasti
- Animoitu count-up effekti kun sivu latautuu (0 → tavoitearvo 0.6 sekunnissa) — vapaaehtoinen, älä tee jos hidastaa
- Skeleton-loaderit kun data latautuu

Vaihe 5: Laitteisto-/aikavyöhykehuomautuksia
- Kaikki päivämäärät rendataan käyttäjän aikavyöhykkeellä (organization.timezone tai oletus Europe/Helsinki)
- Pieni teksti graafien yhteydessä: "Aikavyöhyke: Europe/Helsinki"

Vaihe 6: Tarkkuus-tilat
- Jos kohteita < 3 → näytä yhden korttin sijaan ohjeteksti "Lisää kohteet ensin"
- Jos varauksia < 5 → graafit jätetään pois, näytetään "Liian vähän dataa graafiin"

Vaihe 7: Permissions
- Admin näkee vain oman organisaationsa luvut
- Superadmin näkee organization-vaihtimen ylhäällä, voi katsoa minkä tahansa orgin lukuja
- Tenant-isolation enforced backendillä, ei frontendillä (init-template §12)

Vaihe 8: Testit
- tests/test_admin_dashboard.py (laajennus tai uusi):
  - test_kpi_calculations_use_organization_filter
  - test_kpi_revenue_excludes_cancelled_reservations
  - test_dashboard_does_not_query_other_orgs
  - test_dashboard_renders_skeleton_when_data_missing
  - test_dashboard_renders_chart_data_as_json (varmistaa että Chart.js saa raakadataa)

Tiedostot:
- app/admin/services.py (dashboard_summary laajennus)
- app/admin/routes.py (admin_home muokkaus)
- app/templates/admin/dashboard.html (uusi rakenne)
- app/static/js/admin-dashboard.js (uusi)
- app/static/css/admin.css (KPI-kortti-tyylit)
- tests/test_admin_dashboard.py (uudet testit)

ÄLÄ:
- Älä lähetä raakaa SQL-kyselyä frontendiin (laske kaikki backendissä)
- Älä unohda tenant-isolaatiota
- Älä cachee KPI-arvoja yli 5 minuuttia (käyttäjä haluaa nähdä tuoretta dataa)
- Älä lisää 3rd-party analytics-kirjastoja (Google Analytics, Mixpanel) — init-template ei niitä mainitse, ja PMS-data on arkaluonteista
- Älä tee N+1 -kyselyitä trendi-laskelmissa (käytä SQL aggregaatteja)

Aja lopuksi:
1. pytest tests/test_admin_dashboard.py -v
2. Manuaalitesti: avaa /admin, näe KPI-kortit, mini-graafit
3. Tarkista DevTools Network → ei satoja DB-kyselyitä (käytä Flask-DebugToolbar dev-tilassa jos käytössä)
```

---

## PROMPT 8C — UI-toimivuuspaketti (toast, dialogit, tila-merkinnät)

```
Tehtävä Cursorille: Lisää modernit UI-mikropalveluja: toast-notifikaatiot, vahvistusdialogit, latauspoolit, optimistic UI updates.

Tausta: Nykyiset onnistumisilmoitukset käyttävät Flaskin flash() — toimiva mutta ei moderni. Init-template §13 sanoo "onnistuneet toiminnot näytetään käyttäjälle".

Vaihe 1: Toast-notifikaatiot (app/static/js/admin-toast.js)
- Globaali API:
  toast.success(message, options)
  toast.warning(message, options)
  toast.error(message, options)
  toast.info(message, options)
- Renderöi <div class="toast-stack" /> bodyn päälle (z-index korkea)
- Jokainen toast: ikoni + viesti + sulje-painike
- Auto-sulkeutuu 5 s (success/info), 8 s (warning), pysyy auki (error)
- Liukuu yläoikealta (translateX), poistuu fade-out

Vaihe 2: Flash → toast-bridge (app/templates/admin/base.html)
- Olemassa oleva {% with messages = get_flashed_messages(with_categories=true) %} ... renderöidään myös toast-muodossa
- JS-side lukee data-flash-kentät DOM:sta sivun latauksen yhteydessä, laukaisee toast-kutsut
- Säilytä myös plain HTML-versio fallbackiksi jos JS ei lataudu (saavutettavuus)

Vaihe 3: Vahvistusdialogi (app/static/js/admin-confirm.js)
- Käytä HTML5 <dialog>-elementtiä (init-template §13: "vaaralliset toiminnot vaativat vahvistuksen")
- API:
  confirmAction({
    title: "Poista käyttäjä?",
    message: "Käyttäjä matti@example.com poistetaan pysyvästi.",
    confirmLabel: "Poista",
    cancelLabel: "Peruuta",
    dangerous: true,  // punainen Poista-painike
  }) → Promise<boolean>
- Käytetään lomakkeen submitin sijaan: form lähettää vain jos confirmAction → true
- Esimerkki:
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const config = JSON.parse(form.dataset.confirm);
      if (await confirmAction(config)) form.submit();
    });
  });
- Korvaa nykyiset native confirm()-kutsut (jos sellaisia on) data-confirm-attribuutilla

Vaihe 4: Latauspoolit (app/static/js/admin-loading.js)
- Globaali loading API:
  loading.show(message)  // näyttää overlay + spinneri
  loading.hide()
- Käytä form-submit-aikana automaattisesti:
  document.querySelectorAll('form[data-loading]').forEach(form => {
    form.addEventListener('submit', () => loading.show(form.dataset.loading || 'Tallennetaan…'));
  });
- Painikkeen disable + spinner sisällä:
  <button class="btn btn-primary" data-loading-button>Tallenna</button>
  → klikkauksen jälkeen disabled + sisätekstinä spinner + alkuperäinen teksti

Vaihe 5: Optimistic UI (light)
- Esim. checkbox "valmis" -tilanmuutos: päivitä UI heti vaikka backend ei ole vielä vastannut
- Jos backend palauttaa virheen → revert UI + toast.error
- Älä tee tästä isoa — vain harvoissa kohdissa (taskien tila, tagit, jne.)

Vaihe 6: Status-merkinnät yhtenäisinä
- Käytä jo CSS:ssä olevia .badge-success / .badge-warning ym. luokkia
- Yhtenäinen mappaus:
  reservation.status: confirmed → success, pending → warning, cancelled → muted, completed → info
  invoice.status: paid → success, pending → warning, overdue → danger, cancelled → muted
  maintenance.status: open → warning, in_progress → info, resolved → success, cancelled → muted
- Tee app/templates/admin/_macros.html jossa {% macro status_badge(status, type) %} -helper

Vaihe 7: Skeleton loaders dynaamisille listoille
- Kun JS hakee dataa (esim. dashboard-graafit), renderöi <div class="skeleton skeleton-line"></div> -placeholder
- Korvaa todellisella sisällöllä kun data saapuu

Vaihe 8: Saavutettavuus
- Toast: aria-live="polite" (info/success), aria-live="assertive" (error)
- Dialog: aria-labelledby, focus-trap, Esc sulkee
- Loading: aria-busy="true" + aria-label="Ladataan"
- Painikkeet, joilla ikoni vain → aria-label

Vaihe 9: Testit (tests/test_admin_ui_helpers.py)
- test_admin_pages_load_toast_js (HTML sisältää <script ... admin-toast.js>)
- test_admin_pages_have_dialog_polyfill_for_old_browsers (vapaaehtoinen — vain jos käytät vanhaa selaintukea)
- test_dangerous_actions_have_confirm_attribute (esim. form[action="/admin/users/X/delete"] sisältää data-confirm)
- Manuaalitestaa selaimessa, älä yritä JSDOMin kautta (työläs)

Tiedostot:
- app/static/js/admin-toast.js, admin-confirm.js, admin-loading.js (uudet)
- app/static/css/admin.css (toast-tyylit, dialog-tyylit, spinner)
- app/templates/admin/base.html (lataa uudet JS:t, renderöi toast-stack-container)
- app/templates/admin/_macros.html (uusi, status-badge-helperit)
- tests/test_admin_ui_helpers.py (uusi)

ÄLÄ:
- Älä käytä alert()/confirm()/prompt() — natiivit ovat rumia
- Älä lataa Toastify-, SweetAlert-, jne. -kirjastoja (lisäävät kg-koon kuluja, keksitään pyörää uudestaan)
- Älä unohda saavutettavuutta
- Älä riko fallback-tilaa (jos JS ei lataudu, sivun pitää silti toimia)

Aja lopuksi:
1. pytest -v
2. Manuaalitesti: yritä poistaa käyttäjä → vahvistusdialogi
3. Manuaalitesti: tallenna asetus → toast-onnistumisilmoitus
4. Manuaalitesti: aja lomake jolla validointivirhe → toast-virheilmoitus
5. Saavutettavuus-testi: VoiceOver / NVDA tai Lighthouse-audit (Accessibility-skoori 90+)
```

---

## PROMPT 8D — Haku, filtterit, bulk-actions

```
Tehtävä Cursorille: Lisää Pikahaku, tallennetut suodattimet ja bulk-actions admin-listoihin.

Tausta: Nykyiset listat (varaukset, vieraat, laskut) eivät ole skaalautuvia kun rivimäärä kasvaa. Modernit PMS:t tarjoavat hakukentän, suodattimet ja bulk-toiminnot.

Vaihe 1: Pikahaku (Topbar global search)
- Endpoint: GET /api/v1/search?q=... (uusi)
  - @scope_required("search:read")
  - Hakee: vieraat (nimi, email, puhelin), varaukset (id, vieras), kohteet (nimi), laskut (numero)
  - Tenant-isolaatio: vain g.api_key.organization_id
  - Palauttaa: [{type, id, label, sublabel, url}, ...] (max 20)
- Admin-UI: topbar-input <input type="search" placeholder="Etsi...">
- JS hakee /api/v1/search debounce 200 ms jälkeen, näyttää popup-tulokset
- Cmd/Ctrl+K avaa hakukentän nopeasti

Vaihe 2: Lista-suodattimet
- Jokaiseen lista-näkymään (varaukset, laskut, ym.) lisää suodatinpalkki yläosaan:
  - Status-suodatin (chip-ryhmä: All / Confirmed / Pending / Cancelled)
  - Päivämääräväli (date-range picker, käytä natiivi <input type="date">)
  - Vapaa hakukenttä (suodattaa nykyisestä listasta)
- Suodattimet URL-parametreina (?status=confirmed&from=2026-01-01)
- Backend: services.py list-funktiot ottavat optional filter-parametrit

Vaihe 3: Tallennetut suodattimet (saved views)
- Käyttäjä voi tallentaa nykyisen suodattimen nimellä:
  "Loppuviikolla saapuvat" → /admin/reservations?status=confirmed&checkin_from=today&checkin_to=today+7d
- Tallennus tietokantaan: SavedFilter-malli (user_id, name, view_type, filter_params JSON)
- Sidebar tai dropdown: lista omista tallennetuista
- Audit: action="saved_filter.created" / "saved_filter.deleted"

Vaihe 4: Bulk-actions
- Lista-näkymään checkbox jokaiselle riville + "valitse kaikki" -checkbox otsikkorivillä
- Bulk-actions-bar ilmestyy kun yksi tai useampi rivi valittu:
  - Varaukset: peruuta valitut, vaihda status, lähetä viesti
  - Laskut: merkitse maksetuksi, lähetä muistutus, vie CSV
  - Vieraat: tagaa, vie CSV, poista (vain superadmin)
- Bulk-action: POST /admin/<resource>/bulk
  - body: {action: "...", ids: [1, 2, 3], params: {...}}
  - Backend: validoi tenant-isolaatio jokaiselle id:lle, suorita action, audit-loki
- Idempotency-key bulk-actioneille (käytä Prompt 7B:n mekanismia)

Vaihe 5: Vienti (CSV/XLSX)
- "Vie CSV" -painike jokaiseen lista-näkymään
- Backend: GET /admin/<resource>/export?format=csv&<filters>
- Jos > 10000 riviä, generoi taustatyönä ja lähetä sähköpostilla (käytä Prompt 7G:n queue:ta)
- Audit: action="<resource>.exported", context={format, count}

Vaihe 6: Sivutus
- Jokaisessa listassa: pageration footer
- "Edellinen / Seuraava" + "X-Y / Z" + per-page-valinta (25/50/100)
- URL: ?page=2&per_page=50

Vaihe 7: Lajittelu
- Jokaisen taulukon otsikkosolu klikattava → lajittelu
- ↑/↓ -ikoni näyttää suunnan
- URL: ?sort=created_at&dir=desc

Vaihe 8: Testit
- tests/test_admin_search.py (uusi):
  - test_search_returns_only_own_org_results
  - test_search_includes_all_resource_types
  - test_search_requires_login
  - test_search_handles_empty_query
- tests/test_admin_bulk_actions.py (uusi):
  - test_bulk_cancel_reservations_audits_each
  - test_bulk_action_rejects_other_org_ids (tenant-isolation)
  - test_bulk_action_idempotent_with_key
- tests/test_admin_export.py (uusi):
  - test_csv_export_returns_correct_rows
  - test_csv_export_respects_filters
  - test_large_export_queues_email_delivery

Tiedostot:
- app/api/routes.py (search-endpoint)
- app/admin/services.py (list-funktioiden suodattimet, bulk-funktiot)
- app/admin/routes.py (bulk-action POST-endpoint, export GET-endpoint)
- app/admin/models.py (SavedFilter-malli)
- migrations/versions/*.py (uusi)
- app/static/js/admin-search.js, admin-filters.js, admin-bulk.js (uudet)
- app/templates/admin/_filters.html, _bulk_bar.html (macros)
- app/templates/admin/<resource>/list.html (käyttää macroja)
- tests/test_admin_search.py, test_admin_bulk_actions.py, test_admin_export.py (uudet)

ÄLÄ:
- Älä tee bulk-actionia joka käsittelee > 1000 riviä synkronisesti (käytä taustaajoja)
- Älä unohda tenant-isolaatiota bulk-actionissa
- Älä unohda audit-lokia jokaisesta bulk-toimesta
- Älä unohda CSRF-tokenia POST-bulkissa
- Älä exportoi salaisia kenttiä (password_hash, api_key_hash, totp_secret)

Aja lopuksi:
1. pytest tests/test_admin_search.py tests/test_admin_bulk_actions.py tests/test_admin_export.py -v
2. Manuaalitesti: paina Cmd+K, hae "matti", tulokset näkyvät
3. Manuaalitesti: valitse 3 varausta, peruuta bulk → kaikki audit-lokitetaan
4. Manuaalitesti: vie laskut CSV → tiedosto latautuu
```

---

## PROMPT 8E — Notification center

```
Tehtävä Cursorille: Lisää admin-paneeliin sisäinen notifikaatiokeskus joka näyttää tärkeitä tapahtumia.

Tausta: Käyttäjä näkee sähköpostissa vain osa tapahtumista. Sisäinen notification center pitää käyttäjän ajan tasalla mitä omassa orgissa tapahtuu.

Vaihe 1: Notification-malli (app/notifications/models.py)
- Notification:
  - id, organization_id, user_id (jos kohdistettu, voi olla null = orgin kaikki adminit)
  - type (string, esim. "reservation.created", "invoice.overdue", "backup.failed")
  - title (string), body (text), link (URL, nullable)
  - severity (info / warning / danger / success)
  - is_read (bool, default false)
  - created_at, read_at (nullable)

Vaihe 2: Service (app/notifications/services.py)
- create(organization_id, type, title, body, link, severity, user_id=None)
  - Tallenta DB:hen
  - Audit: action="notification.created"
  - Voitaisiin myös laukaista push (browser Push API tai webhook publisher Prompt 7F:n kautta)
- mark_read(notification_id, user_id) — varmista omistus
- mark_all_read(user_id, organization_id)
- list_unread(user_id, organization_id, limit=50)
- prune_old(retention_days=90) → APScheduler-job

Vaihe 3: Tapahtumien laukaisu
- Kytke vastaaviin service-funktioihin:
  - app/reservations/services.py create_reservation → notify "reservation.created"
  - app/billing/services.py mark_overdue_invoices → notify "invoice.overdue"
  - app/backups/services.py create_backup (failure) → notify "backup.failed" severity=danger
  - app/maintenance/services.py create_request → notify "maintenance.requested"
  - jne.
- Pidä notify-kutsut kevyinä — ÄLÄ ETÄÄ blokkaa request-vastausta

Vaihe 4: Topbar-kello
- Topbarissa kello-ikoni + lukematonta-luku-badge
- Klikkaus avaa popup-listan (max 20 viimeisintä lukematonta)
- Linkki "Näytä kaikki" → /admin/notifications

Vaihe 5: /admin/notifications -sivu
- Lista kaikista (lukematon + luetut)
- Ryhmittely päivän mukaan
- Klikkaus rivillä → merkitse luetuksi + ohjaa link-kohteeseen
- "Merkitse kaikki luetuksi" -painike

Vaihe 6: Real-time (vapaaehtoinen)
- Polling: JS hakee /admin/notifications/unread_count joka 30 s
- Tai: SSE (Server-Sent Events) /admin/notifications/stream
- Push API selaimessa = tarvitsee service workerin → vapaaehtoinen, älä tee jos ei tarvita

Vaihe 7: Per-käyttäjä-asetukset
- "Mitä haluat saada"-asetussivu (toggle-listoja per type)
- Tallenna user_preferences-tauluun JSON-kenttäänä
- Service tarkistaa preferences ennen create():a

Vaihe 8: Testit (tests/test_notifications.py)
- test_notification_only_visible_to_own_org
- test_notification_mark_read_requires_owner
- test_unread_count_excludes_read
- test_create_notification_audits
- test_user_preferences_filter_notifications

Tiedostot:
- app/notifications/__init__.py, models.py, services.py, routes.py (uudet)
- migrations/versions/*.py
- app/admin/routes.py (kytke topbar-data)
- app/templates/admin/_notification_bell.html (macro)
- app/templates/admin/notifications.html (lista-sivu)
- app/static/js/admin-notifications.js (popup, polling)
- tests/test_notifications.py (uusi)

ÄLÄ:
- Älä luo notifikaatiota jokaisesta tapahtumasta (audit-loki on jo olemassa, älä duplikoi)
- Älä unohda tenant-isolaatiota
- Älä blokkaa request-vastausta synkronisella notify-kutsulla (käytä db.session.flush() + commit lopuksi)
- Älä lähetä Push-notifikaatiota ilman käyttäjän opt-iniä

Aja lopuksi:
1. pytest tests/test_notifications.py -v
2. Manuaalitesti: luo varaus → admin näkee notifikaation
3. Manuaalitesti: kelloon tulee badge, klikkaus avaa popupin
```

---

## PROMPT 8F — Tag-järjestelmä + kommentit

```
Tehtävä Cursorille: Lisää tagit ja kommentit varauksiin, vieraisiin ja kohteisiin.

Tausta: Modernit PMS:t sallivat operaattorin lisätä tageja ("VIP", "lapsiperhe", "allergiat") ja kommentteja ("vieras pyysi parveketta") resursseihin. Tämä parantaa työnkulkua ja viestintää tiimissä.

Vaihe 1: Mallit
- Tag (app/tags/models.py):
  - id, organization_id, name (string, unique per org), color (hex string)
  - created_by_user_id, created_at
- Tagit liitetään moneen suuntaan, käytä assosiointiluokkaa:
  - GuestTag (guest_id, tag_id)
  - ReservationTag (reservation_id, tag_id)
  - PropertyTag (property_id, tag_id)
- Comment (app/comments/models.py):
  - id, organization_id, target_type (string, "guest"/"reservation"/"property"), target_id (int)
  - author_user_id, body (text), created_at, edited_at (nullable)
  - is_internal (bool, default true) — internal kommentit eivät näy vieras-portaaliin

Vaihe 2: Service-kerros
- TagService: create, attach, detach, list_for_target
- CommentService: create, edit (vain kirjoittaja, < 15 min), delete (kirjoittaja tai admin)
- Audit-loki: tag.created, tag.attached, tag.detached, comment.created, comment.edited, comment.deleted

Vaihe 3: API-endpointit (/api/v1/)
- GET /tags @scope_required("tags:read")
- POST /tags @scope_required("tags:write")
- POST /<resource>/<id>/tags @scope_required("<resource>:write") (attach)
- DELETE /<resource>/<id>/tags/<tag_id> @scope_required("<resource>:write")
- GET /<resource>/<id>/comments @scope_required("<resource>:read")
- POST /<resource>/<id>/comments @scope_required("<resource>:write")
- PATCH /comments/<id> @scope_required("<resource>:write")
- DELETE /comments/<id> @scope_required("<resource>:write")

Vaihe 4: Admin-UI
- Tag-input: dropdown jolla voi valita olemassa olevia tageja tai luoda uuden
- Värivalinta: 8 esivalittua väriä (vihreä/keltainen/punainen/sininen/violetti/oranssi/harmaa/musta)
- Kommentti-thread: lista uusin ensin, kirjoita-input alhaalla
- Mention-syntax: @käyttäjä → notification kohdekäyttäjälle (käytä Prompt 8E:n notification-systeemiä)

Vaihe 5: Vieras-portaali
- Vieras EI näe internal-kommentteja
- Vieras EI näe tageja
- Tämä on tenant-internal feature

Vaihe 6: Hakuyhteensopivuus (Prompt 8D)
- Tag-suodatin lista-näkymiin: "Näytä vain VIP-vieraat"
- Hakukenttä löytää resurssin jos tag matchaa

Vaihe 7: Testit
- tests/test_tags.py: create, attach, detach, tenant-isolation, audit
- tests/test_comments.py: create, edit by author only, delete by author/admin, internal-flag, audit, mentions

Tiedostot:
- app/tags/__init__.py, models.py, services.py (uudet)
- app/comments/__init__.py, models.py, services.py (uudet)
- migrations/versions/*.py
- app/api/routes.py (uudet endpointit + scope-laajennukset)
- app/admin/routes.py (UI-actionit)
- app/templates/admin/_tag_input.html, _comment_thread.html (macros)
- app/static/js/admin-tags.js, admin-comments.js (uudet)
- tests/test_tags.py, test_comments.py (uudet)

ÄLÄ:
- Älä salli vieras-portaalin kautta tagien tai kommenttien manipulointia
- Älä jätä internal-kommentteja vuotavaan API-vastaukseen
- Älä unohda XSS-suojausta kommenttien renderöinnissä (Jinja2 auto-escape OK)
- Älä unohda audit-lokia
- Älä luo loputtomia tagi-vaihtoehtoja per organisaatio (raja: 100 tagia per org)

Aja lopuksi:
1. pytest tests/test_tags.py tests/test_comments.py -v
2. Manuaalitesti: lisää "VIP"-tag vieras-näkymään, suodata "VIP"-vieraat listassa
3. Manuaalitesti: kommentoi varausta, mention @kollega → kollega saa notifikaation
```

---

## PROMPT 8G — Hinnoittelusäännöt (kausi, viikonpäivä, min. yöt)

```
Tehtävä Cursorille: Lisää dynaaminen hinnoittelu varauksille — kausi-, viikonpäivä- ja vähimmäismajoitus-säännöt.

Tausta: Nykyinen hinnoittelu on (todennäköisesti) yksi kiinteä hinta per kohde. Modernit PMS:t tukevat:
- Eri hinta sesongin mukaan (kesä-/talvihinta)
- Eri hinta arki/viikonloppu
- Vähimmäisvuokra-aika kausissa
- Last-minute-alennukset
- Pitkäaikaisalennukset

Vaihe 1: PricingRule-malli (app/pricing/models.py)
- id, organization_id, property_id (jos rajattu kohteeseen) tai unit_id (rajattu yksikköön)
- name (string), priority (int, korkeampi voittaa)
- season_start (date, nullable), season_end (date, nullable) — voivat olla samaa vuotta tai null
- weekday_mask (int, 0-127, bittinen: ma=1, ti=2, ke=4, ...) — null = kaikki päivät
- min_nights (int, default 1)
- price_per_night (Numeric)
- pct_discount (Numeric, esim. -10.00 = 10 % alennus, sovelletaan kun hinnoittelusääntö osuu)
- last_minute_days (int, nullable) — esim. 3 = vain jos varaus < 3 päivää ennen check-iniä
- long_stay_min_nights (int, nullable) — esim. 7 = vain jos varaus >= 7 yötä
- is_active (bool, default true)
- created_at, updated_at, created_by_user_id

Vaihe 2: Pricing service (app/pricing/services.py)
- calculate_price(unit_id, start_date, end_date, *, organization_id) -> dict
  - Hae soveltuvat säännöt: organization match, property/unit match, season match, weekday-mask match, min-nights match, last-minute/long-stay match
  - Sovella priority-järjestyksessä (korkein voittaa, sitten alennukset)
  - Palauta:
    {
      "nightly_breakdown": [{"date": "2026-06-01", "rate": 120.00, "rule_id": 5}, ...],
      "subtotal": 720.00,
      "discounts": [{"name": "Long-stay -10 %", "amount": -72.00}],
      "total": 648.00,
      "min_nights_required": 3,
    }
- Kun varaus luodaan, tämä laskenta ajetaan AINA backendissä — ei luoteta clientin lähettämään hintaan

Vaihe 3: Reservations-integraatio
- create_reservation kutsuu calculate_price
- Tallenna nightly_breakdown JSON-kenttäänä Reservation-malliin (uusi sarake `pricing_breakdown`)
- Tämä auttaa myöhemmin laskutuksessa ja kuiteissa

Vaihe 4: API-endpointit
- POST /api/v1/pricing/quote — laske hinta ilman varauksen luontia (vieras-portaalia varten)
- GET /api/v1/pricing/rules @scope_required("pricing:read")
- POST /api/v1/pricing/rules @scope_required("pricing:write")
- PATCH /api/v1/pricing/rules/<id> @scope_required("pricing:write")
- DELETE /api/v1/pricing/rules/<id> @scope_required("pricing:write")

Vaihe 5: Admin-UI
- /admin/pricing — lista kohteista + niiden säännöistä
- Sääntö-editori: kalenterinäkymä jossa voi visualisoida päiviä ja niiden hintoja
- Esikatselu: "Mikä olisi hinta valitulla välillä?" → calculate_price-API-kutsu

Vaihe 6: Vieras-portaali
- Hinnan näyttäminen varauspyyntö-vaiheessa (käytä /api/v1/pricing/quote)
- "Hinta sisältää: ALV 24 %" — selkeä erittely

Vaihe 7: Audit-loki
- pricing_rule.created / .updated / .deleted
- Reservation.created -kutsuun lisätään context={pricing_rules_applied: [5, 7]}

Vaihe 8: Testit (tests/test_pricing.py)
- test_default_price_when_no_rules
- test_seasonal_rule_applies_only_in_season
- test_weekend_rule_higher_than_weekday
- test_min_nights_enforced (varaus jossa nights < min_nights → virhe)
- test_long_stay_discount_applied
- test_last_minute_discount_when_within_window
- test_priority_resolution (korkeampi sääntö voittaa)
- test_tenant_isolation (toisen orgin sääntö ei näy)

Tiedostot:
- app/pricing/__init__.py, models.py, services.py (uudet)
- app/reservations/services.py (kytke calculate_price)
- app/reservations/models.py (pricing_breakdown JSON-sarake)
- migrations/versions/*.py
- app/api/routes.py (uudet endpointit)
- app/admin/routes.py (UI)
- app/templates/admin/pricing_*.html (uudet)
- app/portal/services.py / templates/portal/* (vieras-portaali näyttää hinnat)
- tests/test_pricing.py (uusi)

ÄLÄ:
- Älä jätä hintalaskentaa frontendiin — backend laskee aina
- Älä salli rajan ohittaa min_nights ilman explicit superadmin-merkintää
- Älä cachaa hintoja yli 5 minuuttia (säännöt voivat muuttua)
- Älä unohda tenant-isolaatiota
- Älä unohda ALV:tä (käytä Prompt 5:n mekanismia — pricing-säännöt antavat veroton/incl-summan tarpeen mukaan)

Aja lopuksi:
1. pytest tests/test_pricing.py -v
2. Manuaalitesti: luo "Kesäkausi 1.6-31.8 +20 %" -sääntö, varaa heinäkuussa → kalliimpi hinta
3. Manuaalitesti: yritä varata 1 yötä kohteessa jolla min_nights=3 → virhe
```

---

## Yhteenveto

Tämä paketti tekee PMS:stä ammattitason ennen maksuintegraatiota:

| Prompti | Mitä saa | Aika (Cursor) |
|---------|----------|---------------|
| 8A — Design-järjestelmä | Modernit värit, typografia, dark mode, komponentit, mobiili | 6–10 h |
| 8B — Dashboard | KPI-kortit, mini-graafit, toimintaehdotukset | 3–5 h |
| 8C — UI-toimivuus | Toast, dialogit, loading, status-merkinnät | 3–5 h |
| 8D — Haku/filtterit/bulk | Cmd+K-haku, tallennetut suodattimet, bulk-actionit, CSV-vienti | 8–12 h |
| 8E — Notification center | Sisäinen tapahtumakeskus | 4–6 h |
| 8F — Tagit + kommentit | Tagit, mentions, internal-kommentit | 5–8 h |
| 8G — Hinnoittelusäännöt | Kausi/viikonpäivä/min-yöt/last-minute | 8–12 h |

Kaikki promptit:
- Noudattavat init-templatea 100 %
- Sisältävät audit-lokin
- Sisältävät tenant-isolaation
- Sisältävät testit
- Sisältävät ÄLÄ-listan rikkomusten estoon
- Eivät edellytä maksuintegraatiota

Aja järjestyksessä — 8A on perusta josta muut nojautuvat. 8B-8C ovat "quick wins" jotka näkyvät heti. 8D-8G ovat isompia mutta merkittäviä laadulle.
