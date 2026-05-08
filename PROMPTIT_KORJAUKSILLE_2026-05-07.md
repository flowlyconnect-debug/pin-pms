# Promptit ChatGPT → Cursor -työnkululle

Tämä tiedosto sisältää yhden promptin kutakin selvityksessä havaittua
poikkeamaa kohden. Jokainen prompti on itsenäinen — sen voi syöttää
ChatGPT:lle hiottavaksi (anna ChatGPT:lle ohje "tee tästä Cursorille
syötettävä tarkka tehtävänanto"), ja lopputulos viedään Cursoriin.

Promptit on suunniteltu niin, että ne **eivät riko** olemassa olevaa
toiminnallisuutta. Jokainen päättyy testaus- ja varmistusvaiheeseen.

Suoritusjärjestys: **1 → 2 → 3 → 4 → 5 → 6**. Älä hyppää yli, koska
seuraava prompti olettaa edellisen lopputilan.

---

## Prompti 1 — Repon siivous ja .gitignore-kovennus

> **Käytä tätä ChatGPT:n syötteenä. ChatGPT muokkaa Cursorille tarkan
> tehtävänannon. Cursor toteuttaa.**

```
Tehtävä: Siivoa Pindora-PMS-repo turhista tiedostoista ja koventaa
.gitignore niin että ne eivät palaa.

Konteksti:
- Repo: Flask-pohjainen monikäyttäjä-PMS, Python 3.12+, PostgreSQL.
- Repon juurihakemistossa on tällä hetkellä turhia tiedostoja ja
  hakemistoja, jotka eivät kuulu versionhallintaan.

Tunnistetut turhat kohteet:
1. `.venv/` ja `venv/` — Python-virtualenv-hakemistot.
2. `node_modules/` — npm-riippuvuudet (jos JS-buildia ei tarvita
   repossa, mieti voiko poistaa myös package-lock.json).
3. `.pytest_cache/` — pytestin paikallinen välimuisti.
4. `.claude/worktrees/sleepy-hypatia-41ed3c/` — Cursorin/Claudin
   väliaikainen worktree, joka duplikoi koko projektin.
5. `.git/cursor/crepe/` — Cursorin sisäinen indeksi (alle .git/, ei
   pidä versioida).
6. Juurihakemiston "prosessitiedostot", joita ei käytetä:
   - AUDIT_REPORT.md
   - AUDIT_FULL_v2.md
   - CHATGPT_PROMPTS.md
   - CHATGPT_PROMPTS_PRE_PAYMENT.md
   - CHATGPT_PROMPTS_BEFORE_PAYMENTS_2.md
   - CHATGPT_PROMPTS_VISUAL_PRO.md
   - CHATGPT_PROMPTS_PRO_FINISHING.md
   - CHATGPT_PROMPT_9_PAYMENTS.md
   - CHATGPT_CURSOR_PROMPTS_NEXT.md
   - CURSOR_PROMPT_LIST1.md
   - CURSOR_PROMPT_LIST2.md
   - CURSOR_PROMPT_DEPLOY_FIX.md
   - CURSOR_PROMPT_PAYMENTS_HARDEN.md
   - CURSOR_PROMPT_UI_FIXES.md
   - CUSTOMER_FEEDBACK_RESPONSE.md
   - SELVITYS_PMS_TILA_2026-05-06.md

Toimenpiteet:
1. Poista yllä luetellut tiedostot ja hakemistot levyltä ja
   versionhallinnasta (käytä `git rm -r --cached` jos ne ovat jo
   trackattuna).
2. Lisää tai täydennä `.gitignore` niin että se kattaa:
   - `.venv/`, `venv/`, `env/`
   - `__pycache__/`, `*.pyc`, `*.pyo`
   - `.pytest_cache/`, `.coverage`, `htmlcov/`
   - `.mypy_cache/`, `.ruff_cache/`
   - `node_modules/`
   - `.env` (mutta EI `.env.example`)
   - `.claude/worktrees/`
   - `.idea/`, `.vscode/` (jos ei jaettua workspace-konfiguraatiota)
   - `*.log`
   - käyttöjärjestelmäkohtaiset: `.DS_Store`, `Thumbs.db`
3. Älä poista tai siirrä:
   - `.env.example`
   - `README.md`
   - `SELVITYS_INIT_TEMPLATE_2026-05-07.md`
   - `PROMPTIT_KORJAUKSILLE_2026-05-07.md`
   - mitään `app/`, `tests/`, `migrations/`, `deploy/`,
     `docs/`-kansiossa.
4. Tarkista että `.env`-tiedosto repon juuressa ei ole git-trackattu
   (`git ls-files | grep -E "^\.env$"`). Jos on, poista
   versionhallinnasta `git rm --cached .env`. Älä poista tiedostoa
   levyltä — se on paikallinen kehityskonfiguraatio.

Hyväksymiskriteerit:
- `git status` ei näytä yllä lueteltuja kohteita.
- `git ls-files | wc -l` pienenee selvästi.
- `pytest -v` menee edelleen läpi.
- `flask run` käynnistyy edelleen.
- README ja SELVITYS-tiedostot ovat ennallaan.

Älä koske sovelluskoodiin tämän vaiheen aikana.
```

---

## Prompti 2 — requirements.txt -versiopinning

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Pinnaa requirements.txt:n versiot reproducibility-syistä.

Konteksti:
- Pindora-PMS, Flask 3.x, Python 3.12.
- Nykyinen `requirements.txt` listaa paketit ilman versioita
  (esim. `Flask`, `flask-sqlalchemy`, `pyotp`). Tämä tekee
  buildista epädeterministisen — eri päivinä saa eri versioita.

Toimenpiteet:
1. Luo paikallisesti puhdas virtualenv:
   ```
   python -m venv .venv-fresh
   .venv-fresh\Scripts\activate
   pip install -r requirements.txt
   pip freeze > requirements.lock
   ```
2. Käytä `requirements.lock`-tiedostoa pohjana ja päivitä
   `requirements.txt` siten että jokainen suoraan tarvittu paketti on
   pinnattu täsmälleen (`==`). Älä kuitenkaan listaa transitiivisia
   riippuvuuksia toplevelinä — pidä top-level lista samana, mutta
   versioilla.

   Esimerkki:
   ```
   Flask==3.0.3
   flask-sqlalchemy==3.1.1
   flask-migrate==4.0.7
   ...
   ```
3. Lisää tiedoston yläosaan kommenttiriville selitys:
   ```
   # Pinnatut versiot — käytä `pip-compile`/`pip freeze` kun
   # päivität. Päivitys: 2026-05-07.
   ```
4. Luo erillinen `requirements-dev.txt` (jos sitä ei jo ole hyvällä
   sisällöllä) joka sisältää: `pytest`, `pytest-cov`, `ruff`,
   `black`, `mypy`, `pre-commit`. Pinnaa nämäkin.
5. Päivitä `Dockerfile` käyttämään pinnattua tiedostoa
   (todennäköisesti jo tekee, mutta varmista).

Hyväksymiskriteerit:
- `pip install -r requirements.txt` puhtaaseen virtualenviin
  asentaa tasan samat versiot toistuvasti.
- `pytest -v` menee läpi.
- `docker compose build` onnistuu.
- `requirements.lock`-tiedostoa EI committeta, lisää se
  `.gitignoreen` (paitsi jos haluatte sen referenssiksi —
  tehkää valinta tiimin kesken).

Älä päivitä paketteja uudempiin versioihin tässä vaiheessa.
Päivitykset hoidetaan erillisenä työnä (Renovate / Dependabot).
```

---

## Prompti 3 — Varmuuskopion sisältö (templaten kohta 8)

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Lisää varmuuskopioon erilliset, ihmisluettavat exporttitiedostot
sähköpostipohjista ja järjestelmäasetuksista, kuten
init-templaten kohta 8 vaatii.

Konteksti:
- `app/backups/services.py:create_backup` ajaa `pg_dump`-dumppauksen
  PostgreSQL-tietokannasta ja gzippaa sen.
- Sähköpostipohjat (`email_templates`-taulu) ja asetukset
  (`settings`-taulu) sisältyvät jo dumppiin, mutta init-template
  vaatii ne myös erikseen — niin että niitä on helpompi tarkastaa
  ja palauttaa selektiivisesti.

Toimenpiteet:
1. Laajenna `create_backup` luomaan SQL-dumpin lisäksi:
   - `<stamp>.email_templates.json` — kaikkien rivien serialisointi
     (key, subject, html_body, text_body, variables_json,
     description, created_at, updated_at; ei salaisuuksia).
   - `<stamp>.settings.json` — kaikki rivit, mutta `is_secret=true`-
     riveiltä `value` korvataan stringilla `"<redacted>"`. Tämä
     vastaa init-templaten ohjetta "ei kuitenkaan salaisuuksia
     selväkielisenä".
2. Tallenna molemmat samaan `BACKUP_DIR`-hakemistoon kuin SQL-
   dumppi, samalla aikaleimaprefiksillä. Lisää uudet kentät
   `Backup`-malliin, jos niitä ei vielä ole:
   - `email_templates_filename: str | None`
   - `settings_filename: str | None`
   Luo Alembic-migraatio.
3. Päivitä retentio-/pruning-logiikka käsittelemään myös nämä uudet
   tiedostot.
4. Päivitä `restore_backup` valinnaisesti palauttamaan myös JSON-
   exportit takaisin tauluihin (upsert key-perusteisesti). Lisää
   selvä varoitus admin-UI:hin: "JSON-palautus ylikirjoittaa nykyiset
   pohjat/asetukset". Salaisuus-arvot (`<redacted>`) jätetään
   palauttamatta — ne säilyvät DB:ssä koskemattomina.
5. Lisää testit:
   - `tests/test_backup.py`: backup luo nyt myös JSON-tiedostot ja
     ne sisältävät oikean datan.
   - `tests/test_backup.py`: secret-asetuksen `value` näkyy JSON:issa
     stringinä `"<redacted>"`.
   - `tests/test_backup_restore_flow.py`: JSON-palautus toimii kun
     käyttäjä valitsee sen, ja tekee sen audit-merkinnällä.
6. Päivitä `README.md`:n "Backup usage" -osio kuvaamaan uudet
   tiedostot.

Hyväksymiskriteerit:
- Kaikki olemassa olevat backup-testit menevät edelleen läpi.
- Uudet testit menevät läpi.
- `flask backup-create` tulostaa polun SQL-dumppiin sekä uusiin
  JSON-tiedostoihin.
- Audit-loki saa rivin jokaisesta JSON-palautuksesta.

Älä muuta SQL-dumpin formaattia tai pakkausta.
```

---

## Prompti 4 — Acceptance-kriteerien CI-verifiointi

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Luo automaattinen smoke-testi joka ajaa init-templaten kohdan
22 acceptance-kriteerit Docker Compose -ympäristössä, ja kytke se
CI:hin.

Konteksti:
- README.md:n "Acceptance criteria (init template §22)" -lista
  sisältää 13 manuaalista varmistusta. Mikään niistä ei ole nyt
  automatisoitu loppuun asti.
- Repossa on `pytest`-testit, mutta ei integraatiotestiä joka
  rakentaa stackin nollasta.

Toimenpiteet:
1. Luo `tests/integration/test_acceptance.py` (uusi hakemisto).
   Käytä `pytest`-fikstuureja jotka:
   - Käynnistävät stackin `docker compose up -d --build`.
   - Odottavat että `web` ja `db` ovat healthy.
   - Ajavat migraatiot.
   - Ajavat `flask create-superadmin` ympäristömuuttujilla
     (`ACCEPTANCE_SUPERADMIN_EMAIL`, `ACCEPTANCE_SUPERADMIN_PASSWORD`,
     `ACCEPTANCE_ORG_NAME`).
   - Pyyhkivät stackin lopuksi (`docker compose down -v`).

2. Testit, jotka tarkastavat acceptance-listan kohdat 1–13:
   - 1, 2: stack noussee, `GET /api/v1/health` palauttaa 200.
   - 3: `flask create-superadmin` luo aktiivisen käyttäjän.
   - 4: HTML-pyyntö `/admin/properties` redirectaa `/2fa/...`-polulle
     superadminilla ennen TOTP:ää.
   - 5: API-avain luodaan CLI:llä, `GET /api/v1/me` palauttaa 200.
   - 6: `api_keys`-rivissä `key_hash` on täynnä, plaintext-saraketta
     ei ole skeemassa.
   - 7: `flask send-test-email --to a@example.com --template
     admin_notification` palauttaa exit 0 kun `MAIL_DEV_LOG_ONLY=1`.
   - 8: PUT `/admin/email-templates/<key>` muuttaa pohjaa.
   - 9: `flask backup-create` kirjoittaa tiedoston `BACKUP_DIR`:iin.
   - 10: `flask backup-restore --filename <stamp>.sql.gz` palauttaa.
   - 11: kirjautumisesta syntyy `audit_logs`-rivi.
   - 12: `pytest -v` menee läpi (tämä testi voi olla erillinen
     job, ei riippuvuus integraatiosta).
   - 13: README sisältää avainotsikot (string-haku tiedostoon).

3. Lisää `.github/workflows/acceptance.yml` (tai vastaava CI-
   konfiguraatio sen mukaan mikä on käytössä). Jos GitHub Actionsia
   ei käytetä, kerro mille CI:lle teet (esim. Render, GitLab CI).
   Workflow:
   - Triggers: `push` mainiin, `pull_request`, viikoittainen cron.
   - Job: ajaa `pytest tests/integration/ -v`.
   - Käytä `services: postgres` tai laita Compose hoitamaan kaiken.

4. Merkkaa olemassa oleva `pytest -v` jatkossa "yksikkötestit", ja
   lisää `pytest.ini`-osio joka rajaa yksikkötestit pois
   `tests/integration/`-kansiosta oletuksena (`addopts =
   --ignore=tests/integration`). Integraatiot ajetaan eksplisiittisesti
   (`pytest tests/integration/`).

5. Päivitä `README.md` mainitsemaan miten integraatiotestit ajetaan.

Hyväksymiskriteerit:
- `pytest tests/integration/test_acceptance.py -v` menee läpi
  paikallisesti Dockerin kanssa.
- Olemassa olevat yksikkötestit eivät rikkoudu.
- CI-job ajaa integraation ja punainen putki bloccaa mergen.

Älä korvaa pytest-testejä — laajenna kattavuus.
```

---

## Prompti 5 — KAIKKI TURHA POIS sovelluskoodista (kohta 23)

> **ChatGPT-syöte → Cursor-toteutus.**
> **HUOM:** Tämä on suurin ja riskialttein prompti. Aja ehdottomasti
> oma branchille ja tee PR-katselmointi. Älä mergeä ilman testien
> ajoa.

```
Tehtävä: Karsi Pindora-PMS-projektista käyttämätön tai aliarvoinen koodi
ja moduulit. Älä riko olemassa olevia ominaisuuksia.

Konteksti:
- Init-templaten kohta 23 painottaa yksinkertaisuutta: "Älä rakenna
  ylimääräistä arkkitehtuuria, jos sille ei ole vielä tarvetta."
- Projekti on kasvanut MVP:n yli, ja osa moduuleista voi olla
  lisätty varauksena tai keskeneräisenä.

Toimenpiteet — TEE NÄMÄ JOKAINEN ERILLISENÄ COMMITINA:

A) Käyttämättömät importit ja symbolit
   - Aja `ruff check --select F401,F841 app/ tests/ --fix`.
   - Tarkista diff manuaalisesti ennen committia.
   - Älä poista importteja jotka rekisteröivät SQLAlchemy-malleja
     sivuvaikutuksena (`app/__init__.py:register_models`).

