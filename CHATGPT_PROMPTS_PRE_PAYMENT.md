# Promptit ennen maksuintegraatiota (Prompt 8 valmistelu)

Liitä jokainen prompti ChatGPT:lle erikseen. ChatGPT:lle pitää muistuttaa Prompt 0:n säännöistä ja kontekstista (sama init-template kuin aiemmin).

Aja järjestyksessä: 7B (idempotency) → 7C (webhook-runko) → vasta sitten Prompt 8 (maksuintegraatio).

Molemmat promptit noudattavat init-templatea 100 %: service-kerros, audit-loki, oikeustarkistus, tenant-isolation, validointi, env-konfig, testit.

---

## PROMPT 7B — Idempotency-key-mekanismi

```
Tehtävä Cursorille: Luo geneerinen idempotency-key-mekanismi joka voidaan käyttää maksu-webhookien ja muiden duplikaatti-arkojen API-kutsujen yhteydessä.

Tausta: Maksuintegraatio (Stripe/Visma Pay) lähettää webhookit useita kertoja samasta tapahtumasta. Ilman idempotenssia luodaan duplikaattimaksuja tai tuplakuitteja. Sama mekanismi suojaa myös tavallisia POST-pyyntöjä clientin uudelleenyrityksiltä. Tämän pitää valmistua ENNEN Prompt 8:aa, jotta maksulogiikka voi nojautua valmiiseen idempotency-tarkistukseen.

Vaihe 1: Uusi moduuli (app/idempotency/)
- app/idempotency/__init__.py
- app/idempotency/models.py — IdempotencyKey-malli:
  - id, key (string 128, UNIQUE), endpoint (string 128, esim. "POST /api/v1/payments"), 
  - request_hash (string 64, SHA-256 normalisoidusta payloadista),
  - response_status (int), response_body (Text, max 64 KiB), 
  - organization_id (FK, nullable jos webhook),
  - created_at, expires_at (default now() + 24h, env IDEMPOTENCY_KEY_TTL_SECONDS jo olemassa)
- app/idempotency/services.py:
  - get_or_create(key, endpoint, request_hash) -> tuple[IdempotencyKey, bool]
    - Jos key olemassa JA request_hash sama: palauta (row, False) → kutsuja palauttaa cached responsen
    - Jos key olemassa JA request_hash eri: nosta IdempotencyKeyConflict
    - Jos key ei olemassa: luo rivi, palauta (row, True)
  - record_response(idempotency_row, status, body) -> None
  - prune_expired() -> int (poistaa expired-rivit, kutsutaan APSchedulerista)

Vaihe 2: Migraatio
- flask db migrate -m "add_idempotency_keys_table"
- Tarkista että UNIQUE constraint on (key) -kentällä
- Lisää indeksi (expires_at) prune-kyselyille
- flask db upgrade

Vaihe 3: Decorator API-reiteille
- app/idempotency/decorators.py @idempotent_post(endpoint_name: str)
- Decorator:
  1. Lukee headerista "Idempotency-Key" (tai "X-Idempotency-Key")
  2. Jos puuttuu JA endpoint vaatii sen → 400 Bad Request
  3. Laskee request_hash JSON-bodysta (sorted keys, normalized)
  4. Kutsuu get_or_create(key, endpoint, request_hash)
  5. Jos cached vastaus löytyi → palauta se (HTTP 200, sama body)
  6. Jos uusi → suorita view-funktio, tallenna response cacheen, palauta

Vaihe 4: APScheduler-job
- app/idempotency/scheduler.py: prune_expired() ajetaan päivittäin (esim. 04:00 UTC)
- Lisää env-muuttujat .env.example:
  IDEMPOTENCY_PRUNE_SCHEDULER_ENABLED=1
  IDEMPOTENCY_PRUNE_SCHEDULE_CRON=0 4 * * *
- Kytke schedulerin start() -funktioon (samalla tavalla kuin email_scheduler ja backup_scheduler)

Vaihe 5: Audit-loki
- audit_record("idempotency.replay", ...) kun cached response palautetaan (kerro mitä kutsuttiin uudestaan)
- audit_record("idempotency.conflict", ...) kun sama key eri payloadilla → potentiaalinen hyökkäys
- Jälkimmäinen on FAILURE-status

Vaihe 6: Testit (tests/test_idempotency.py)
- test_idempotency_key_blocks_duplicate_request: sama key + sama payload → cached response palautuu, view-funktio EI ajeta toista kertaa
- test_idempotency_key_conflict_on_different_payload: sama key + eri payload → 409 Conflict
- test_missing_idempotency_key_returns_400: vaadittu mutta puuttuu → 400
- test_expired_idempotency_key_allows_new_request: vanhentunut → uusi suoritus
- test_prune_removes_expired_rows: aja prune_expired() → expired-rivit poistuvat
- test_idempotency_audit_log_created: replay ja conflict kirjautuvat audit-lokiin
- Kaikki testit käyttävät pytest-fixtureja (no real DB writes ulos test-transaktiosta)

Vaihe 7: API-doc päivitys
- app/api/docs.py — kuvaile Idempotency-Key-headerin käyttöä OpenAPI-dokumentaatiossa
- Esimerkki: "Send 'Idempotency-Key: <unique-string>' header to safely retry POST requests"

Tiedostot:
- app/idempotency/__init__.py, models.py, services.py, decorators.py, scheduler.py (uudet)
- migrations/versions/*.py (auto)
- .env.example (uudet muuttujat)
- app/__init__.py (kytke prune-scheduler)
- app/api/docs.py (dokumentaatio)
- tests/test_idempotency.py (uusi)

ÄLÄ:
- Älä tallenna response_bodyn sisältöön salaisuuksia tai tokeneita (huom: kuten Stripe-webhook-vastauksen sisältöön ei pidä jättää signed payload)
- Älä cache-vastauksia jotka ovat 5xx-virheitä (suorita ne aina uudestaan)
- Älä cache-vastauksia jotka ovat 4xx-virheitä paitsi 422 Unprocessable Entity (validointivirhe → cache OK)
- Älä unohda tenant-isolaatiota: organization_id pitää tallentaa kun saatavilla
- Älä unohda audit-lokia replay/conflict-tapahtumille
- Älä luo decoratoria joka serialisoi raakaa requestia — käytä JSON-payloadia normalisoituna

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_idempotency.py -v
3. pytest -v (kaikki testit edelleen vihreänä)
4. Manuaalitesti: curl -X POST -H "Idempotency-Key: test-1" --data '{...}' /api/v1/some-endpoint kahdesti — toinen palauttaa cachen
```

