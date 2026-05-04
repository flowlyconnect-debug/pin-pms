# Promptit ennen maksuintegraatiota — osa 2

Tehty: Prompt 7B (idempotency), 7C (webhook-runko). Tämä tiedosto sisältää lisää template-mukaisia parannuksia jotka kannattaa tehdä ennen Prompt 8:aa, sekä CSP-bugi jonka huomasin mobiilibugin tutkimuksessa.

> **Muista:** Liitä jokainen prompti ChatGPT:lle erikseen. Ennen ensimmäistä, muistuta ChatGPT:tä Prompt 0:n säännöistä. Yksikään lisäys ei saa rikkoa init-templatea.

---

## PROMPT 7D — CSP-nonce ja inline-scriptien siivous (KRIITTINEN)

```
Tehtävä Cursorille: Korjaa CSP-rikkomukset siten että strict CSP (script-src 'self') säilyy mutta admin-sivut toimivat.

Tausta: Init-template §10 vaatii XSS-suojausta ja tiukkaa CSP:tä. Nykyinen CSP `script-src 'self'` (app/core/security_headers.py rivi 21) ESTÄÄ kaikki inline-scriptit. Useat admin-sivut käyttävät inline-`<script>`-tageja, ja kalenteri-sivu lataa FullCalendar:n CDN:stä. Nämä eivät toimi nykyisellä CSP:llä:

- app/templates/admin/calendar.html — inline + CDN (https://cdn.jsdelivr.net/...)
- app/templates/admin/leases/edit.html — inline
- app/templates/admin/leases/new.html — inline
- app/templates/admin/maintenance/edit.html — inline
- app/templates/admin/maintenance/new.html — inline
- app/templates/admin/reservations/edit.html — inline (2 kpl)
- app/templates/admin/reservations/new.html — inline
- app/templates/admin_api_keys.html — inline event handler (onclick=, onload=, jne.)
- app/templates/admin_webhooks.html — inline event handler

ÄLÄ lisää 'unsafe-inline' CSP:hen — se rikkoo init-template §10. Käytä SEN SIJAAN CSP-noncea tai siirrä JS staattisiin tiedostoihin.

Vaihe 1: CSP-nonce-mekanismi (app/core/security_headers.py)
- Generoi per-request nonce ennen response-vaihetta:
  @app.before_request
  def _generate_csp_nonce():
      from secrets import token_urlsafe
      from flask import g
      g.csp_nonce = token_urlsafe(16)
- Lisää Jinja-globaali (app/__init__.py register_extensions tai vastaavassa kohdassa):
  @app.context_processor
  def _csp_nonce_ctx():
      return {"csp_nonce": getattr(g, "csp_nonce", "")}
- Päivitä _DEFAULT_CSP käyttämään noncea:
  csp = (
      "default-src 'self'; "
      "img-src 'self' data:; "
      "style-src 'self' 'unsafe-inline'; "  # CSS-pseudonyysin nonce on vaikeaa, säilytä
      f"script-src 'self' 'nonce-{g.csp_nonce}' https://cdn.jsdelivr.net; "
      "frame-ancestors 'none'; "
      "base-uri 'self'; "
      "form-action 'self'"
  )
  HUOM: CSP rakennetaan request-kohtaisesti _apply()-funktiossa, EI luokkamuuttujana.

Vaihe 2: Päivitä jokainen inline-script lisäämään nonce
- Käytä Edit-työkalua jokaiseen tiedostoon:
- <script> → <script nonce="{{ csp_nonce }}">
- Mutta: SUOSITTELE EKSPLISIITTISESTI ulos siirtoa staattiseen .js-tiedostoon kun mahdollista.

Vaihe 3: Suositeltu — siirrä mahdollisuuksien mukaan staattisiin tiedostoihin
- Esimerkkitiedosto: app/static/js/admin-calendar.js (FullCalendar-init)
- Esimerkkitiedosto: app/static/js/admin-form-helpers.js (lomakkeiden helperit)
- HTML: <script src="{{ url_for('static', filename='js/admin-calendar.js') }}" defer></script>
- Etu: ei tarvitse nonce, JS:n CDN-cache toimii

Vaihe 4: Inline event handlers (onclick=, onload=, jne.)
- nonce EI auta inline-handler-attribuuteille
- AINOA tapa: muuta ne addEventListener-kutsuiksi (luo per-sivu .js-tiedosto)
- Esimerkki: <button onclick="confirmDelete()">  →  <button data-action="delete" data-id="123">
  + JS: document.querySelectorAll('[data-action="delete"]').forEach(btn => btn.addEventListener('click', () => confirmDelete(btn.dataset.id)))

Vaihe 5: Verifiointi browseissa (testi-Cursorin sijaan, manuaalinen)
- Avaa /admin/calendar — kalenteri renderöityy
- Avaa /admin/reservations/new — sivun JS toimii
- Avaa /admin sivu mobiilissa — hampurilainen toimii
- Tarkista DevTools → Console: ei CSP-violaatioita
- Tarkista DevTools → Network → response headers: Content-Security-Policy sisältää 'nonce-XXXX'

Vaihe 6: Testit
- tests/test_security_headers.py: laajenna testit:
  - test_csp_includes_nonce: CSP-headerin sisältää 'nonce-XXX' -fragmentin
  - test_csp_nonce_unique_per_request: kaksi pyyntöä → eri noncet
  - test_csp_does_not_use_unsafe_inline: 'unsafe-inline' EI saa olla script-src:ssä
  - test_csp_allows_jsdelivr_for_calendar: 'https://cdn.jsdelivr.net' on script-src:ssä
- tests/test_admin_calendar.py (uusi): GET /admin/calendar → 200 + nonce löytyy script-tageista
- tests/test_admin_inline_scripts.py (uusi): meta-testi joka iteroi listalla annetut admin-sivut, hakee niiden HTML:n ja varmistaa että jokainen <script>-tag joko (a) on src=... muotoa tai (b) sisältää nonce-attribuutin

Tiedostot:
- app/core/security_headers.py (nonce + dynaaminen CSP)
- app/__init__.py (context_processor)
- app/templates/admin/calendar.html (nonce + jsdelivr säilyy)
- app/templates/admin/leases/edit.html, new.html (nonce tai siirto staticiin)
- app/templates/admin/maintenance/edit.html, new.html (nonce tai siirto staticiin)
- app/templates/admin/reservations/edit.html, new.html (nonce tai siirto staticiin)
- app/templates/admin_api_keys.html (siirto staticiin — inline-handlerit eivät toimi noncella)
- app/templates/admin_webhooks.html (siirto staticiin)
- app/static/js/admin-*.js (uudet)
- tests/test_security_headers.py (laajennus)
- tests/test_admin_calendar.py, test_admin_inline_scripts.py (uudet)

ÄLÄ:
- Älä lisää 'unsafe-inline' tai 'unsafe-eval' CSP:hen
- Älä mahdollista CDN:ää muille tiedostoille kuin jsdelivr (FullCalendar) — pidä whitelist mahdollisimman pieni
- Älä käytä samaa noncea useammalle pyynnölle (turvallisuusriski)
- Älä unohda päivittää testiä joka tarkistaa CSP:n sisällön — se kaatuu nyt

Aja lopuksi:
1. pytest tests/test_security_headers.py tests/test_admin_calendar.py tests/test_admin_inline_scripts.py -v
2. pytest -v (kaikki testit edelleen vihreänä)
3. Manuaalitesti selaimessa: avaa kaikki listatut admin-sivut, varmista DevTools-konsolissa ei CSP-violaatioita
4. Manuaalitesti mobiilissa: hampurilaisvalikko aukeaa
```