B) Käyttämättömät blueprintit ja moduulit
   Tarkista jokainen alla oleva moduuli ja vastaa raportissa
   (joko PR-kuvauksessa tai DECISIONS.md:ssä):
     - `app/subscriptions/` — onko `SubscriptionPlan` käytössä
       muualla kuin `organizations.subscription_plan_id`-FK:ssa?
       Jos ei, harkitse poistoa.
     - `app/owner_portal/` — onko `/owner`-blueprint testattu ja
       käytössä? Jos kesken, merkitse `app/__init__.py`:ssä
       feature-flagin taakse (`OWNER_PORTAL_ENABLED`).
     - `app/status/` — käytetäänkö `/api/v1/health/ready`-pollausta
       jossain monitorissa? Jos ei, sama kohtelu kuin yllä.
     - `app/integrations/pindora_lock/` ja
       `app/integrations/ical/` — onko PINDORA_LOCK_*- tai
       ICAL_*-ympäristömuuttujat oikeasti asetettu missään
       deployssa? Jos eivät, jätä koodi mutta dokumentoi tilanne.
     - `app/payments/` (Stripe + Paytrail) — toimialalle olennainen,
       älä poista, mutta tarkista onko siellä kuolleita haaroja.
   - ÄLÄ poista yhtään moduulia ilman selkeää perustelua. Jos
     epäselvää, jätä koodi ja siirry seuraavaan.

