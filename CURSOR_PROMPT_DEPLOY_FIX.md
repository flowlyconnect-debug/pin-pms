# Cursor-prompti — korjaa rikki oleva tuotantodeployment

Kopioi koko alla oleva teksti Cursorin chattiin (kuten muutkin promptit). Cursor ajaa diagnostiikan, korjaa puuttuvat osat, ja stagaa committin valmiiksi sinulle. **Cursor EI saa committata tai pushata** — sinä teet sen viimeisen vaiheen itse kun olet tarkistanut.

---

```
Tehtävä: Korjaa Pindora PMS:n tuotantodeployment Renderissä.

Konteksti: Render-tuotantokanta on alembic-revisiossa `e9f0a1b2c3d4` (idempotency_keys-taulu). Aiemmat 7B/7C-committit menivät gittiin, mutta migraatiotiedostot ja kolme testitiedostoa unohtuivat niistä. Render-kanta on revisiossa jonka tiedostoa ei ole repossa → `flask db upgrade` kaatuu virheeseen "Can't locate revision identified by 'e9f0a1b2c3d4'" → Render pitää vanhan version (6c60662 = Prompt 7) elossa.

Lisäksi paikallinen .venv on rikki: `apispec`-paketti puuttuu, joten `flask`-komennot kaatuvat ImportErroriin.

ÄLÄ:
- Älä committaa tai pushaa mitään automaattisesti — anna käyttäjän tehdä se itse
- Älä muuta migraatiotiedostojen sisältöä (revisio-ID:t ovat kriittisiä)
- Älä muuta tiedostojen rivinvaihtoja LF→CRLF tai päinvastoin (käytä editor-asetuksia jotka säilyttävät alkuperäisen)
- Älä lisää `'unsafe-inline'` CSP:hen
- Älä koske .git-hakemistoon manuaalisesti (paitsi index.lock jos se estää operaatiot)

Vaihe 1 — Diagnostiikka
1. Aja `git status` ja raportoi:
   - Modified-tiedostojen lista
   - Untracked-tiedostojen lista
   - Onko .git/index.lock-tiedostoa olemassa
2. Aja `git log --oneline -10` ja raportoi viimeiset 10 committia
3. Aja `git remote -v` ja varmista että origin/main on olemassa
4. Aja `git diff HEAD --shortstat`

Vaihe 2 — Korjaa paikallinen venv
1. Aktivoi venv: `.venv\Scripts\activate`
2. Aja `python --version` (pitäisi olla 3.10 tai uudempi)
3. Aja `pip install --upgrade pip`
4. Aja `pip install -r requirements.txt`
5. Aja `pip install -r requirements-dev.txt`
6. Aja `flask --help` ja varmista että listalla näkyy `db`-komentoryhmä
7. Jos `flask db --help` toimii → venv on kunnossa, jatka
8. Jos jokin asennus kaatuu → kopioi virheilmoitus käyttäjälle ja pysähdy

Vaihe 3 — Varmista migraatioketju
1. Aja: ls migrations/versions/ ja varmista että nämä KAIKKI tiedostot ovat olemassa:
   - 12f7eacdab45_add_vat_to_invoices.py
   - a1b2c3d4e5f7_add_anonymized_at_to_users.py
   - e9f0a1b2c3d4_add_idempotency_keys_table.py
   - a7b8c9d0e1f2_add_webhook_infrastructure.py
2. Tarkista jokaisen tiedoston yläosa — `revision = "..."` ja `down_revision = "..."` -kentät
3. Varmista että ketju on:
   - 12f7eacdab45 ← w6f7g8h9i0j1
   - a1b2c3d4e5f7 ← 12f7eacdab45
   - e9f0a1b2c3d4 ← a1b2c3d4e5f7
   - a7b8c9d0e1f2 ← e9f0a1b2c3d4
4. Jos ketju on rikki → raportoi käyttäjälle ja pysähdy
5. Aja: flask db current — paikallinen kanta-revisio (info)
6. Aja: flask db heads — pitää näyttää `a7b8c9d0e1f2 (head)`

Vaihe 4 — Tarkista että kaikki Promptin 7B/7C-osat ovat paikoillaan
1. Tarkista että nämä tiedostot ovat olemassa:
   - app/idempotency/__init__.py
   - app/idempotency/models.py
   - app/idempotency/services.py
   - app/idempotency/decorators.py
   - app/idempotency/scheduler.py
   - app/webhooks/__init__.py
   - app/webhooks/models.py
   - app/webhooks/services.py
   - app/webhooks/routes.py
   - app/webhooks/scheduler.py
   - app/webhooks/handlers.py
   - app/webhooks/signature.py
   - app/webhooks/crypto.py
   - tests/test_idempotency.py
   - tests/test_webhooks.py
   - tests/test_webhooks_outbound.py
2. Jos jokin puuttuu, raportoi se käyttäjälle ja pysähdy

Vaihe 5 — Korjaa rivinvaihto-noise (CRLF-only-muutokset)
1. Aja PowerShellissä:
   git diff HEAD --name-only > /tmp/changed-files-list.txt
   (tai vastaava Windows-tapa)
2. Iteroi muutettujen tiedostojen yli ja tarkista jokainen:
   diff <(git show HEAD:$file | tr -d '\r') <(tr -d '\r' < $file)
   Jos ulostulo on tyhjä → vain rivinvaihtomuutos → palauta tiedosto
   git show HEAD:$file > $file -tyyppisellä komennolla (PowerShellissä `git show HEAD:$file | Set-Content -NoNewline -Path $file`)
3. PARITUS: tee tämä VAIN niille tiedostoille jotka eivät kuulu Promptin 7B/7C tai mobile-fixin todellisiin muutoksiin
4. Älä koske näihin tiedostoihin (ne ovat aitoja muutoksia):
   - app/core/logging.py
   - migrations/versions/e9f0a1b2c3d4*.py
   - migrations/versions/a7b8c9d0e1f2*.py
   - tests/test_idempotency.py
   - tests/test_webhooks.py
   - tests/test_webhooks_outbound.py

Vaihe 6 — Aja testit
1. Aja: pytest -v --cov=app --cov-fail-under=80
2. Jos kaikki vihreänä → raportoi käyttäjälle "OK, X testiä menee läpi, Y % coverage" ja jatka
3. Jos jokin kaatuu → kopioi epäonnistuvien testien nimet ja virheilmoitukset käyttäjälle
4. ÄLÄ ohita kaatuvia testejä — ne pitää korjata ennen committia
5. Jos testi kaatuu uuteen migraatioon liittyvästä syystä, tarkista että migraatio ajaa testikannan luonnin yhteydessä (conftest.py)

Vaihe 7 — Stagaa puuttuvat tiedostot ja korjaus
1. Jos .git/index.lock on olemassa, kerro käyttäjälle:
   "Lock-tiedosto roikkuu, suorita PowerShellissä: Remove-Item -Force .git\\index.lock"
   Pysähdy ja odota.
2. Aja:
   git add migrations/versions/e9f0a1b2c3d4_add_idempotency_keys_table.py
   git add migrations/versions/a7b8c9d0e1f2_add_webhook_infrastructure.py
   git add tests/test_idempotency.py
   git add tests/test_webhooks.py
   git add tests/test_webhooks_outbound.py
   git add app/core/logging.py
3. Re-stagaa rivinvaihtokorjaukset:
   git add README.md app/auth/services.py app/email/services.py app/templates/admin_settings.html
4. Aja: git status — varmista että:
   - "Changes to be committed" sisältää 6 todellista lisäystä/muutosta + 4 EOL-paluuta
   - "Changes not staged" on TYHJÄ (paitsi mahdolliset käyttäjän omat muut muutokset)
   - "Untracked files" on TYHJÄ tämän commitin osalta

Vaihe 8 — Esikatsele commit
1. Aja: git diff --cached --stat
2. Pitäisi näyttää suunnilleen:
   migrations/versions/e9f0a1b2c3d4_add_idempotency_keys_table.py | XX +
   migrations/versions/a7b8c9d0e1f2_add_webhook_infrastructure.py  | XX +
   tests/test_idempotency.py                                       | XX +
   tests/test_webhooks.py                                          | XX +
   tests/test_webhooks_outbound.py                                 | XX +
   app/core/logging.py                                             |  2 +-
3. Jos näytössä on yli 50 tiedostoa tai > 5000 rivin muutos → STOPP, jossain on EOL-noise — palaa vaiheeseen 5

Vaihe 9 — Raportoi käyttäjälle ja pysähdy
1. Tulosta käyttäjälle yhteenveto:
   "Valmis stagaamaan committia. X tiedostoa stagattu, Y testiä menee läpi.
    Tarkista 'git diff --cached' ja jos hyvältä näyttää, suorita:

    git commit -m \"fix(deploy): add missing 7B/7C migrations and tests; redact webhook signatures\"
    git push origin main

    Push laukaisee Renderin uudelleendeployin. Seuraa Renderin Logs-tabia ja varmista että 'flask db upgrade' menee läpi (e9f0a1b2c3d4 ohitetaan, a7b8c9d0e1f2 ajetaan)."
2. ÄLÄ aja git commit eikä git push

Lopputulos:
- Paikallinen venv toimii (apispec asennettu)
- Kaikki 7B/7C-tiedostot ovat olemassa ja stagattuna
- Testit menevät läpi
- Commit on valmis käyttäjän vahvistukseen
- Käyttäjä ajaa `git commit` + `git push` itse → Render saa puuttuvat tiedostot → migraatio toimii → uusi versio menee elossa
```