---

## PROMPT 7E — Sentry + monitoring (TÄRKEÄ ENNEN MAKSUJA)

```
Tehtävä Cursorille: Lisää Sentry-virheraportointi ja laajenna /api/v1/health/ready tarkistamaan ulkoiset riippuvuudet.

Tausta: Init-template §14 mainitsee suorituskyvyn ja §22 hyväksymiskriteerit. Maksuintegraatiossa virheet ovat liikevaihtokriittisiä — ilman Sentry-monitoringia maksuvirheet jäisivät huomaamatta. Health-endpoint on jo olemassa mutta ei tarkista Mailgunia tai tulevaa Stripe-yhteyttä.

Vaihe 1: Riippuvuus
- requirements.txt: lisää sentry-sdk[flask]>=1.40

Vaihe 2: Konfiguraatio
- .env.example sisältää jo SENTRY_DSN= (rivi 149) — säilytä
- app/config.py: SENTRY_DSN, SENTRY_TRACES_SAMPLE_RATE on jo
- Lisää: SENTRY_ENVIRONMENT (default = FLASK_ENV-arvo)
- Lisää: SENTRY_RELEASE (default = git-revision tai "development")

Vaihe 3: Sentry-init (app/__init__.py)
- create_app() kutsuu init_sentry(app) jos SENTRY_DSN on asetettu
- init_sentry:
  - import sentry_sdk
  - sentry_sdk.init(
      dsn=app.config["SENTRY_DSN"],
      integrations=[FlaskIntegration(), SqlalchemyIntegration()],
      traces_sample_rate=app.config.get("SENTRY_TRACES_SAMPLE_RATE", 0.1),
      environment=app.config.get("SENTRY_ENVIRONMENT") or app.config.get("FLASK_ENV"),
      release=app.config.get("SENTRY_RELEASE"),
      send_default_pii=False,  # älä lähetä PII Sentryyn
      before_send=_redact_sentry_event,
  )
- _redact_sentry_event suodattaa pois: cookies, authorization-headers, password-arvot, x-api-key, kaikki app/core/logging.py:n RedactingFilter:n maskattavat avaimet
  - Tämä on kriittinen GDPR-vaatimus — älä vuoda PII:tä Sentryyn

Vaihe 4: Health-endpoint laajennus (app/status/service.py readiness_status)
- Tarkista lisäksi:
  - Mailgun-yhteys: GET https://api.mailgun.net/v3/<DOMAIN>/log?limit=1 (timeout 2 s)
    - Onnistuu (HTTP 200): mailgun_ok=True
    - Virhe: mailgun_ok=False, mailgun_error=<truncated msg>
  - APScheduler tila: tarkista että kaikki kytketyt jobit ovat ajettavissa (next_run_time != None)
  - Tietokannan latenssi: SELECT 1 timinkö, > 500 ms = "slow"
  - Tarkista: backups.last_success_at < 25 h sitten (päivittäinen + ylimäärä)
- payload[]:
  - "checks": [{"name": "db", "ok": true, "latency_ms": 5}, ...]
  - "ok": all(c["ok"] for c in checks)
- Jos backupin viimeinen onnistunut > 36 h sitten → ei estä readinessia, mutta varoita
  Sentry-message "backup_overdue" + audit "monitoring.backup_overdue"

Vaihe 5: Slow-query loggi → Sentry breadcrumbs
- Olemassa oleva slow-query-logging (SQL_SLOW_QUERY_MS env) lähettää nyt vain logiin
- Lisää Sentryyn breadcrumb (sentry_sdk.add_breadcrumb) jokaisesta hitaasta kyselystä
- Lähetä Sentryyn varoitus jos > 5 hidasta kyselyä saman pyynnön aikana

Vaihe 6: Sentry-test-CLI
- @app.cli.command("sentry-test")
- Lähetä: sentry_sdk.capture_message("Sentry test from Pin PMS CLI")
- Tulosta: "Sent test event to Sentry. Check your project at <DSN_URL>."
- Hyödyllinen tuotantoasennuksen verifioinnissa.

Vaihe 7: Audit-loki — uusi monitoring-kategoria
- "monitoring.health_check_failed" — kun readiness palauttaa ok=false
- "monitoring.backup_overdue" — yllä
- "monitoring.mailgun_unreachable" — kun health tarkistaa Mailgunia ja saa virheen

Vaihe 8: Testit
- tests/test_sentry.py:
  - test_sentry_init_skips_when_dsn_missing
  - test_sentry_redact_strips_secrets (käytä before_send funktiota suoraan)
  - test_sentry_redact_strips_authorization_header
  - test_sentry_test_cli_command
- tests/test_health_ready_extended.py:
  - test_health_includes_db_check
  - test_health_includes_mailgun_check_when_configured
  - test_health_returns_503_when_db_slow_or_down
  - test_health_warns_when_backup_overdue (mockattu monkeypatch)

Tiedostot:
- requirements.txt (sentry-sdk)
- app/__init__.py (init_sentry, _redact_sentry_event)
- app/config.py (SENTRY_ENVIRONMENT, SENTRY_RELEASE)
- app/status/service.py (laajennettu readiness_status)
- app/core/logging.py (Sentry-breadcrumb hidasta-kyselyt)
- app/cli.py (sentry-test komento)
- .env.example (SENTRY_ENVIRONMENT, SENTRY_RELEASE)
- tests/test_sentry.py, test_health_ready_extended.py (uudet)

ÄLÄ:
- Älä koskaan lähetä Sentryyn raakaa request.json:ia (sisältää PII)
- Älä lähetä Sentryyn cookies-headereita
- Älä lähetä Sentryyn API-avaimia tai sessiotunnuksia
- Älä cachaa Mailgun-tarkistusta enempää kuin 30 sekuntia (muuten outage näkyy myöhässä)
- Älä koskaan poista SENTRY_DSN-arvon vaikutusta CONFIG-arvosta logiin

Aja lopuksi:
1. pytest tests/test_sentry.py tests/test_health_ready_extended.py -v
2. pytest -v (kaikki testit vihreänä)
3. Manuaalitesti: aseta SENTRY_DSN testiprojektiin, aja `flask sentry-test`, tarkista Sentry UI
4. curl /api/v1/health/ready — tulisi näyttää uudet checks-kentät
```