---

## PROMPT 7C — Webhook-runko (joka tukee maksu-webhookeja)

```
Tehtävä Cursorille: Luo geneerinen webhook-infrastruktuuri vastaanottoon (inbound) ja lähettämiseen (outbound). Maksu-webhookit (Stripe, Visma Pay) tulevat käyttämään tätä Prompt 8:ssa. Inbound-webhookien jo olemassa oleva logiikka (app/integrations/pindora_lock/) tulee yhtenäistää tämän rungon kanssa.

Tausta: Init-template ei vaadi webhookeja eksplisiittisesti, mutta §6 (API), §11 (audit), §20 (service-kerros) ja §10 (tietoturva) edellyttävät että webhookien käsittely on:
- HMAC-allekirjoituksella varmennettu
- Idempotenssi-suojattu (käyttää Prompt 7B:n mekanismia)
- Audit-lokitettu
- Tenant-isolaatiossa (organization_id mukana kun mahdollista)
- Retry-suojattu lähtevien webhookien osalta
- Geneerinen niin että uusi provider lisätään 1 tiedostolla

Vaihe 1: Uusi moduuli (app/webhooks/)
- app/webhooks/__init__.py
- app/webhooks/models.py — kaksi mallia:

  WebhookEvent (inbound):
  - id, provider (string 64), event_type (string 128), 
  - external_id (string 128, providerin oma id, NULL jos ei ole), 
  - payload (JSON), signature (string 256, masked log:ssa), 
  - signature_verified (bool, default False), processed (bool, default False),
  - processing_error (Text, nullable), 
  - organization_id (FK, nullable kun ei tiedossa),
  - created_at, processed_at
  - Indeksit: (provider, external_id) UNIQUE, (provider, processed)

  WebhookSubscription (outbound):
  - id, organization_id (FK), url (string 512), 
  - secret_hash (string 64, SHA-256 secretistä — secret EI tallenneta selväkielisenä), 
  - events (JSON array, esim. ["reservation.created", "invoice.paid"]),
  - is_active (bool), 
  - last_delivery_at (DateTime), last_delivery_status (int),
  - failure_count (int, default 0),
  - created_at, updated_at, created_by_user_id (FK)

  WebhookDelivery (outbound delivery log):
  - id, subscription_id (FK), event_type (string 128), 
  - payload (JSON), payload_hash (string 64), 
  - signature (string 256, masked), 
  - response_status (int, nullable), 
  - response_body (Text, max 8 KiB),
  - attempt_number (int), 
  - delivered_at (DateTime, nullable kun pending),
  - next_retry_at (DateTime, nullable),
  - created_at

- app/webhooks/services.py:

  Inbound:
  - verify_signature(provider, payload_bytes, signature_header, secret) -> bool
    - Kutsuu providerin omaa varmennusfunktiota (esim. stripe_webhook_verify())
    - Aluksi tukee yleisen HMAC-SHA256-tarkistuksen (käytetty Pindora Lockin webhookissa)
  - record_inbound_event(provider, event_type, external_id, payload, signature, signature_verified, organization_id) -> WebhookEvent
    - Idempotency-tarkistus: jos (provider, external_id) on jo olemassa, palauta olemassa oleva
    - Audit-loki: action="webhook.received", target_type="webhook_event"
  - mark_processed(event_id, error: str | None) -> None
    - Asettaa processed=True, processing_error=error
    - Audit-loki: action="webhook.processed" tai "webhook.failed"

  Outbound:
  - dispatch(subscription_id, event_type, payload) -> WebhookDelivery
    - Laskee HMAC-SHA256-allekirjoituksen subscription.secretillä (haetaan Settingsistä tai ympäristöstä)
    - HUOM: secret EI tallenneta DB:hen selväkielisenä → ratkaise tallennustapa: joko secret_hash + verify-only, tai kryptaus Fernetillä (Fernet-key olemassa env CHECKIN_FERNET_KEY)
    - Yritys 1 lähetetään heti (sync). Epäonnistuessa luo retry-rivin (next_retry_at = now + 1 min, 5 min, 30 min, 2 h, 12 h)
    - Audit-loki: action="webhook.dispatched", target_type="webhook_delivery"
  - retry_pending_deliveries() -> int
    - APScheduler-jobin kutsu, käy läpi pending-rivit joiden next_retry_at < now()
    - Yli 5 epäonnistuneen yrityksen jälkeen merkitse subscription.is_active=False ja audit-loki "webhook.subscription_disabled"

Vaihe 2: Generic inbound-reitti (app/webhooks/routes.py)
- POST /api/v1/webhooks/<provider> — geneerinen vastaanotto-endpoint
- EI vaadi API-avainta (whitelistataan in app/api/__init__.py before_request -hookin jälkeen, mutta tämä reitti ei ole api_bp:ssä — käytä erillistä webhooks_bp:tä joka rekisteröidään /api/v1/webhooks-prefiksillä)
- Vaiheet:
  1. Hae provider URL-parametrista
  2. Tarkista että provider on tunnettu (whitelist: ["stripe", "vismapay", "pindora_lock"])
  3. Lue raw payload (älä parsi vielä)
  4. Hae signature-header (provider-spesifinen: Stripe="Stripe-Signature", Visma Pay="X-VismaPay-Signature", Pindora="X-Signature")
  5. Hae provider-secret asetuksista (settings.get("webhooks.<provider>.secret")) — secret on Fernet-kryptattu DB:ssä
  6. verify_signature(...) — jos epäonnistuu → 401 Unauthorized + audit "webhook.invalid_signature"
  7. Parsi JSON payload — jos epäonnistuu → 400 + audit
  8. Idempotency: kutsu get_or_create(idempotency_key=external_id) Prompt 7B:n mekanismilla
  9. record_inbound_event(...) (palauttaa WebhookEvent)
  10. Dispatch providerin handleriin (esim. stripe_webhook_handler.handle(event)) — handler on määritelty per provider, mutta ei vielä toteutettu (Prompt 8 lisää Stripe-handlerin)
  11. mark_processed(event_id, error) tuloksen mukaan
  12. Palauta 200 OK aina kun signature on validi (provider odottaa 2xx-vastausta)

Vaihe 3: Outbound-rekisteröinti (admin-UI + API)
- Admin-UI: /admin/webhooks (superadmin-only, 2FA-vahvistus)
  - Lista subscriptioneista
  - Luo uusi: URL, events[], secret (näkyvä vain luonnissa, kuten API-key)
  - Deaktivoi
  - Näytä viimeiset 10 deliverya per subscription
- API: 
  - GET /api/v1/webhooks/subscriptions @scope_required("webhooks:read")
  - POST /api/v1/webhooks/subscriptions @scope_required("webhooks:write")
  - DELETE /api/v1/webhooks/subscriptions/<id> @scope_required("webhooks:write")
- Audit-loki kaikille toimille

Vaihe 4: APScheduler-job
- app/webhooks/scheduler.py: retry_pending_deliveries() ajetaan 1 min välein
- Env-muuttujat .env.example:
  WEBHOOK_DELIVERY_SCHEDULER_ENABLED=1
  WEBHOOK_DELIVERY_RETRY_INTERVAL_SECONDS=60

Vaihe 5: Yhtenäistä Pindora Lock -webhook
- app/integrations/pindora_lock/ olemassa olevat webhook-rivit pitää siirtyä uudelle rungolle
- Säilytä taaksepäin yhteensopivuus (sama URL, sama signature)

Vaihe 6: Asetukset
- Webhook-secrets tallennetaan Settings-tauluun, NOT plain text:
  - webhooks.stripe.secret
  - webhooks.vismapay.secret
  - webhooks.pindora_lock.secret
  - is_secret=True KAIKKIIN (audit-lokin masking aktivoituu)

Vaihe 7: Testit (tests/test_webhooks.py + tests/test_webhooks_outbound.py)
- test_inbound_invalid_signature_returns_401
- test_inbound_valid_signature_creates_event
- test_inbound_duplicate_external_id_is_idempotent
- test_outbound_dispatch_signs_payload
- test_outbound_retry_after_failure
- test_outbound_disabled_after_5_failures
- test_audit_log_for_received_processed_invalid_signature
- test_secret_is_not_stored_plaintext
- test_secret_is_not_in_logs (RedactingFilter)
- test_pindora_lock_webhook_still_works (regressio)

Vaihe 8: API-dokumentaatio
- app/api/docs.py — dokumentoi /api/v1/webhooks/* endpointit
- Lisää webhook-skeema OpenAPI-tiedostoon
- Esimerkki HMAC-allekirjoituksen tarkistuksesta clientin puolelta

Tiedostot:
- app/webhooks/__init__.py, models.py, services.py, routes.py, scheduler.py (uudet)
- app/admin/routes.py (uusi /admin/webhooks)
- app/templates/admin_webhooks*.html (uudet)
- app/api/__init__.py (rekisteröi webhooks_bp)
- app/api/docs.py (dokumentaatio)
- app/integrations/pindora_lock/ (yhtenäistä uudelle rungolle)
- migrations/versions/*.py (auto)
- .env.example (uudet muuttujat)
- tests/test_webhooks.py, test_webhooks_outbound.py (uudet)

ÄLÄ:
- Älä koskaan tallenna webhook-secrettiä selväkielisenä DB:hen (käytä Fernet tai hash+verify-only)
- Älä logita signature-headeria selväkielisenä — RedactingFilter pitää maskata
- Älä luota client-IP:hen webhookin tunnistuksessa (HMAC on ainoa luotettava)
- Älä unohda tenant-isolaatiota outbound-subscriptioneissa (org_id aina)
- Älä unohda kun signature epäonnistuu: audit FAILURE + 401 mutta EI 400
- Älä riko Pindora Lockin olemassa olevaa webhookia — ole tarkka regression-testissä
- Älä yritä käsitellä webhookit synkronisesti yli 5 sekunnin (käytä 200 OK + taustakäsittely jos hidas)

Aja lopuksi:
1. flask db upgrade
2. pytest tests/test_webhooks.py tests/test_webhooks_outbound.py -v
3. pytest -v (kaikki testit edelleen vihreänä, mukaan lukien Pindora Lock -regressio)
4. Manuaalitesti: simuloi Stripe-webhook stripe-CLI:llä → 200 OK + audit-loki
```