C) Duplikoituneet tai vanhentuneet näkymät
   - Tarkista `app/templates/`:istä mahdolliset rinnakkaisversiot
     (esim. `*.old.html`, `*.bak.html`, kommentoidut näkymät).
   - Poista käyttämättömät templatet.

D) Dead routes
   - Listaa kaikki rekisteröidyt routet:
     ```
     flask routes > /tmp/routes.txt
     ```
   - Käy läpi: löytyykö `app.view_functions`-mappista funktioita,
     joihin ei ole linkkiä missään templatessa eikä testissä?
   - Poista vain ne joista olet täysin varma. Muut: lisää TODO-
     kommentti tai feature flag.

E) Keskeneräiset try/except-importit
   - `app/__init__.py:register_models`-funktiossa on useita
     `try: ... except Exception: pass`-blokkeja. Jos moduuli on
     jo vakaa, muuta ne suoriksi importeiksi (helpompi nähdä
     puuttuvat kentät tuotannossa). Jos moduuli on aidosti
     valinnainen, lisää selittävä kommentti.

F) Kuolleet env-muuttujat
   - Etsi `os.getenv(...)`-kutsuja joiden nimeä ei ole
     `.env.example`:ssä. Joko lisää `.env.example`:en tai poista
     käyttö.
   - Etsi `.env.example`:n muuttujia joita ei lue mikään
     `os.getenv` tai `app.config.get`. Poista turhat rivit.