---

## PROMPT 7F — Webhook-perusta tuottamaan tapahtumia (joka tukee maksuja myöhemmin)

```
Tehtävä Cursorille: Lisää outbound-webhookien laukaisu PMS:n keskeisille tapahtumille jotta integraatioasiakkaat saavat oikea-aikaisia ilmoituksia. Sama mekanismi käytetään myöhemmin maksuwebhookeissa.

Tausta: Prompt 7C loi webhook-rungon (subscriptions, deliveries, retry). Tämä prompti kytkee sen liiketoimintaan: kun tapahtuma syntyy, se julkaistaan rekisteröityneille subscribereille. Init-template §6 (API), §11 (audit), §20 (service-kerros).

Vaihe 1: Tapahtumahaarat (events)
- Listaa tuetut event_type-arvot constanteina (app/webhooks/events.py):
  RESERVATION_CREATED = "reservation.created"
  RESERVATION_CANCELLED = "reservation.cancelled"
  RESERVATION_UPDATED = "reservation.updated"
  INVOICE_CREATED = "invoice.created"
  INVOICE_PAID = "invoice.paid"  # Prompt 8:aa varten
  INVOICE_REFUNDED = "invoice.refunded"  # Prompt 8:aa varten
  GUEST_CHECKED_IN = "guest.checked_in"
  GUEST_CHECKED_OUT = "guest.checked_out"
  MAINTENANCE_REQUESTED = "maintenance.requested"

Vaihe 2: Pub/sub-kerros (app/webhooks/publisher.py)
- publish(event_type: str, organization_id: int, payload: dict) -> None
  - Hae kaikki WebhookSubscription joiden organization_id matchaa, is_active=True, ja events sisältää event_type
  - Jokaiselle: kutsu webhooks.services.dispatch(subscription_id, event_type, payload)
  - Tämä on synkroninen ENSIMMÄINEN yritys — Prompt 7C:n retry-scheduler hoitaa loput
  - Audit: action="webhook.published", target_type="webhook_event", context={event_type, subscriber_count}

Vaihe 3: Kytke publisher liiketoimintaan
- app/reservations/services.py create_reservation(): kutsu publish("reservation.created", org_id, {...})
- app/reservations/services.py cancel_reservation(): kutsu publish("reservation.cancelled", ...)
- app/billing/services.py create_invoice(): publish("invoice.created", ...)
- app/portal/services.py check_in(): publish("guest.checked_in", ...)
- app/portal/services.py check_out(): publish("guest.checked_out", ...)
- app/maintenance/services.py create_request(): publish("maintenance.requested", ...)

Vaihe 4: Payload-skeemat (app/webhooks/schemas.py)
- Per event-type funktio joka rakentaa minimaalisen, EI-PII-vuotavan payloadin
- Esim. build_reservation_created_payload(reservation) -> dict:
  {
    "event": "reservation.created",
    "occurred_at": "2026-05-04T10:00:00Z",
    "organization_id": 1,
    "data": {
      "reservation_id": 123,
      "unit_id": 42,
      "start_date": "2026-06-01",
      "end_date": "2026-06-05",
      "status": "confirmed",
      "guest_id": 99  # ID, ei email!
    }
  }
- Älä koskaan sisällytä payloadiin: password_hash, totp_secret, kortin tiedot, henkilötunnusta

Vaihe 5: Skeema-dokumentaatio
- app/api/docs.py: lisää "Webhook events" -sektio OpenAPI-tiedostoon
- Listaa kaikki event_type:t ja niiden payload-rakenne (esimerkkeineen)
- Maininta: "Käytä outbound-allekirjoituksen varmennukseen samaa HMAC-SHA256-mekanismia kuin inbound — secret saadaan webhook subscriptionin luonnissa"

Vaihe 6: Asynkroninen vaihtoehto (suositus)
- Synkroninen publish() voi hidastaa request-vastausaikaa jos subscriptioneita on monta
- VAIHTOEHTO 1: APScheduler-job joka käsittelee jonon (helpoin)
- VAIHTOEHTO 2: Threading-pohjainen async-publish (riskialttein)
- VAIHTOEHTO 3: SQS / RabbitMQ (overkill nyt)
- Suositus: Aluksi synkroninen, mutta lisää WEBHOOK_PUBLISH_ASYNC env-flag (default False) joka kytkee taustaajon
- Synkronisesti: max 3 subscriberia per request, muutoin enqueue

Vaihe 7: Testit (tests/test_webhook_events.py)
- test_reservation_created_publishes_to_matching_subscriptions
- test_subscription_with_no_matching_events_not_called
- test_subscription_in_other_org_not_called (tenant-isolation)
- test_publish_handles_dispatch_failure_gracefully (yksi sub epäonnistuu, muut saavat)
- test_publish_does_not_block_request_when_async (mockattu)
- test_payload_does_not_leak_pii (esim. guest.email EI saa olla payloadissa, vain guest.id)
- test_audit_log_for_webhook_published

Vaihe 8: Admin-UI päivitys
- /admin/webhooks/<id> — näytä viimeiset 20 deliverya tämän subscriptionin
- Painike "Lähetä testi-event" joka julkaisee dummy-payloadin tähän subscribereen (vain superadmin)

Tiedostot:
- app/webhooks/events.py, publisher.py, schemas.py (uudet)
- app/reservations/services.py (publish-kutsut)
- app/billing/services.py (publish-kutsut)
- app/portal/services.py (publish-kutsut)
- app/maintenance/services.py (publish-kutsut)
- app/api/docs.py (dokumentaatio)
- app/admin/routes.py (testi-event-painike)
- app/templates/admin_webhooks*.html (UI)
- .env.example (WEBHOOK_PUBLISH_ASYNC)
- tests/test_webhook_events.py (uusi)

ÄLÄ:
- Älä julkaise tapahtumia ennen kuin liiketoiminta-DB-transaktio on commitoitu (muuten subscriber saa tapahtumasta tiedon ennen kuin se on pysyvä)
  → Käytä @event.listens_for(Session, "after_commit") tai julkaise vasta service-funktion lopussa db.session.commit():n jälkeen
- Älä julkaise tapahtumia jotka eivät ole tenant-isolaatiossa
- Älä unohda audit-lokia
- Älä koskaan vuoda PII tai card-tietoja webhook-payloadissa
- Älä toista subscriberia jolla on is_active=False

Aja lopuksi:
1. pytest tests/test_webhook_events.py -v
2. pytest -v (kaikki testit vihreänä, mukaan lukien Pindora Lock -regressio Prompt 7C:stä)
3. Manuaalitesti: luo webhook subscription admin-UI:sta, luo varaus → tarkista että subscriberin URL:iin tulee POST
```

