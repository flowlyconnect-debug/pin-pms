# Pin PMS — Bugfix-pass yhteenveto

Päivämäärä: 2026-05-07

## Muutetut tiedostot

| # | Tiedosto                                              | Muutos                                          |
|---|-------------------------------------------------------|-------------------------------------------------|
| 1 | `app/static/css/polish.css`                           | UUSI — kaikki värikorjaukset yhdessä paikassa   |
| 2 | `app/templates/admin/base.html`                       | Lataa `polish.css` viimeisenä CSS-tiedostona    |
| 3 | `app/templates/admin/_bulk_bar.html`                  | "Toteuta"-nappi: `btn-secondary` → `btn-primary` |
| 4 | `app/static/js/admin-dashboard.js`                    | Trend 0% → neutraali "→". Iso sparkline + endpoint-piste. |
| 5 | `app/templates/admin/availability.html`               | Pvm "05-07" → "7.5.". Legend lisätty.           |
| 6 | `app/admin/routes.py`                                 | Välittää `today`-muuttujan availability-templateen |

## Mitä korjattiin

### 1. Mustat hoverit & taulukko-headerit (kriittinen)
**Syy:** Selaimen oletus-styles + dark-mode tokenit vuotaneet light modeen.
**Korjaus:** `polish.css` pakottaa `!important`-säännöillä taulukon header-värin (`var(--bg-alt)`) ja hover-tilan (sama vaalea harmaa). Defeatataan myös tailwind-tyyliset `bg-black`/`bg-stone-900`-leakit.

### 2. Lila checkboxit (kriittinen)
**Syy:** Selaimen default `accent-color` on lila Windowsilla.
**Korjaus:** `accent-color: var(--primary) !important` globaalisti `<input type="checkbox|radio">`, `<progress>` ja `<meter>` -elementeille.

### 3. Mustat napit "Toteuta", "Vaihda", "Avaa täysi näkymä" (korkea)
**Syy:** Bulk-barin "Toteuta"-nappi sisälsi sekä `.btn-secondary` että `data-variant="primary"` — secondary voitti CSS-spesifisyydessä.
**Korjaus:** Vaihdettu luokka `btn-primary`:ksi. Lisäksi `polish.css` pakottaa jokainen `data-variant="primary"` ja submit-nappi punaiseksi.

### 4. Trend-indikaattori 0% vihreä (korkea)
**Syy:** `trendUp = trendValue >= 0` käsitti nollan positiivisena.
**Korjaus:** Erillinen `is-neutral`-tila kun trend on 0. Nuoli "→". Lisäksi tuki "inverted" trendille (Kulut: pieneneminen on hyvä).

### 5. Sparklines tuskin näkyvät (korkea)
**Syy:** 60×20 px liian pieni, viiva 1 px haalea.
**Korjaus:** `viewBox` 120×32 + `preserveAspectRatio="none"` + 100% leveys → täyttää kortin alalaidan. Viivan paksuus 2 px, päätepiste pyöreänä. Flat-line-tapaus piilotetaan kokonaan.

### 6. Päivämäärät "05-07" Saatavuus-taulukossa (keski)
**Syy:** Template käytti `day_iso[5:]`-slicea ISO-merkkijonosta.
**Korjaus:** Pilkotaan ISO-string ja muodostetaan "7.5." -muoto. Tämän päivän sarake saa `is-today`-luokan korostusta varten.

### 7. Saatavuus-taulukon "R"/"F" ilman selitystä (keski)
**Korjaus:** Lisätty `availability-legend`-rivi taulukon yläpuolelle 6 statuksella + värikoodatut swatch-laatikot. Status-solut saavat selkeät värit `polish.css`:ssä.

### 8. Info-banner haalea + Yksiköiden tilanne -linkit punaisia alleviivattuja (matala)
**Korjaus:** `polish.css` antaa info-bannerille selkeän sinisen vasemman reunan ja luettavan kontrastin. Yksiköiden tilanne -listan linkit muutetaan tummiksi (hover → punainen), pallot statuksen mukaan värikoodattuna.

## Kun haluat peruuttaa kaiken

```bash
git revert HEAD~1..HEAD
```

Tai ota erikseen tietty tiedosto vanhaksi:

```bash
git checkout HEAD~1 -- app/static/css/polish.css
```