G) `requirements.txt` — tarpeettomat paketit
   - Aja `pip install -U deptry` ja `deptry app/` (tai `pipreqs`).
   - Listaa paketit jotka ovat `requirements.txt`:ssä mutta joita
     ei tuoda missään tiedostossa. Esimerkkejä joita kannattaa
     tarkistaa:
       - `moto[s3]` — pitäisi olla vain `requirements-dev.txt`:ssä,
         koska se on testikirjasto.
       - `Pillow` — käytetäänkö muualla kuin `qrcode`-deppinä?
         (`qrcode[pil]` saattaa riittää.)
   - Poista vain ne joista olet 100 % varma.

Hyväksymiskriteerit:
- Jokainen ylläoleva alaluku on oma commit.
- `pytest -v` menee läpi joka commitin jälkeen.
- `ruff check app/ tests/` ei tuota uusia varoituksia.
- `mypy app/` ei tuota uusia virheitä (verrattuna lähtötilaan).
- PR:n kuvaukseen kirjoita lyhyt yhteenveto: "Poistettu X riviä,
  Y moduulia, Z deppiä. Säästöt: …"

Tärkeää:
- Älä poista turvallisuus-/audit-/2FA-koodia.
- Älä poista mitään mitä testit käyttävät.
- Älä koske `migrations/`-hakemistoon (ei poista vanhoja migraatioita
  vaikka ne näyttäisivät turhilta — historia on tärkeä).
