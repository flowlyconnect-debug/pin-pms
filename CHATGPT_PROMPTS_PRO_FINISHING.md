# Promptit — viimeistely ammattitasolle

Liitä jokainen prompti ChatGPT:lle erikseen. Aloita Prompt 0:lla (init-template-säännöt) jos uusi ChatGPT-keskustelu.

Suositeltu järjestys:

1. **Prompt CLEAN** — koodin siivous (TODO-kommentit, käyttämättömät moduulit, duplikoitu logiikka)
2. **Prompt 8G** — hinnoittelusäännöt (suunniteltu jo aiemmin, viimeistele)
3. **Prompt 8H** — Channel manager (vaatii asiakkaan päätöksen integraattorista)
4. **Prompt 8I** — Monikielisyys (i18n)
5. **Prompt 8J** — Saavutettavuus (a11y)
6. **Prompt 8K** — Vieraskommunikaatio-automaatio
7. **Prompt 8L** — Kuvagalleria

---

## PROMPT CLEAN — Koodin siivous

```
Tehtävä Cursorille: Siivoa Pindora PMS:n koodista turhat TODO-kommentit, mahdolliset käyttämättömät moduulit ja duplikoitu tenant-tarkistuslogiikka.

Tausta: Auditoinnissa havaittiin pieniä siisteysasioita. Ei rikkomuksia, vain tekninen velka.

Vaihe 1: TODO-kommenttien siivous
1. grep -rn "TODO\|FIXME\|XXX\|HACK" app/ — listaa kaikki
2. Jokaiselle päätös:
   - Jos kommentti on vielä relevantti → muuta GitHub Issuen viittaukseksi (esim. # See issue #42 in GitHub)
   - Jos epärelevantti → poista
3. Erityisesti: app/admin/routes.py rivi 122 ("If a safe, explicit superadmin cross-tenant override is introduced") — joko poista tai dokumentoi

Vaihe 2: Käyttämättömien moduulien selvitys
1. Tarkista nämä moduulit ja kysy itseltäsi: onko routea joka käyttää sitä? Onko UI-elementtiä joka kutsuu sitä?
   - app/subscriptions/
   - app/status/
   - app/owner_portal/
2. Aja jokaisen moduulin osalta:
   grep -rn "from app\.<moduuli>\|import app\.<moduuli>" app/ tests/
3. Per moduuli päätös:
   a) Jos käytetään (importteja löytyy) → varmista että dokumentaatio (README.md tai docstrings) selittää käyttötarkoituksen
   b) Jos EI käytetä missään → poista koko moduuli, lisää muutos commit-viestiin "removed unused module X"

Vaihe 3: Tenant-isolation-decoraattori
1. Aja: grep -rn "organization_id\s*!=\s*current_user.organization_id\|organization_id\s*!=\s*g\.api_key\.organization_id" app/
2. Listaa toistuvat patternit
3. Luo app/core/decorators.py:hin uusi:
   def require_tenant_access(model_name: str, id_arg: str = "id"):
       """Decorator that fetches model by id and verifies organization match.
       
       Usage: @require_tenant_access("invoice", id_arg="invoice_id")
              def view(invoice):
                  ...
       """
       ...
4. Refaktoroi 5-10 yleisintä paikkaa käyttämään decoraattoria
5. Säilytä taaksepäin yhteensopivuus — älä riko olemassa olevia testejä

Vaihe 4: localStorage-käyttö-tarkistus
1. grep -rn "localStorage\|sessionStorage" app/static/
2. Per löydös päätös:
   a) Jos data ei ole kriittinen (esim. UI-toggle joka voidaan menettää) → OK, dokumentoi
   b) Jos data on kriittinen (kuten teema-asetus) → siirrä http-only-cookieksi tai server-side settings-mekanismiin

Vaihe 5: Console.log-tarkistus
1. grep -rn "console\.log\|console\.debug" app/static/js/
2. Poista debug-tason kutsut, säilytä console.error/console.warn (ne ovat osa virheloggausta)

Vaihe 6: Testit
- Aja pytest -v --cov=app --cov-fail-under=80 — pitää säilyä vihreänä
- Lisää tests/test_tenant_decorator.py jos teit uuden decoraattorin

Tiedostot:
- app/admin/routes.py (TODO-poisto)
- app/core/decorators.py (uusi require_tenant_access)
- app/<refaktoroidut moduulit>/ (käyttämään decoraattoria)
- README.md (dokumentaatio jos säilytät jonkin moduulin)
- tests/test_tenant_decorator.py (uusi)

ÄLÄ:
- Älä poista moduuleja jotka käyttäjä saattaa haluta tulevaa varten — kysy ENSIN
- Älä rikkoa testejä
- Älä muuta API-skeemaa
- Älä muuta tietokantarakennetta

Aja lopuksi:
1. pytest -v --cov=app --cov-fail-under=80
2. git diff --stat — varmista että muutokset ovat järkeviä
3. Raportoi käyttäjälle: "Poistin X TODO-kommenttia, refaktoroin Y tenant-tarkistusta, käyttämättömät moduulit jätetty/poistettu (perustelu)."
```

