# Testaus — Pindora PMS

Automaattinen testikoneisto kattaa varauslogiikan, admin-paneelin, maksut,
sähköpostit, lukkointegraation ja synkronointiketjut. Ulkoisia palveluita
(Mailgun, Paytrail, Stripe, Pindora) **ei koskaan kutsuta oikeasti** —
kaikki mockataan tai ajetaan dev-log-moodissa.

## Pika-aloitus

```bash
# Kertaluonteinen asennus
pip install -r requirements-dev.txt
python -m playwright install chromium        # selain E2E-testeille

# Kaikki testit yhdellä komennolla (raportit reports/-kansioon)
python scripts/test.py            # tai: make test
```

## Komennot

| Komento | Mitä ajaa |
|---|---|
| `python scripts/test.py` / `make test` | Kaikki: backend + Playwright E2E |
| `python scripts/test.py backend` / `make test-backend` | Vain pytest-yksikkö/reittitestit (`tests/`) |
| `python scripts/test.py e2e` / `make test-e2e` | Vain Playwright-selaintestit (`e2e/`) |
| `python scripts/test.py journeys` / `make test-journeys` | Nopea savutesti: kriittiset käyttäjäpolut |
| `pytest tests/integration -m integration --override-ini addopts=` | Docker Compose -acceptance (vaatii Dockerin) |

## Raportit

Jokainen ajo kirjoittaa itsenäisen HTML-raportin, josta näkee testikohtaisesti
mikä meni läpi ja mikä ei:

- `reports/backend.html` — backend-testit
- `reports/e2e.html` — selaintestit
- `reports/e2e-artifacts/` — kuvakaappaukset epäonnistuneista selaintesteistä
- `reports/journeys.html` — käyttäjäpolkusavutesti

## Testikerrokset

### 1. Backend-testit (`tests/`, ~130 tiedostoa)

Yksikkö- ja reittitason testit: saatavuus/päällekkäisyys, varauswizard,
admin-näkymät, API-avaimet ja -scopet, maksut (Paytrail + Stripe mockattuna),
sähköpostijonot ja -pohjat, varmuuskopiot, 2FA, tenant-eristys, audit-loki.

Tietokanta: PostgreSQL jos saatavilla (`.env`in `POSTGRES_*`), muuten
automaattinen SQLite-fallback. Pakota SQLite: `FORCE_SQLITE_TEST_DB=1`.

### 2. Kriittiset käyttäjäpolut (`tests/test_critical_journeys.py`)

HTTP-tason synkronointiketjut:

- admin luo varauksen → varauslista → kalenteri-API → tietokanta
- päällekkäinen ja osittain päällekkäinen varaus estyy
- peruutus vapauttaa ajan ja sama slotti voidaan varata uudelleen
- varausvahvistus- ja peruutussähköpostit muodostuvat oikealla sisällöllä
- Paytrail: epäonnistunut callback ei merkitse laskua maksetuksi; väärä
  allekirjoitus hylätään (401)
- Pindora-lukkovirhe ei kaada varauksen peruutusta eikä check-iniä
- virhetilanteet: puuttuva/virheellinen lomakedata, kirjautumaton käyttäjä,
  väärä rooli, API ilman avainta (yhtenäinen virhe-envelope)

### 3. Playwright E2E (`e2e/`)

Oikea selain (Chromium) oikeaa dev-palvelinta vasten. Suite käynnistää
Flask-sovelluksen omaan SQLite-kantaan taustasäikeessä — Postgresia tai
Dockeria ei tarvita. CSRF on päällä kuten tuotannossa.

Kattaa: admin-kirjautuminen, väärä salasana, superadminin pakollinen TOTP-2FA,
varauswizard päästä päähän, varaus kalenterissa, tuplavarauksen esto,
varauksen muokkaus ja peruutus (aika vapautuu), asetuksen muokkaus
superadminina, portaalikirjautuminen ja varausten eristys käyttäjien välillä.

`e2e/test_server_smoke.py` toimii ilman selainta — jos se menee läpi mutta
selaintestit eivät, vika on selainasennuksessa (`python -m playwright install chromium`).

### 4. Acceptance (`tests/integration/`)

Docker Compose -pohjainen koko pinon testi (ennallaan, ajetaan CI:n
`acceptance.yml`-workflow'ssa).

## CI (GitHub Actions)

- `ci.yml` — lint, mypy, pytest (Python 3.11 + 3.12), Docker build (ennallaan)
- `e2e.yml` — **uusi**: Playwright-suite jokaisella pushilla/PR:llä;
  HTML-raportti ja failure-kuvakaappaukset tallentuvat workflow-artefaktiksi
- `acceptance.yml` — Docker Compose -acceptance (ennallaan)

## Uuden testin lisääminen

- Backend: uusi `tests/test_*.py`, fixturet `tests/conftest.py`stä
  (`client`, `organization`, `admin_user`, `superadmin`, `api_key`).
- E2E: uusi `e2e/test_*.py`, fixturet `e2e/conftest.py`stä
  (`live_server`, `seed`, `admin_page`, `superadmin_page`).
- Älä koskaan kutsu ulkoisia palveluita — mockkaa provider-taso
  (malli: `tests/test_payments_smoke.py`).