- Jos mikään askel tuottaa epäselvyyttä, jätä se ja jatka seuraavaan.
  Parempi pieni voitto kuin rikki menevä deploy.
```

---

## Prompti 6 — Loppuverifiointi ja dokumentointi

> **ChatGPT-syöte → Cursor-toteutus.**

```
Tehtävä: Vahvista että edelliset 5 promptia on toteutettu loppuun ja
dokumentoi muutokset.

Konteksti:
- Promptit 1–5 on ajettu, tehty PR:t ja mergetty.
- Ennen tämän promptin ajoa, päivitä main-haara ja vedä uusin koodi.

Toimenpiteet:
1. Aja täysi smoke:
   - `git status` — puhdas.
   - `git ls-files | grep -E "(\.venv|venv/|node_modules|\.pytest_cache)"`
     ei tulokset.
   - `pytest -v` — vihreä.
   - `pytest tests/integration/` — vihreä (jos Docker saatavilla).
   - `flask db upgrade` — onnistuu nollasta.
   - `flask create-superadmin` — luo käyttäjän.
   - `flask backup-create` → `flask backup-restore --filename ...`
     — pyörähtää läpi.
   - `flask send-test-email` `MAIL_DEV_LOG_ONLY=1`-tilassa — exit 0.
   - `ruff check app/ tests/` — clean.
   - `black --check app/ tests/` — clean.
   - `mypy app/` — ei uusia virheitä.

