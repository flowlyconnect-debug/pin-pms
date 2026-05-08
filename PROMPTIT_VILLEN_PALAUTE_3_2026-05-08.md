# Promptit Villen palautteen kolmas kierros (2026-05-08)

**Tarkoitus:** kaksi itsenäistä ChatGPT-syötettä jotka noudattavat
init-templaten kohtia **§6 (API), §10 (tietoturva), §11 (audit-loki),
§12 (tenant-isolaatio), §13 (UI), §14 (suorituskyky), §15
(virheenkäsittely), §16 (testaus), §20 (service-kerros)**.

**Työnkulku:** Sinä → ChatGPT (*"Hio tästä Cursorille syötettävä tarkka
tehtävänanto. Säilytä init-template -viittaukset ja hyväksymiskriteerit.
Älä lisää skooppia."*) → Cursor → `pytest -v`.

**Suoritusjärjestys:** **E → F**.
E on bugifix laskumaksuun, F on UX-parannus huone-listaan.

**Havaintojen lähde:** käyttöliittymäkuvakaappaukset 2026-05-08:
1. Laskun maksupainike palauttaa raakaa JSON:ia
   `{"data": {"count": 1}, "error": null, "success": true}` selaimessa
   sen sijaan että näyttäisi onnistumisilmoituksen ja palaisi
   laskunäkymään.
2. /admin/properties/<id>-näkymässä huoneet-listalla ei näy onko
   huone juuri nyt vapaa vai varattu — vastaus löytyy vain klikkaamalla
   kalenteria.

---

## Prompti E — Laskun maksumerkinnän redirect-flash + API-yhtenäisyys

> **ChatGPT-syöte → Cursor-toteutus.** Pieni, mutta init-templaten
> §6, §11, §13, §15, §20 mukainen.

```
Tehtävä: Korjaa Pin PMS:n /admin/invoices/<id>/mark-paid -toiminto niin,
että HTML-lomakkeesta tuleva POST palauttaa redirectin + flash-viestin
laskunäkymään, ja Accept: application/json -pyynnöistä palautetaan
edelleen yhtenäinen JSON-envelope.

Konteksti:
- Käyttäjä painaa /admin/invoices-listassa "Merkitse maksetuksi"-
  painiketta. Selain navigoi nykyisellään raakaan JSON-vastaukseen
  `{"success": true, "data": {"count": 1}, "error": null}`, koska
  reitti palauttaa AINA jsonify(...). Toiminto onnistuu, vain UI-
  käsittely puuttuu.
- Init-template §6 vaatii API:lle yhtenäisen JSON-envelopen — sitä
  EI saa rikkoa. Säilytä JSON-vastaus AJAX/API-pyynnöille.
- Init-template §13 vaatii: "onnistuneet toiminnot näytetään
  käyttäjälle". Flash-viesti hoitaa tämän server-rendered UI:lle.
- Init-template §11 vaatii audit-rivin kriittisistä tapahtumista —
  laskun statusmuutos kuuluu näihin.
- Init-template §15 vaatii hallitun virheenkäsittelyn.
- Init-template §20 vaatii: "Routeissa ei saa olla raskasta
  liiketoimintalogiikkaa." Tarkista että laskunmuutos on jo
  app/billing/services.py:ssa; jos ei, siirrä sinne.

Toimenpiteet:
1. Tarkista nykytila:
   - Tiedostot: app/admin/routes.py (mark_paid-endpoint),
     app/billing/services.py (mark_invoice_paid tai vastaava),
     app/templates/admin/invoices/list.html ja
     app/templates/admin/invoices/detail.html
   - Onko olemassa erillinen API-reitti app/api/routes.py:ssa? Jos
     on, varmista että sen palautusrakenne ei muutu.

2. Refaktoroi reitti:
   ```python
   @admin_bp.post("/invoices/<int:invoice_id>/mark-paid")
   @login_required
   @admin_required
   @tenant_scoped  # init template §12
   def invoices_mark_paid(invoice_id: int):
       try:
           invoice = billing_service.mark_invoice_paid(
               invoice_id=invoice_id,
               organization_id=current_user.organization_id,
               actor_user_id=current_user.id,
           )
       except billing_service.InvoiceNotFoundError as err:
           # init template §15 — selkeä virheviesti
           if _wants_json():
               return error_envelope(
                   "invoice_not_found", str(err), status=404
               )
           flash("Laskua ei löytynyt.", "error")
           return redirect(url_for("admin.invoices_list"))
       except billing_service.InvoiceStateError as err:
           if _wants_json():
               return error_envelope(
                   "invalid_state", str(err), status=409
               )
           flash(f"Laskun tilaa ei voi muuttaa: {err}", "error")
           return redirect(
               url_for("admin.invoices_detail", invoice_id=invoice_id)
           )

       # init template §6 — yhtenäinen JSON-envelope säilyy
       if _wants_json():
           return success_envelope({"invoice_id": invoice.id,
                                    "status": invoice.status})

       # init template §13 — onnistunut toiminto käyttäjälle
       flash("Lasku merkitty maksetuksi.", "success")
       return redirect(
           url_for("admin.invoices_detail", invoice_id=invoice.id)
       )
   ```
   Lisää tarvittaessa apurifunktio `_wants_json()`:
   ```python
   def _wants_json() -> bool:
       return request.accept_mimetypes.best == "application/json" \
              or request.is_xhr \
              or request.headers.get("X-Requested-With") == "XMLHttpRequest"
   ```

3. Varmista että app/billing/services.py:n mark_invoice_paid:
   - kirjoittaa audit-rivin (init template §11):
     ```python
     audit_record(
         "invoice.marked_paid",
         status=AuditStatus.SUCCESS,
         actor_type=ActorType.USER,
         actor_id=actor_user_id,
         organization_id=organization_id,
         target_type="invoice",
         target_id=invoice.id,
         context={"previous_status": prev_status,
                  "amount": str(invoice.total_incl_vat)},
     )
     ```
   - rajaa kyselyn organization_id:lla (init template §12 — älä luota
     pelkkään frontendiin).
   - heittää `InvoiceStateError`-poikkeuksen jos lasku on jo
     paid/cancelled, ei muuta tilaa hiljaa.

4. Lisää CSRF-token kaikkiin lomakkeisiin
   (admin/invoices/list.html, detail.html):
   ```html
   <form method="post"
         action="{{ url_for('admin.invoices_mark_paid', invoice_id=row.id) }}"
         data-confirm="Merkitäänkö lasku maksetuksi?">
     <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
     <button class="btn btn-secondary">Merkitse maksetuksi</button>
   </form>
   ```
   data-confirm hyödyntää olemassa olevaa admin-confirm.js-skriptiä
   (init template §13: "vaaralliset toiminnot vaativat vahvistuksen").

5. Käy läpi MUUT samanlaiset admin-toiminnot ja korjaa sama kuvio.
   Listaa kaikki:
   - /admin/invoices/<id>/cancel
   - /admin/invoices/<id>/send (sähköposti)
   - /admin/leases/<id>/activate
   - /admin/leases/<id>/end
   - /admin/leases/<id>/cancel
   - /admin/reservations/<id>/check-in
   - /admin/reservations/<id>/check-out
   - /admin/reservations/<id>/cancel
   - /admin/maintenance/<id>/resolve
   - /admin/maintenance/<id>/cancel
   - /admin/payments/<id>/refund
   Jos jokin näistä palauttaa raw-JSONin lomake-POST:lle, sovella
   sama redirect+flash -kuvio.

6. Testit (init template §16):
   `tests/test_admin_invoices.py` (luo tai laajenna):
   a) test_mark_paid_html_form_redirects_with_flash — POST ilman
      Accept: application/json -headeria → 302 + flash-viesti
      "Lasku merkitty maksetuksi.".
   b) test_mark_paid_json_request_returns_envelope — POST
      Accept: application/json -headerilla → 200 + envelope
      `{"success": true, "data": {...}, "error": null}`.
   c) test_mark_paid_already_paid_returns_409_or_flash_error —
      pari versiota: HTML → flash error + redirect detail-näkymään,
      JSON → 409 + envelope error.
   d) test_mark_paid_writes_audit_row — audit_logs sisältää uuden
      rivin action="invoice.marked_paid".
   e) test_mark_paid_enforces_tenant_scope — toisen organisaation
      lasku → 404, ei 200.
   f) test_mark_paid_requires_csrf_token — POST ilman tokenia → 400.

7. Manuaalitesti (acceptance-checklista):
   - flask seed-demo-data
   - /admin/invoices/<id> → "Merkitse maksetuksi"
   - Selain pysyy admin-näkymässä, näkee "Lasku merkitty maksetuksi"-
     vihreän bannerin, ja laskun status on "Maksettu".
   - curl -H "Accept: application/json" -X POST .../mark-paid
     → JSON-envelope.

Hyväksymiskriteerit:
- Kaikki 6 testiä menevät läpi.
- Olemassa olevat testit (tests/test_billing.py,
  tests/test_admin_pms.py) eivät rikkoudu.
- /admin/invoices-näkymä toimii ilman raakaa JSON-vastausta selaimessa.
- API-vastaukset (/api/v1/invoices/...) säilyttävät yhtenäisen
  envelope-rakenteen (init template §6).
- audit_logs-taulussa on rivi jokaisesta maksumerkinnästä
  (init template §11).
- tests/test_ui_finnish.py ei valita uusia jäänteitä.

Älä:
- Muuta API-vastauksen JSON-kentän nimiä (taaksepäin yhteensopivuus).
- Lisää uusia kenttiä Invoice-malliin tämän promptin alla.
- Poista olemassa olevia API-reittejä /api/v1/invoices alta.
- Käytä request.is_json sellaisenaan — Flask-WTF asettaa Content-Typen
  joskus virheellisesti. Käytä Acceptin parsimista.
```

---

## Prompti F — "Tila"-sarake huoneet-listaan (Pekan kohta 2 jatko)

> **ChatGPT-syöte → Cursor-toteutus.** Init-templaten §12, §13, §14,
> §16, §20 mukainen.

```
Tehtävä: Lisää Pin PMS:n /admin/properties/<id>-näkymässä olevaan
huoneet-taulukkoon "Tila"-sarake, joka näyttää yhdellä silmäyksellä
onko huone juuri nyt vapaa, varattu, vai vaihtopäivänä — ja koska
se seuraavaksi muuttuu.

Konteksti:
- Asiakas Pekka 2026-05-06 puhelin-skenaariossa: "olisi näkymä joka
  kertoo onko vapaana vai ei". Saatavuusmatriisi /admin/availability
  vastaa tähän kalenterimuodossa, mutta huoneet-lista (taulukko) on
  silti sokea — Pekka joutuu klikkaamaan kalenterisivulle joka kerta.
- Uusi sarake näkyy myös /admin/units-näkymässä jos sellainen on.
- Init-template §13: "tärkeimmät toiminnot löytyvät nopeasti" ja
  "yksinkertainen, selkeä".
- Init-template §14: vältettävä N+1-kyselyitä.
- Init-template §20: liiketoimintalogiikka palvelukerrokseen, ei
  templateen.

Toimenpiteet:
1. Lisää app/properties/services.py:hin uusi palvelufunktio:
   ```python
   def list_units_with_availability_status(
       organization_id: int,
       property_id: int | None = None,
       as_of: date | None = None,
   ) -> list[dict]:
       """
       Palauttaa huoneet + niiden saatavuustilan annettuna päivämääränä.
       Yksi tietokantakysely (LEFT JOIN reservations + maintenance)
       välttää N+1-ongelman (init template §14).

       Tenant-rajaus: organization_id pakollinen (init template §12).
       """
   ```
   Palautettava dict per unit:
   ```python
   {
       "id": int,
       "name": str,
       "unit_type": str | None,
       "property_name": str,
       "current_state": "free" | "reserved" | "transition" | "maintenance" | "blocked",
       "current_guest_name": str | None,   # vain reserved/transition
       "current_reservation_id": int | None,
       "occupied_until": date | None,      # reserved: viimeinen yöpymispäivä
       "next_reservation_at": date | None, # free: seuraava varaus
       "next_guest_name": str | None,
       "days_until_next": int | None,      # free: päivien määrä
   }
   ```

2. Toteutus yhdellä kyselyllä:
   - LEFT JOIN reservations ON reservations.unit_id = units.id
     AND reservations.start_date <= :as_of < reservations.end_date
     AND reservations.status IN ('confirmed','active')
   - LEFT JOIN seuraavaan tulevaan varaukseen
   - LEFT JOIN aktiiviseen huoltopyyntöön (status NOT IN
     ('resolved','cancelled') AND due_date <= :as_of)
   - Tenant-rajaus: WHERE units.property_id IN
     (SELECT id FROM properties WHERE organization_id = :org_id)
   - Lisää indeksit jos puuttuvat (Alembic-migraatio):
     reservations(unit_id, start_date, end_date),
     reservations(unit_id, status, start_date)

3. Lisää keskitetty status-label-helperi
   app/core/i18n.py:hin (jos lisätty Prompti 10:ssä, hyödynnä):
   ```python
   UNIT_AVAILABILITY_LABELS_FI = {
       "free": "Vapaa",
       "reserved": "Varattu",
       "transition": "Vaihtopäivä",
       "maintenance": "Huolto",
       "blocked": "Estetty",
   }
   def availability_label(state: str) -> str:
       return UNIT_AVAILABILITY_LABELS_FI.get((state or "").lower(), state or "-")
   ```
   Rekisteröi Jinja-filteriksi: `availability_label`.

4. Päivitä app/admin/routes.py:n property-detail-näkymä käyttämään
   uutta service-funktiota:
   ```python
   units_with_status = list_units_with_availability_status(
       organization_id=current_user.organization_id,
       property_id=property_id,
   )
   return render_template("admin/properties/detail.html",
                          ..., units_with_status=units_with_status)
   ```

5. Päivitä template
   app/templates/admin/properties/detail.html (huoneet-osio):
   ```jinja
   <table>
     <thead>
       <tr>
         <th>ID</th>
         <th>Nimi</th>
         <th>Tyyppi</th>
         <th>Tila</th>
         <th>Toiminnot</th>
       </tr>
     </thead>
     <tbody>
       {% for unit in units_with_status %}
         <tr>
           <td>{{ unit.id }}</td>
           <td>{{ unit.name }}</td>
           <td>{{ unit.unit_type or "-" }}</td>
           <td>
             <span class="status-badge status-badge--{{ unit.current_state }}">
               {{ unit.current_state|availability_label }}
             </span>
             {% if unit.current_state == "reserved" and unit.current_guest_name %}
               <span class="meta">
                 {{ unit.current_guest_name }}
                 {% if unit.occupied_until %}
                   · vapautuu {{ unit.occupied_until.strftime("%-d.%-m.") }}
                 {% endif %}
               </span>
             {% elif unit.current_state == "free" and unit.next_reservation_at %}
               <span class="meta">
                 seur. varaus {{ unit.next_reservation_at.strftime("%-d.%-m.") }}
               </span>
             {% elif unit.current_state == "transition" %}
               <span class="meta">vaihtopäivä</span>
             {% endif %}
           </td>
           <td>
             <a href="{{ url_for('admin.units_detail', unit_id=unit.id) }}">Näytä</a>
             ·
             <a href="{{ url_for('admin.units_edit', unit_id=unit.id) }}">Muokkaa</a>
             ·
             <a href="{{ url_for('admin.calendar_sync_unit', unit_id=unit.id) }}">Kalenterisynk</a>
           </td>
         </tr>
       {% endfor %}
     </tbody>
   </table>
   ```
   Säilytä olemassa oleva tyyli — älä riko punaista linkkityyliä jos
   se on määritetty admin.css:ssä.

6. CSS app/static/css/admin.css:
   ```css
   .status-badge {
     display: inline-block;
     padding: 0.15rem 0.55rem;
     border-radius: 999px;
     font-size: 0.78rem;
     font-weight: 600;
     letter-spacing: 0.02em;
   }
   .status-badge--free        { background: #ecfdf5; color: #047857; }
   .status-badge--reserved    { background: #dbeafe; color: #1e40af; }
   .status-badge--transition  { background: #fed7aa; color: #9a3412; }
   .status-badge--maintenance { background: #fef3c7; color: #92400e; }
   .status-badge--blocked     { background: #f3f4f6; color: #374151; }
   .status-badge + .meta {
     display: block;
     font-size: 0.78rem;
     color: var(--color-text-muted, #6b7280);
     margin-top: 0.1rem;
   }
   ```
   Värit ovat samat kuin /admin/availability-matriisin solut →
   visuaalinen yhtenäisyys.

7. Käytä SAMAA list_units_with_availability_status -funktiota
   /admin/units-näkymässä (jos olemassa) ja Dashboard-kortin
   "Vapaat huoneet juuri nyt" -datassa (Prompti 3) — älä duplikoi
   logiikkaa (init template §20).

8. Testit (init template §16):
   `tests/test_admin_property_unit_availability.py`:
   a) test_list_units_returns_free_state_when_no_active_reservation
   b) test_list_units_returns_reserved_state_with_guest_name
   c) test_list_units_returns_transition_when_checkin_and_checkout_same_day
   d) test_list_units_returns_maintenance_state_when_active_request
   e) test_list_units_enforces_tenant_isolation — toisen org. data
      ei vuoda.
   f) test_list_units_n_plus_1_query_count — kysele 50 unitia,
      varmista että tehdään max 3 SQL-kyselyä (käytä
      `sqlalchemy.event.listen` + `flask_sqlalchemy.get_debug_queries`).
   g) test_property_detail_view_renders_status_badges — GET
      /admin/properties/<id> sisältää HTML:n
      `class="status-badge status-badge--free"` tai vastaavaa.

9. Manuaalitesti:
   - flask seed-demo-data luo tunnetun joukon varauksia.
   - Avaa /admin/properties/<id>:
     · Vapaa huone näyttää vihreän badgin "Vapaa" + "seur. varaus
       13.5.".
     · Varattu huone näyttää sinisen badgin "Varattu" + vieraan
       nimi + "vapautuu 13.5.".
     · Huoneessa jonka due_date=tänään huoltopyyntöä → keltainen
       "Huolto"-badge.

Hyväksymiskriteerit:
- Tila näkyy yhdellä silmäyksellä ilman, että käyttäjän pitää avata
  kalenteria.
- Yksi SQL-kysely (tai max 3 batchattua) per sivunlataus 50 unitin
  taulukolle (init template §14).
- Tenant-rajaus toimii (init template §12).
- Suomenkieliset labelit i18n-helperilla (init template §13 + Prompti
  10:n kuviolla).
- Pytest vihreä, mukaan lukien N+1-vahti.
- tests/test_ui_finnish.py ei valita uusia jäänteitä.
- Ei muutoksia API-vastausten rakenteeseen (init template §6 säilyy).

Älä:
- Tee uutta DB-saraketta unitsille — laske tila ajonaikaisesti
  reservations-taulusta.
- Käytä N+1-iterointia templatessa (esim. {% for unit in units %}{{
  unit.reservations|selectattr("active") %}}.
- Lisää JavaScriptia tämän sarakkeen renderöintiin — server-rendered
  riittää.
- Riko olemassa olevia property-detail-näkymän muita osioita
  (kuvat, kuvaus, sijainti).
```

---

## Yhteenveto työnkulusta

1. **Prompti E** — bugifix laskumaksuun. Korjaa raakaa JSON-näyttöä,
   lisää audit + flash + redirect, säilyttää API-yhtenäisyyden.
   Init-template: §6, §11, §13, §15, §16, §20.

2. **Prompti F** — Pekan toivoma "tila yhdellä silmäyksellä" -sarake.
   Yksi optimoitu kysely, sama logiikka kuin matriisi-näkymässä,
   suomenkieliset labelit, samat värit.
   Init-template: §12, §13, §14, §16, §20.

**Hyväksymisportti koko paketille:**
- `pytest -v` vihreä jokaisen promptin jälkeen.
- `pytest tests/integration/ -v` vihreä projektin lopussa.
- Manuaalitesti molemmille:
  · /admin/invoices → maksu → flash + redirect (ei JSON).
  · /admin/properties/<id> → "Tila"-sarake näkyy värillisillä
    badgeilla ja päivämäärillä.
- README:n "Acceptance criteria (init template §22)" -lista käydään
  läpi ja varmistetaan että uudet testit kuuluvat siihen.