---

## Mitä asiakkaalta pitää kysyä ennen Prompt 8:aa

Lähetä tämä kysymys asiakkaalle (ChatGPT voi muotoilla sähköpostin):

```
Pindora PMS:n maksuintegraatio on seuraava vaihe. Ennen toteutusta tarvitaan päätökset:

1. **Maksuvälittäjä** (valitse vähintään yksi):
   - Stripe (kansainvälinen, 1.4 % + 0.25 € per kortti)
   - Visma Pay (Suomi, suositumpi pien-Airbnb-yrityksille, tukee verkkopankki+MobilePay)
   - Sekä että (kumpi default?)

2. **Maksutavat**:
   - Vain kortti?
   - Verkkopankit (kotimaiset)?
   - MobilePay / Apple Pay / Google Pay?
   - Kuukausilasku (yritysasiakkaille)?

3. **Maksun ajoittaminen**:
   - Heti varauksen yhteydessä (deposit %)?
   - Ennen sisäänkirjautumista (full payment)?
   - Sisäänkirjautumisen yhteydessä?
   - Joustava per omistaja?

4. **Hyvitykset (refunds)**:
   - Kuka saa peruuttaa? (admin / superadmin / vieras itse?)
   - Peruutusehdot (30/14/7 päivää ennen)?
   - Onko peruutusvakuutus erikseen?

5. **PCI-DSS-vastuu**:
   - Ovatko Stripe Checkout / Visma Pay -lomakkeet riittävät? (Suosittelen kyllä — meillä ei tarvitse käsitellä korttinumeroita itse)

6. **Kirjanpito**:
   - Tarvitaanko Procountor / Netvisor -integraatio?
   - Kuukausittainen tilitysraportti omistajille?
```

---

## Suositeltu työjärjestys

1. **Pidä asiakkaalta vastauksia odottaessa nykyiset commitit kasassa** — älä pushaa kunnes pytest on vihreä
2. **Aja Prompt 7B (idempotency)** ChatGPT:lle — ~2-3 h Cursorilla
3. **Aja Prompt 7C (webhook-runko)** ChatGPT:lle — ~4-6 h Cursorilla
4. **Asiakas vastaa kysymyksiin** → muokkaa Prompt 8:aa vastausten mukaan
5. **Aja Prompt 8 (maksuintegraatio)** — nyt valmis pohja → Cursorin työ on selkeästi kapeampi

Tässä järjestyksessä jokainen vaihe rakentaa edelliselle. Maksuintegraatio (Prompt 8) ei joudu keksimään webhook- tai idempotency-mekanismia uudelleen, vaan käyttää valmista runkoa.
