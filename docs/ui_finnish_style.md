# UI Finnish style guide

Käyttäjälle näkyvä teksti on suomeksi, raw-arvot pysyvät englanniksi.

## Periaate

- Tietokannan, API:n ja integraatioiden raw-arvoja ei käännetä.
- Käyttäjälle näkyvät labelit käännetään templateissa tai service-contextissa.
- Formien `<option value="">` säilyttää raw-arvon, mutta näkyvä teksti on suomeksi.
- JSON-virhevastauksen `code` pysyy englanniksi; `message` voi olla suomeksi.

## Label-mappaukset

- draft -> Luonnos
- active -> Aktiivinen
- ended -> Päättynyt
- cancelled -> Peruttu
- pending -> Odottaa
- paid -> Maksettu
- overdue -> Erääntynyt
- open -> Avoin
- new -> Uusi
- in_progress -> Työn alla
- waiting -> Odottaa
- resolved -> Ratkaistu
- confirmed -> Vahvistettu
- checked_in -> Saapunut
- checked_out -> Lähtenyt
- low -> Matala
- normal -> Normaali
- high -> Korkea
- urgent -> Kiireellinen