---

## PROMPT 7G — Sähköpostien jonotus + retry (TÄRKEÄ ENNEN MAKSUJA)

```
Tehtävä Cursorille: Varmista että sähköpostit lähetetään luotettavasti — jonossa, retry-logiikalla, ja audit-lokituksella.

Tausta: Init-template §7 (sähköposti) ja §14 (suorituskyky) sanovat: "sähköpostit lähetetään taustatyönä". Tällä hetkellä on EmailQueue olemassa (app/email/), mutta retry-logiikkaa ja saturation-skenaarioita ei välttämättä ole testattu. Maksuvahvistukset ja kuitit lähtevät sähköpostilla → puuttuva kuitti = huono UX.

Vaihe 1: Tarkista nykytila
- Lue app/email/__init__.py, services.py, scheduler.py
- Onko EmailQueue-tauluraketta vai lähetetäänkö suoraan?
- Onko retry-logiikkaa epäonnistuneille viesteille?

Vaihe 2: Lisää (jos puuttuu) EmailQueue-malli
- app/email/models.py — EmailQueueItem:
  id, organization_id (FK, nullable kun system-mail), template_key, recipient_email,
  context (JSON), status (pending/sending/sent/failed), attempt_count (int),
  last_error (Text, nullable), next_attempt_at (DateTime, nullable),
  created_at, sent_at (nullable)
- Migraatio
- Backoff: 1 min, 5 min, 30 min, 2 h, 12 h (max 5 yritystä)

Vaihe 3: send_template() refaktorointi
- Nykyisen send_template(...) sisään: tallenna EmailQueueItem, EI lähetä heti
- Uusi: send_template_now(...) joka lähettää suoraan (vain CLI-testitarkoituksiin)
- send_template_sync(...) joka odottaa lähetyksen valmistumista (käytä esim. password_resetille — käyttäjä odottaa)

Vaihe 4: Scheduler päivitys (app/email/scheduler.py)
- Käy läpi queue:n pending-rivit joiden next_attempt_at < now()
- Jokaiselle: lähetä Mailgunilla
  - Onnistuu: status=sent, sent_at=now()
  - Epäonnistuu: attempt_count+1, last_error, next_attempt_at = now + backoff[attempt_count]
  - Yli 5 yritystä: status=failed, audit + admin-notification

Vaihe 5: Audit-loki
- "email.queued" — kun jonoon lisätään
- "email.sent" — onnistuneesti lähetetty
- "email.failed" — yli 5 yritystä epäonnistunut
- "email.retried" — uudelleenyrityksissä (debug-tason audit, voi olla jätetty pois)

Vaihe 6: Admin-UI
- /admin/email-queue — superadmin näkee jonon tilanteen
- Lista: recipient, template, status, attempt_count, last_error
- Painike "Yritä uudelleen" failed-tilassa olevalle viestille
- Painike "Peruuta" pending-tilassa olevalle viestille

Vaihe 7: Health-endpoint
- /api/v1/health/ready palauttaa "email_queue": {"pending": N, "failed": N, "oldest_pending_age_minutes": M}
- Jos failed > 10 → ok=false (varoitus)
- Jos oldest_pending > 30 min → varoitus (mutta ok=true)

Vaihe 8: Testit (tests/test_email_queue_retry.py — uusi)
- test_email_queue_retries_failed_send (mockattu Mailgun fail → success)
- test_email_queue_max_attempts_marks_failed
- test_email_queue_audit_log_for_each_state
- test_email_queue_backoff_schedule
- test_admin_can_retry_failed_message
- test_password_reset_uses_sync_path (ei queue, käyttäjä odottaa)
- test_health_reports_queue_status

Tiedostot:
- app/email/models.py (EmailQueueItem laajennus)
- app/email/services.py (send_template-refaktor)
- app/email/scheduler.py (retry-logiikka)
- app/admin/routes.py (UI)
- app/templates/admin_email_queue.html (uusi)
- migrations/versions/*.py (auto)
- app/status/service.py (queue health)
- tests/test_email_queue_retry.py (uusi)

ÄLÄ:
- Älä blokkaa request-vastausta odottamalla sähköpostin lähetystä (paitsi password reset jossa käyttäjä odottaa flash-viestiä)
- Älä tallenna context-arvoissa salaisuuksia (token suoraan, käytä url_for tokenin URL:lle)
- Älä unohda tenant-isolaatiota — yhden orgin admin ei näe toisen orgin queue:ta
- Älä retryta yli 5 kertaa (resurssien hukka)
- Älä unohda kun `MAIL_DEV_LOG_ONLY=1` — silloin "lähetys" on lokitus, jonotus ei ole tarpeen

Aja lopuksi:
1. pytest tests/test_email_queue_retry.py -v
2. pytest -v
3. Manuaalitesti: aja flask shell, kutsu send_template(...), tarkista admin/email-queue → status=pending → odota 1 min → status=sent
4. Manuaalitesti negatiivinen: aseta väärä Mailgun-domain, lähetä viesti → tarkista että retryt toimivat ja lopulta status=failed
```