---

## Pushin jälkeen — Render-puolella

Kun pushaat, Render rakentaa uuden imagen ja yrittää deployatä. Avaa Renderin **Logs**-tab ja seuraa.

**Onnistunut deployment näyttää tältä:**

```
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade e9f0a1b2c3d4 -> a7b8c9d0e1f2, add_webhook_infrastructure
[gunicorn] Starting...
[gunicorn] Listening at: http://0.0.0.0:10000
```

Jos näet "Running upgrade e9f0a1b2c3d4 -> a7b8c9d0e1f2" — **kaikki toimii**. Webhook-taulut luodaan, sovellus käynnistyy.

**Jos näkyy edelleen "Can't locate revision":**

Tarkista että commit todella sisälsi tiedoston:

```powershell
git log --stat -1 | findstr "e9f0a1b2c3d4_add_idempotency_keys_table"
```

Jos rivi puuttuu → tiedosto ei mennyt committiin. Toista vaihe 7.

**Jos näkyy uusi virhe** (esim. "ImportError" tai "OperationalError"):

Kopioi virheilmoitus tähän chattiin niin selvitetään.

---

## Tämän jälkeen voit jatkaa Prompteihin 7D-7G

Kun deployment on terve, voit ajaa edellisen tiedoston (CHATGPT_PROMPTS_BEFORE_PAYMENTS_2.md) Prompteja 7D-7G ChatGPT:n kautta:

1. **7D — CSP-nonce + inline-script-siivous** (kalenteri ja muut admin-sivut alkavat toimia)
2. **7E — Sentry + monitoring**
3. **7F — Webhook-publisher**
4. **7G — Email-jonotus + retry**

Vasta sitten Prompt 8 (maksuintegraatio) — kun olet saanut asiakkaalta vastaukset maksuvälittäjästä jne.