---

## PROMPT 8H — Channel manager (kahdensuuntainen)

```
Tehtävä Cursorille: Toteuta kahdensuuntainen channel manager Booking.com:n ja Airbnb:n kanssa Channex-välipalvelun kautta.

ENNEN ALOITUSTA: Kysy käyttäjältä:
1. Onko Channex-tili olemassa? Käyttäjätunnukset?
2. Onko Booking.com:n ja Airbnb:n channel-mappingit luotu Channexissa?
3. Mitä kohteita synkronoidaan?

Tausta: Pelkkä iCal on yksisuuntainen — ei tue kaksisuuntaista varauksen, hinnan, saatavuuden synkronointia. Channex tarjoaa yhden API:n josta avautuu yhteys 100+ kanavaan. Tämä on PMS:n perusta, jonka on oltava paikallaan ennen kuin "ammattitaso" -tasoa voidaan väittää.

Init-template §2 (moduulirakenne, integrations), §6 (API), §10 (tietoturva), §11 (audit), §20 (service-kerros).

Vaihe 1: Channex-tutkinta
1. Tutki Channex-API: https://docs.channex.io/
2. Tunnista relevantit endpointit:
   - Properties (rooms/units)
   - Rate plans
   - Restrictions (min/max stay)
   - Bookings (incoming + outgoing)
   - Webhooks (booking.created, booking.modified, booking.cancelled)
3. HMAC-allekirjoitus ja API-key auth

Vaihe 2: Uusi moduuli (app/integrations/channex/)
- app/integrations/channex/__init__.py
- app/integrations/channex/client.py — REST-API-wrapperi
- app/integrations/channex/service.py — sync-logiikka
- app/integrations/channex/models.py — ChannexMapping (Pindora-property → Channex-property-id), ChannexRatePlan, jne.
- app/integrations/channex/scheduler.py — periodic sync jos webhookit eivät ole tarpeen
- app/integrations/channex/webhooks.py — käyttää Prompt 7C:n inbound-runkoa

Vaihe 3: Mappaus-malli
- ChannexMapping(id, organization_id, property_id, channex_property_id, channex_rate_plan_id, is_active, created_at)
- ChannexBookingMapping(id, reservation_id, channex_booking_id, channel_name, sync_status)

Vaihe 4: Sync-virrat

a) Pindora → Channex:
- Hinnan päivitys (Prompt 8G hinnoittelusäännöt → Channex rate plan update)
- Saatavuuden päivitys (Reservation.create → Channex availability close)
- Restriction-päivitys (min nights jne.)
- Käytä idempotency-keytä Prompt 7B:n mekanismilla

b) Channex → Pindora:
- Webhook saapuu → Prompt 7C inbound-runko vastaanottaa
- handle_channex_event() (uusi handler app/webhooks/handlers.py:ssä)
- Booking.created → luo Reservation Pindora-puolella
- Booking.modified → päivitä Reservation
- Booking.cancelled → mark Reservation cancelled + notification

Vaihe 5: Konfliktinratkaisu
- Jos Pindora ja Channex eroavat (esim. Pindora-puoli muutti hintaa offlineissa, Channex sai oman päivityksen) → conflict resolution policy
- Default: Channex voittaa (kanava-data on master)
- Admin-UI sallii manuaalisen ratkaisun
- Audit kaikki konfliktit

Vaihe 6: Admin-UI
- /admin/channex — yhteenveto:
  - Yhdistetyt kohteet
  - Viimeisin sync (success/error)
  - Aktiiviset kanavat
  - Konfliktit
- Mahdollisuus laukaista manuaalinen sync per kohde
- "Channel manager" -näkymä korvaa nykyisen iCal-only näkymän (säilytä iCal toissijaisena)

Vaihe 7: API
- POST /api/v1/integrations/channex/properties/<property_id>/connect
- DELETE /api/v1/integrations/channex/properties/<property_id>/connect
- POST /api/v1/integrations/channex/properties/<property_id>/sync (manuaalinen sync)
- @scope_required("integrations:write")

Vaihe 8: Audit-loki
- channex.property_connected
- channex.property_disconnected
- channex.sync_started
- channex.sync_completed
- channex.sync_failed
- channex.booking_created (Channex → Pindora)
- channex.booking_cancelled
- channex.conflict_detected
- channex.conflict_resolved

Vaihe 9: Env-muuttujat (.env.example)
CHANNEX_ENABLED=0
CHANNEX_API_KEY=
CHANNEX_API_BASE=https://staging.channex.io
CHANNEX_WEBHOOK_SECRET=

Vaihe 10: Testit (tests/test_channex.py)
- test_channex_disabled_returns_503_on_sync
- test_property_connect_creates_mapping
- test_inbound_webhook_creates_reservation
- test_inbound_webhook_invalid_signature_returns_401
- test_outbound_sync_pushes_availability
- test_conflict_detection_logs_audit
- test_tenant_isolation_in_mappings

Vaihe 11: Migraatio
- ChannexMapping, ChannexBookingMapping taulut
- flask db migrate

Tiedostot:
- app/integrations/channex/__init__.py, client.py, service.py, models.py, scheduler.py, webhooks.py
- app/admin/routes.py + templates/admin/channex_*.html
- app/api/routes.py
- app/webhooks/handlers.py (laajennus)
- migrations/versions/*.py
- .env.example
- tests/test_channex.py
- README.md

ÄLÄ:
- Älä koskaan tallenna Channex API-keyä selväkielisenä DB:hen — env-muuttujassa
- Älä unohda tenant-isolaatiota mappingeissa
- Älä riko olemassa olevaa iCal-integraatiota — säilytä se toissijaisena
- Älä tee suoraa Booking.com / Airbnb -integraatiota (kalliita ja vaativat sertifikaatit) — käytä välipalvelua
- Älä unohda audit-lokia ja idempotenssia

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_channex.py -v
3. pytest -v --cov=app --cov-fail-under=80
4. Manuaalitesti staging-Channexissa (jos mahdollista)
5. Tee kytkentä yhteen testikohteeseen, varmista että booking syncautuu
```