2. Päivitä `SELVITYS_INIT_TEMPLATE_2026-05-07.md`:
   - Lisää uusi luku "2026-05-07 jälkeen tehdyt korjaukset".
   - Käy "Havaitut poikkeamat ja varauksin täytetyt kohdat" -lista
     läpi ja merkitse rasti / kommentti jokaiseen kuuteen kohtaan.

3. Lisää tai päivitä `CHANGELOG.md` (juurihakemistoon, jos sitä ei
   ole). Yksi merkintä per prompti, esim:
   ```
   ## 2026-05-07
   - chore: repon siivous (.venv, prosessitiedostot, .gitignore)
   - chore: requirements.txt pinned
   - feat(backups): erilliset email_templates ja settings JSON-
     exportit, salaisuudet redaktoituna
   - test: integraatio-acceptance-suite tests/integration/
   - refactor: dead-code-pyyhintä (kohta 23)
   ```

4. Avaa lopuksi viimeinen PR otsikolla "chore: init-template
   compliance pass — 2026-05-07" jossa pelkät dokumentaatiomuutokset.

Hyväksymiskriteerit:
- README, SELVITYS, CHANGELOG ovat ajan tasalla.
- Kaikki yllä olevat smoke-testit menevät läpi paikallisesti.
- `git log --oneline` näyttää selkeän, peräkkäisen historian
  prompteista 1–5.

Älä lisää uusia ominaisuuksia tähän PR:ään — vain dokumentaatio.
```

---

## Yhteenveto työnkulusta

1. Kopioi prompti 1 ChatGPT:lle. Pyydä: "Hio tästä Cursorille
   syötettävä tehtävänanto." ChatGPT palauttaa hiotun version.
2. Liitä hiottu versio Cursoriin. Anna sen ajaa, käytä
   automaattistä review-tilaa.
3. Aja testit, committaa, pushaa, mergeä.
4. Toista kohdat 1–3 prompteille 2 → 6.
5. Promptin 6 jälkeen sovellus täyttää init-templaten **kohdan 22
   acceptance-kriteerit ja kohdan 23 hengen** niin tarkasti kuin
   nykytilasta on järkevää.