---

## Suositeltu järjestys

1. **Korjaa CSP/inline-script-bugi (Prompt 7D)** ENSIN — kalenteri ja muut admin-sivut ovat nyt rikki
2. **Sentry + monitoring (Prompt 7E)** — pohja tuotantoa varten, kannattaa olla ennen maksuja
3. **Webhook-publisher (Prompt 7F)** — käyttää 7C:n runkoa, valmistaa Prompt 8:lle
4. **Email-jonotus + retry (Prompt 7G)** — kuitti-flow vaatii luotettavan sähköpostin

Ajat ChatGPT:n kautta, kuten aiemmin. Kun jokainen on valmis ja pytest vihreä, tuo Claudelle tarkistettavaksi ennen committia.

---

## Mitä JÄTETÄÄN myöhemmälle (PMS-laajennukset, ei pakollisia ennen maksuja)

Nämä on listattu AUDIT_REPORT.md:n kohdissa D.5 (siivouskalenteri), D.6 (hinnoittelusäännöt), D.7 (raporttien laajennus), D.8 (monikielisyys), D.9 (channel manager). Ne **eivät ole laillisuusvaatimuksia eivätkä init-template-rikkomuksia** — ne ovat PMS-puolen ammattilaislaajennuksia. Tee ne maksujen jälkeen.