---

## PROMPT 8I — Monikielisyys (i18n)

```
Tehtävä Cursorille: Lisää Pindora PMS:lle i18n-tuki Flask-Babelilla. Kielet aluksi: suomi, englanti, ruotsi.

Tausta: Suomen markkinoilla pitää olla suomi + ruotsi. Englanti tarvitaan kansainvälisille vieraille. Tämä on yleinen vaatimus PMS:lle.

Init-template §17 (dokumentaatio).

Vaihe 1: Riippuvuus
- requirements.txt: Flask-Babel>=4.0

Vaihe 2: Konfiguraatio (app/__init__.py)
- from flask_babel import Babel
- babel = Babel()
- babel.init_app(app, locale_selector=_select_locale)
- _select_locale: 
  1. Käyttäjän asetus (user.locale jos kirjautuneena)
  2. Cookie "lang" jos asetettu
  3. Selaimen Accept-Language
  4. Default "fi"

Vaihe 3: User-malliin
- locale (string 5, default "fi")
- Migraatio

Vaihe 4: Käännös-tiedostojen rakenne
- app/translations/
  - fi/LC_MESSAGES/messages.po
  - en/LC_MESSAGES/messages.po
  - sv/LC_MESSAGES/messages.po
- pybabel extract -F babel.cfg -o app/translations/messages.pot .
- pybabel init -i app/translations/messages.pot -d app/translations -l fi
- (sama en, sv)
- pybabel compile -d app/translations

Vaihe 5: babel.cfg (juuri)
[python: app/**.py]
[jinja2: app/templates/**.html]

Vaihe 6: Templateissa
- {{ _('Hallintapaneeli') }} sijaan tekstit
- Käy läpi kaikki app/templates/admin/**/*.html ja app/templates/portal/**/*.html
- Vaihda staattiset tekstit `{{ _('...') }}` -muotoon

Vaihe 7: Sähköpostipohjat
- EmailTemplate-malliin lisää `locale`-sarake
- Ajetaan: yksi pohja per kieli per template_key
- Lähetyksessä valitaan: send_template(key, to=..., locale=user.locale or 'fi')
- Jos locale-pohjaa ei löydy → fallback fi

Vaihe 8: Kielenvaihtaja-UI
- Topbarissa dropdown: FI / EN / SV
- POST /preferences/locale → tallentaa user.locale + asettaa cookie

Vaihe 9: Päivämäärä- ja valuutta-formatointi
- Käytä Babelin format_datetime, format_currency
- Esim: laskun summa "1 234,56 €" suomeksi, "$1,234.56" englanniksi

Vaihe 10: Testit (tests/test_i18n.py)
- test_locale_selector_uses_user_setting
- test_locale_selector_uses_cookie_when_no_user
- test_email_template_falls_back_to_fi
- test_currency_formatted_per_locale

Tiedostot:
- requirements.txt (Flask-Babel)
- app/__init__.py (init Babel)
- app/users/models.py (locale-sarake)
- app/translations/{fi,en,sv}/LC_MESSAGES/messages.po
- app/templates/**/*.html (käytä _())
- app/email/models.py (locale-sarake)
- app/email/services.py (locale-fallback)
- app/templates/admin/base.html (kielenvaihtaja)
- migrations/versions/*.py
- tests/test_i18n.py
- README.md (i18n-osio: kuinka lisätä uusi kieli, kuinka kääntää)

ÄLÄ:
- Älä käännä admin-only-tekstejä jos admin on aina suomalainen — keskity vieras-portaaliin ensin
- Älä unohda päivämäärä/valuutta-formatointia
- Älä käytä _() -funktiota tietokantakentissä (ne pitää säilyä raakana)

Aja lopuksi:
1. pybabel compile -d app/translations
2. pytest tests/test_i18n.py -v
3. Manuaalitesti: vaihda kieli portaalissa, varmista että UI-tekstit ja sähköpostit muuttuvat
```

