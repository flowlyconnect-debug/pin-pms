# Cursor-prompti — UI-korjaukset

Liitä Cursoriin sellaisenaan. Tämä on iteraatio Prompt 8A:n ja 8B:n päälle, EI uusi ominaisuus.

```
Tehtävä: Korjaa Pin PMS:n admin-paneelin UI-ongelmat.

Tausta: Käyttäjä raportoi että:
1. Värimaailma on sekava — KPI-kortit ja muut kortit ovat lähes mustia (high contrast dark cards) vaikka sivun pohja on kerma/vaalea (light theme). Tämä näyttää siltä että dark mode on vahingossa puolittain päällä.
2. Topbar (ylävalikko) on tyhjä ja turha:
   - Search-bar on placeholderina mutta ei toiminnallisuutta — pois
   - "Hallintapaneeli"-otsikko duplikoituu sivun h1:n kanssa — pois
   - Vain notifikaatiokello + käyttäjän avatar (MA) ovat hyödyllisiä — säilytetään
3. Sivun rakenne: turha "Lisää kohteet ensin" -varoitusbanneri korostaa tyhjyyttä — säilytä mutta tee siitä hillitympi

Vaihe 1: Diagnosoi värivirhe (app/static/css/admin.css)
- Etsi luokat .card, .kpi-card, .dashboard-* (tai vastaavat) joita Prompt 8B/8A loi
- Tarkista, käyttävätkö ne suoraan tummia värejä (kuten background: #18181a tai #0d0d0c) sen sijaan että käyttäisivät --color-surface-muuttujaa
- Tämä on yleinen virhe: design-tokenit määriteltiin :root:iin sekä light- että dark-versiona @media (prefers-color-scheme: dark) -tilaan, mutta KOMPONENTTIEN CSS pakottaa tumman taustan
- KORJAUS: jokaisen kortin background pitää olla var(--color-surface), ei kovakoodattu tumma
- Sama warning-banner-komponentille (Lisää kohteet ensin -laatikko)

Vaihe 2: Korjaa kortit käyttämään tokeneita
- KPI-kortit (app/static/css/admin.css):
  .kpi-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--color-text);
    box-shadow: var(--shadow-sm);
  }
  .kpi-card-label { color: var(--color-text-muted); font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: 0.05em; }
  .kpi-card-value { color: var(--color-text); font-size: var(--fs-3xl); font-weight: 700; font-family: var(--font-mono); }
  .kpi-card-meta { color: var(--color-text-muted); font-size: var(--fs-xs); }

- Säilytä isompi vahva varjo dashboardilla (visual hierarchy):
  .kpi-card { box-shadow: var(--shadow-md); }

- Tee sama .panel, .panel-dark (tai mitä luokkia "Vaatii toimintaa", "Tänään saapuu", jne. käyttävät):
  .panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--r-lg);
    padding: 1.25rem 1.5rem;
    color: var(--color-text);
  }
  .panel h3, .panel .panel-title {
    color: var(--color-text-muted);
    font-size: var(--fs-xs);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin: 0 0 0.85rem;
    font-weight: 600;
  }

- Tarkista myös template-tasolla (app/templates/admin/dashboard.html) — älä käytä inline `style="background: black"` tai vastaavaa

Vaihe 3: Topbarin siivous (app/templates/admin/base.html)
- Topbarissa (desktop ja mobile) säilytetään VAIN:
  - Vasemmalla: sivun otsikko (block content title) — JA tämä otsikko EI duplikoidu sivun h1:n kanssa, koska h1 poistetaan
  - Oikealla: notifikaatiokello (Prompt 8E) + käyttäjän avatar (Prompt 8A käyttäjäpaneelista alavalikkoon)
- POISTETAAN topbarista:
  - Search-input (siirry takaisin Prompt 8D:n haku-toiminnallisuuteen kun se on toteutettu — tällä hetkellä input on tyhjä eikä toimi)
  - Mahdolliset duplikoidut "Pin PMS" -otsikot
  - Kaikki muut decoroivat elementit
- Mobiilissa: hampurilaisikoni vasemmalla + sivun otsikko keskellä + kello + avatar oikealla

Vaihe 4: Päällekkäisen otsikon poisto
- Dashboardilla: "Hallintapaneeli" näkyy nyt KAHDESTI:
  1. Topbarin block content title
  2. Sivun sisällön <h1>Hallintapaneeli</h1>
- Päätä yksi kohta:
  - VAIHTOEHTO A (suositus): Säilytä topbarin title, poista sivun h1
  - VAIHTOEHTO B: Säilytä sivun h1, jätä topbar pelkkään "Pin PMS" -brändiin
- Suositus A — modernit dashboardit eivät toista otsikkoa
- Tee tämä app/templates/admin/dashboard.html ja vastaavat sivut joissa on duplikaatti
- Käytä macro-pohjaista lähestymistä jos useita sivuja: app/templates/admin/_page_header.html joka renderöi pelkän alaotsikon (jos on) + breadcrumbin (jos on)

Vaihe 5: Empty-state -banneri vaaleammaksi
- "Lisää kohteet ensin" -banneri näyttää nyt liian voimakkaalta vaalealta vasemmalta laidalta
- Hillitymmäksi:
  .empty-state-banner {
    background: var(--color-warning-soft);
    border-left: 4px solid var(--color-warning);
    border-radius: var(--r-md);
    padding: 0.85rem 1.1rem;
    color: var(--color-text);
    font-size: var(--fs-sm);
    margin-bottom: 1rem;
  }
- TAI muuta sävy infoksi (sinisempi, vähemmän hälyyttävä):
  .empty-state-banner-info {
    background: var(--color-info-soft);
    border-left: 4px solid var(--color-info);
  }

Vaihe 6: Käyttäjäpaneeli/avatar topbar:iin
- Avatar (initialilla "MA") on jo topbarissa oikealla — säilytä
- Klikkaus avatariin avaa pikkudropdownin:
  - Käyttäjän email
  - Organisaatio
  - "Asetukset" -linkki
  - "Kirjaudu ulos" -linkki
- Sidebarista voi nyt poistaa ALAOSAN (käyttäjä-paneeli sivupalkin alalaidalla) jos sama tieto näkyy topbarissa
- TAI säilytä molemmat (käyttäjäpaneeli sidebarin alaosassa, avatar pikadropdownina topbarissa)
- Suositus: poista sidebarin käyttäjäpaneeli, tilaa muille linkeille

Vaihe 7: Värien tarkistus dark-mode-tilassa
- Aja DevTools → Render emulator → "prefers-color-scheme: dark"
- Sivun pitäisi vaihtua oikeasti tummaksi
  - Kortit: tumma surface, vaalea teksti
  - Sidebar: pitää säilyä tumma (jo nyt OK)
  - Topbar: vaihtuu tummaksi
- Jos jokin elementti EI vaihdu, se käyttää kovakoodattua väriä eikä CSS-muuttujaa — korjaa

Vaihe 8: CSS-muuttujien yhtenäisyys
- Käy app/static/css/admin.css läpi ja varmista että MISTÄÄN ei löydy:
  - background: #ffffff / #fff (kovakoodattu valkoinen)
  - background: #000 / #000000 (kovakoodattu musta)
  - background: rgb(...) suoraan
  - color: #..(suoraan)
  Paitsi :root:ssa missä määritellään tokenit
- Käytä kaikkialla muualla var(--color-...)
- Tämä takaa että tokenit toimivat ja tema vaihtuu

Vaihe 9: Testit
- tests/test_admin_visual.py: päivitä jos olemassa
  - test_dashboard_uses_kpi_card_class (HTML sisältää "kpi-card")
  - test_topbar_does_not_duplicate_h1 (sivun HTML ei sisällä topbar-titlessä JA <h1>:ssä samaa tekstiä)
  - test_topbar_search_input_removed (HTML EI sisällä topbar-searchissä input-elementtiä — kunnes 8D:n haku on toteutettu)
- pytest -v --cov=app --cov-fail-under=80

Tiedostot:
- app/static/css/admin.css (kortit, paneelit, banneri — käyttävät tokeneita)
- app/templates/admin/base.html (topbarin siivous, avatar-dropdown)
- app/templates/admin/dashboard.html (h1 pois jos topbarin title säilyy)
- app/templates/admin/_page_header.html (uusi macro, vapaaehtoinen)
- tests/test_admin_visual.py (päivitys)

ÄLÄ:
- Älä poista CSS-muuttujia (:root) — siellä määritellyt tokenit ovat oikein
- Älä poista dark-mode-mediakyselyä @media (prefers-color-scheme: dark) — se on kunnossa
- Älä lisää inline-style:ä HTML:ään (CSP estää, ja design-järjestelmän idea rikkoutuu)
- Älä lisää hakukentän takaisin topbariin (palautuu Prompt 8D:n yhteydessä toiminnallisena)
- Älä riko Prompt 8E:n notification-belliä (kello pysyy, vain search ja duplikaattititle pois)
- Älä riko Prompt 8A:n teema-vaihtimen (data-theme-select on toiminnallinen — se voi siirtyä avatar-dropdowniin tai sidebariin alas, mutta säilytä JS-toiminnallisuus)
- Älä koske app/static/js/admin.js:n teema-vaihtaja-osaan rivillä 67–78 — se toimii oikein

Aja lopuksi:
1. pytest -v --cov=app --cov-fail-under=80
2. Manuaalitesti light-mode (default): /admin näyttää valkoiset kortit kerma-pohjalla
3. Manuaalitesti dark-mode (DevTools toggle): /admin vaihtuu yhtenäiseksi tummaksi
4. Manuaalitesti mobiili: hampurilainen vasemmalla, otsikko keskellä, kello + avatar oikealla — ei tilan tuhlaajia
5. Tarkista DevTools → Console: ei CSP-violaatioita uudessa avatar-dropdownissa
```

---

## Sen jälkeen committaa ja pushaa

```powershell
.venv\Scripts\activate
pytest -v --cov=app --cov-fail-under=80
```

Jos vihreä:

```powershell
git add app/static/css/admin.css app/templates/admin/base.html app/templates/admin/dashboard.html tests/test_admin_visual.py
# Lisää _page_header.html jos Cursor loi sen
git add app/templates/admin/_page_header.html 2>$null

git commit -m "fix(ui): consistent light/dark cards, remove placeholder search bar, drop title duplication"

git push origin main
```

Render rakentaa uuden imagen → avaa sivu uudelleen → värit ovat yhtenäiset, topbar siisti.