Yksi mahdollinen poikkeus: **D.8 monikielisyys (Flask-Babel)** kannattaa harkita ennen Prompt 8:aa, jos asiakkaalla on ulkomaisia vieraita — maksusivut ja kuitit pitää sitten saada vähintään suomi+englanti samalla.

---

## Mitä asiakkaalle pitää kysyä (lisätty edellisestä)

Aiempaan listaan (Stripe vs. Visma Pay, maksutavat, ajoittaminen jne.) lisää:

7. **Webhook-tilaajat**:
   - Onko PMS:llä ulkoisia integroijia jotka haluavat reaaliaikaisia ilmoituksia? (Booking.com, Airbnb omilla webhookeilla — ei vaadi tätä)
   - Vai onko tämä vain "tulevaisuutta varten" -ominaisuus?

8. **Sähköpostit**:
   - Lähetetäänkö kuitti automaattisesti maksun jälkeen?
   - Tarvitaanko erilainen pohja maksumuistutus / maksun viivästys -tilanteisiin?
   - Lähetetäänkö myös PDF-liitteenä vai pelkkä linkki?

9. **Kirjanpito**:
   - Procountor- / Netvisor-integraatio nyt vai myöhemmin?
   - Kuukauden päätösrutiini — automatisoitu vai manuaalinen?