---

## PROMPT 8J — Saavutettavuus (a11y) WCAG 2.1 AA

```
Tehtävä Cursorille: Tee Pindora PMS:n admin-paneelista ja vieras-portaalista saavutettava WCAG 2.1 AA -tason mukaisesti.

Tausta: EU:n Web Accessibility Directive (2016/2102) edellyttää julkisten verkkopalveluiden saavutettavuutta. Yksityiset palvelut eivät ole pakottavasti, mutta saavutettavuus on hyvä käytäntö ja markkinaetu.

Vaihe 1: Audit
- Aja Lighthouse-audit /admin- ja /portal-sivustoille
- Kirjaa kaikki "Accessibility"-virheet
- Erityisesti tarkista: kuvien alt-tekstit, form-labelit, kontrasti, keyboard-navigointi, ARIA-roolit

Vaihe 2: Kuvien alt-tekstit
- Käy läpi kaikki <img>-tagit
- Lisää alt-attribuutti jokaiseen
- Logo: alt="Pin PMS"
- Ikoni: alt="" (decorative, screen reader skippaa)
- Kohteen kuva: alt="<kohteen nimi> - kuva 1/N"

Vaihe 3: Form-labelit
- Jokaisella input-elementillä pitää olla joko <label for="id"> tai aria-label="..."
- Tarkista kaikki app/templates/**/*.html lomakkeet
- Erityisesti search-input, hidden-inputit

Vaihe 4: Kontrasti
- Tarkista CSS-värit Lighthouse-tools:lla
- Tekstin ja taustan kontrasti vähintään 4.5:1 (normaali) tai 3:1 (suuri teksti)
- Korjaa CSS-muuttujat jos eivät täytä rajoja

Vaihe 5: Keyboard-navigointi
- Kaikki interaktiiviset elementit pitää olla saavutettavissa Tab-näppäimellä
- Focus-tila pitää olla näkyvä (CSS :focus-visible)
- Skip-link "Hyppää sisältöön" sivun alussa

Vaihe 6: ARIA-roolit
- <nav role="navigation">, <main role="main">, <aside role="complementary">
- Modal-dialogit: aria-modal="true", aria-labelledby="..."
- Tabulaatti listat: aria-label

Vaihe 7: Tekstin koko ja zoom
- Käytä rem-yksiköitä (ei px) kaikissa tekstikentissä
- Sivu pitää olla luettava 200 % zoomatessa

Vaihe 8: Kielen tunniste
- <html lang="fi"> (riippuu locale-arvosta)
- Päivitä app/templates/admin/base.html ja portal/base.html

Vaihe 9: Testit
- tests/test_accessibility.py:
  - test_images_have_alt
  - test_form_inputs_have_labels
  - test_lang_attribute_set
  - test_skip_link_present
- Manuaalitesti: NVDA / JAWS / VoiceOver testaus

Vaihe 10: Saavutettavuusseloste
- Luo app/templates/accessibility.html
- Reitti /accessibility-statement (julkinen, EI vaadi authentikointia)
- Sisältö: kuinka yhteyttä, mitä rajoituksia, milloin päivitetty

Tiedostot:
- app/templates/**/*.html (alt-tekstit, ARIA)
- app/static/css/admin.css, portal.css (kontrasti)
- app/static/css/skip-link.css (uusi)
- app/templates/admin/base.html, portal/base.html (skip-link, lang)
- app/templates/accessibility.html (uusi)
- app/core/__init__.py (reitti)
- tests/test_accessibility.py (uusi)

ÄLÄ:
- Älä käytä pelkkiä värejä informaation välittämiseen (esim. punainen "virheellinen" — lisää myös ikoni tai teksti)
- Älä piilota focus-tilaa CSS:llä (älä koskaan outline:none ilman korvaavaa focus-visible-tilaa)
- Älä unohda saavutettavuusseloste-sivua

Aja lopuksi:
1. pytest tests/test_accessibility.py -v
2. Aja Lighthouse-audit uudestaan, varmista että Accessibility-skoori >= 95
3. Manuaalitesti: navigoi koko admin-paneeli vain Tab-näppäimellä
```

---

## PROMPT 8K — Vieraskommunikaatio-automaatio

```
Tehtävä Cursorille: Lisää automaattiset sähköpostit ja muistutukset vieraille varauksen elinkaaren mukaan.

Tausta: Modernit PMS:t lähettävät automaattisesti:
- Vahvistus varauksen jälkeen
- Check-in-ohjeet 1-2 päivää ennen
- Check-out-muistutus aamulla
- Palautekysely 1 päivä check-outin jälkeen

Vaihe 1: Uusi moduuli (app/messaging/)
- app/messaging/__init__.py
- app/messaging/services.py — automation logic
- app/messaging/scheduler.py — APScheduler-job

Vaihe 2: Sähköpostipohjat (app/email/seed_data.py)
- guest_booking_confirmation
- guest_checkin_instructions (lähetetään 2 päivää ennen)
- guest_checkout_reminder (lähetetään check-outin aamuna)
- guest_feedback_request (lähetetään 1 päivä check-outin jälkeen)

Vaihe 3: Triggerit
- Booking.created → confirmation lähetetään heti
- Päivittäinen scheduler-job:
  - Hae varaukset joiden check-in on huomenna → lähetä checkin-ohjeet
  - Hae varaukset joiden check-out on tänään → lähetä reminder
  - Hae varaukset joiden check-out oli eilen → lähetä feedback

Vaihe 4: Per-organisaatio-asetukset
- Settingsissä: messaging.enabled (bool), messaging.send_feedback (bool)
- Admin voi ottaa pois tietyt automaatiot

Vaihe 5: Testit
- test_confirmation_sent_on_reservation_create
- test_checkin_reminder_sent_2_days_before
- test_feedback_skipped_when_disabled
- test_messages_use_guest_locale

Vaihe 6: Audit
- messaging.confirmation_sent
- messaging.checkin_reminder_sent
- messaging.feedback_request_sent

Tiedostot:
- app/messaging/__init__.py, services.py, scheduler.py
- app/email/seed_data.py (uudet pohjat)
- app/reservations/services.py (kytke confirmation)
- app/__init__.py (käynnistä messaging-scheduler)
- .env.example (MESSAGING_SCHEDULER_ENABLED, GUEST_FEEDBACK_DELAY_DAYS)
- tests/test_messaging.py

ÄLÄ:
- Älä lähetä vieraan luvalla — pyydä opt-in varauksen yhteydessä
- Älä lähetä yli 1 viesti per päivä per vieras
- Älä unohda audit-lokia
- Älä käytä vieraan PII:tä yli sen mitä on välttämätöntä

Aja lopuksi:
1. pytest tests/test_messaging.py -v
2. Manuaalitesti: luo testivaraus, varmista vahvistus-sähköposti tulee
```

---

## PROMPT 8L — Kuvagalleria kohteille

```
Tehtävä Cursorille: Lisää kuvagalleria-toiminto kohteille (properties).

Tausta: Vieras-portaalissa vieraat haluavat nähdä kohteen kuvat ennen varausta. Adminin pitää voida ladata, järjestellä ja poistaa kuvia.

ENNEN ALOITUSTA: Kysy käyttäjältä:
1. Mihin kuvat tallennetaan? (Render-volyymi, S3, R2, Backblaze B2)
2. Onko CDN käytössä?

Vaihe 1: PropertyImage-malli
- id, organization_id, property_id, url, thumbnail_url, alt_text, sort_order, file_size, content_type, uploaded_by, created_at

Vaihe 2: Upload-flow
- Admin: /admin/properties/<id>/images → drag-drop upload
- Backend: /api/v1/properties/<id>/images @scope_required("properties:write")
- Käytä Pillow:ta thumbnaileihin (esim. 800x600 max + 200x150 thumb)
- POISTA EXIF (Pillow Image.open + save ilman exif)
- Tallenna providerille (S3/R2/Render)

Vaihe 3: Storage-rajapinta
- app/storage/__init__.py: upload(file, key), delete(key), get_url(key)
- app/storage/local.py — Render-volyymi
- app/storage/s3.py — boto3 S3-yhteensopivat (AWS, R2, Backblaze)
- Konfiguraatio: STORAGE_BACKEND=local|s3, S3_*

Vaihe 4: Vieras-portaali
- Property-detail-sivulla galleria (slider tai grid)
- Lazy-loading
- Saavutettavuus: alt-tekstit pakollisia

Vaihe 5: Kuvankäsittely
- Resize ja optimointi: max 2 MB per kuva
- Salli WebP, JPEG, PNG
- Älä salli SVG (XSS-riski)

Vaihe 6: Testit
- test_image_upload_strips_exif
- test_image_resize_max_dimensions
- test_image_only_org_can_upload
- test_image_delete_removes_from_storage
- test_svg_upload_rejected

Tiedostot:
- app/properties/models.py (PropertyImage)
- app/storage/ (uusi)
- app/admin/routes.py + templates (UI)
- app/api/routes.py (upload-endpoint)
- app/portal/routes.py + templates (galleria)
- migrations/
- requirements.txt (Pillow, boto3 jos S3)
- .env.example (STORAGE_*)
- tests/test_images.py

ÄLÄ:
- Älä salli SVG-uploadia (XSS-riski)
- Älä unohda EXIF-poistoa (sisältää GPS-koordinaatit jne.)
- Älä unohda tenant-isolaatiota
- Älä unohda CDN-cache-invalidointia kun kuva muutetaan

Aja lopuksi:
1. pytest tests/test_images.py -v
2. Manuaalitesti: lataa kuva, varmista thumbnail luotu, EXIF poistettu
```

---

## Yhteenveto

| Prompti | Aika (Cursor) | Riippuvuus |
|---------|---------------|------------|
| CLEAN | 1–2 h | Ei |
| 8G hinnoittelu | 8–12 h | CLEAN ensin |
| 8H Channel manager | 20–30 h | Asiakkaan päätös integraattorista |
| 8I i18n | 10–15 h | Voi alkaa milloin vain |
| 8J a11y | 6–10 h | Mieluiten 8A:n jälkeen |
| 8K vieraskommunikaatio | 5–8 h | 8I:n jälkeen (käännökset) |
| 8L kuvagalleria | 8–12 h | Asiakkaan päätös storagesta |

Kaikki noudattavat init-templatea 100 %. Aja CLEAN ensin, sitten kysy asiakkaalta channel manager + storage -ratkaisuista, sitten 8G + 8I + 8J rinnakkain.
