# BUG 500 Notifications — 2026-05-08

## Reproduction

- Komennot (paikallinen):
  - `docker compose up --build -d`
  - `docker compose exec web flask db upgrade`
  - `docker compose exec web flask seed-demo-data`
- Vaihtoehtoinen reproduktio testikäyttäjällä (käytetty tässä korjauksessa):
  - `pytest tests/test_notifications.py::test_notifications_index_renders_with_seed_rows -v`
- Reitti:
  - `GET /admin/notifications`
- Rooli:
  - admin (sama virhe myös superadmin + 2FA-rooleilla — ongelma on templaten
    renderöinnissä, ei oikeustarkistuksessa)
- Päivämäärä:
  - 2026-05-08

Selain näytti aiemmin:

> 500 Internal Server Error — Something went wrong on our side. The error has
> been recorded.

## Original stack trace

Reprodukoitu testiclientillä `tests/test_repro_notifications_500.py` (poistettu
korjauksen jälkeen). Lokin sisältö korjausta edeltäen:

```
{"exc_info": ["<class 'TypeError'>", "TypeError(\"'builtin_function_or_method' object is not iterable\")", ...],
 "level": "error", "logger": "app.errors",
 "route": "/admin/notifications",
 "message": "Unhandled exception during request"}

Traceback (most recent call last):
  File ".../flask/app.py", line 917, in full_dispatch_request
    rv = self.dispatch_request()
  File ".../flask/app.py", line 902, in dispatch_request
    return self.ensure_sync(self.view_functions[rule.endpoint])(**view_args)
  File ".../flask_login/utils.py", line 290, in decorated_view
    return current_app.ensure_sync(func)(*args, **kwargs)
  File "app/admin/routes.py", line 114, in wrapped
    return view_func(*args, **kwargs)
  File "app/admin/routes.py", line 421, in notifications_list
    return render_template(
        "admin/notifications.html",
        rows=rows,
        grouped_rows=notification_routes.group_by_day(rows),
    )
  File ".../flask/templating.py", line 151, in render_template
    return _render(app, template, context)
  File ".../flask/templating.py", line 132, in _render
    rv = template.render(context)
  File ".../jinja2/environment.py", line 1295, in render
    self.environment.handle_exception()
  File ".../jinja2/environment.py", line 942, in handle_exception
    raise rewrite_traceback_stack(source=source)
  File "app/templates/admin/notifications.html", line 1, in top-level template code
    {% extends "admin/base.html" %}
  File "app/templates/admin/base.html", line 254, in top-level template code
    {% block content %}{% endblock %}
  File "app/templates/admin/notifications.html", line 28, in block 'content'
    {% for row in day_group.items %}
TypeError: 'builtin_function_or_method' object is not iterable
```

## Initial suspected causes

Tarkistuslista promptin mukaan ja niiden lopullinen tila:

- [ ] Template viittaa puuttuvaan kenttään (esim. `row.read_at`, `row.severity`)
  — _ei pitänyt paikkaansa: kentät ovat olemassa mallissa._
- [ ] Service iteroi None-arvoa (`metadata`, `items`) — _ei pitänyt
  paikkaansa: service ei käytä `metadata`-saraketta._
- [ ] `Notification.organization_id` puuttuu seedistä — _ei: `organization_id`
  on `nullable=False` ja seed asettaa sen oikein._
- [ ] Migraatio current/head mismatch — _ei: kaikki sarakkeet ovat templaten
  käyttämiä, eikä mikään lokimerkintä viitannut puuttuvaan sarakkeeseen._
- [ ] `status_label`-filter puuttuu Jinja-rekisteröinnistä — _ei: filter on
  rekisteröity (`app/__init__.py:315`), eikä template käytä sitä._

Todellinen juurisyy paljastui stack tracesta — se oli erillinen Jinja-ansa.

## Root cause

`app/notifications/routes.py::group_by_day()` palauttaa lista-dictejä muodossa

```python
[{"day": "2026-05-08", "items": [<payload>, ...]}, ...]
```

Template `app/templates/admin/notifications.html` (rivi 28) iteroi:

```jinja
{% for row in day_group.items %}
```

Jinja2 tulkitsee `obj.attr` ensisijaisesti `getattr(obj, attr)` -kutsulla ja
vasta toissijaisesti `obj["attr"]` -hakemistosyntaksilla. Pythonin `dict`
sisältää sisäänrakennetun metodin `dict.items` (sidottu metodi), joten Jinjan
attribuuttihaku onnistuu **eikä koskaan putoa** `__getitem__("items")`-hakuun.
Tästä seuraa, että template iteroi sidottua `dict.items`-metodia listan
sijaan ja Python heittää `TypeError: 'builtin_function_or_method' object is
not iterable`. Sama ansa _ei_ koske `day_group.day`-riviä, koska `dict`-
luokassa ei ole `day`-attribuuttia, joten Jinja siirtyy automaattisesti
`__getitem__`-hakuun.

Tämä on yleinen Jinja-virhe aina kun dict-avain osuu yksiin Pythonin
`dict`-tyypin metodien (`items`, `keys`, `values`, `pop`, `get`, `update`,
`copy`, `clear`, `setdefault`) kanssa.

## Fix

Minimaalinen muutos — ainoastaan template korjattu käyttämään eksplisiittistä
hakemistosyntaksia, joka pakottaa Jinjan dict-key-lookupiin:

- `app/templates/admin/notifications.html`
  - `{% for row in day_group.items %}` → `{% for row in day_group["items"] %}`
  - `<h2>{{ day_group.day }}</h2>` → `<h2>{{ day_group["day"] or "-" }}</h2>`
    (defensiivinen fallback `unknown`-ryhmälle)
  - `{{ row.title }}` → `{{ row.title or "-" }}` (defensiivinen fallback;
    `title` on `nullable=False` mallissa, mutta payload menee templaten läpi
    sellaisenaan, joten varmistetaan ettei mahdollinen tyhjä merkkijono näytä
    rikkinäiseltä napilta).

Muut suojaukset templatessa olivat jo paikallaan korjauksen ulkopuolella:
`row.body or "-"`, `row.created_at[:16].replace("T", " ") if row.created_at else "-"`,
ja `row.severity if row.severity in [...] else 'info'`.

Mitä **ei** muutettu (rajoitukset täytetty):

- `app/notifications/models.py` — ei uusia kenttiä eikä muutoksia.
- `app/notifications/services.py` — ei muutoksia (juurisyy oli puhtaasti
  templatessa).
- `app/notifications/routes.py` (helperit `to_payload` / `group_by_day`) —
  ei muutoksia. Olisi ollut vaihtoehtoinen korjaus uudelleennimetä
  `"items"`-avain → `"entries"`, mutta se olisi koskenut myös JSON-
  serialisaatiota epäsuorasti ja ollut suurempi muutos kuin templaten
  yhden rivin täsmäkorjaus.
- Migraatiot — ei muutoksia.
- Scheduler / taustatyö-logiikka — ei muutoksia.
- `app/__init__.py` — ei muutoksia (`status_label`-filter oli jo
  rekisteröity).

## Regression tests

Lisätty tiedostoon `tests/test_notifications.py`:

- `test_notifications_index_renders_when_table_empty` — varmistaa että
  tyhjällä taululla GET /admin/notifications palauttaa 200 ja näyttää
  empty staten "Ei ilmoituksia".
- `test_notifications_index_renders_with_seed_rows` — luo yhden rivin ja
  varmistaa että sivu palauttaa 200 ja näyttää otsikon + body-tekstin.
  Reprodukoi alkuperäisen 500:n ennen korjausta.
- `test_notifications_index_handles_null_optional_fields` — luo rivin
  jossa `body=None`, `link=None`, `read_at=None`, `user_id=None`. Varmistaa
  että 200 ja ettei "None"-tekstiä leviä HTML-bodyyn.

Lisätty tiedostoon `tests/test_admin_pms.py`:

- `test_admin_list_pages_do_not_500_as_superadmin` — parametrisoitu smoke
  yli reittien `/admin/audit`, `/admin/email-queue`, `/admin/webhooks`,
  `/admin/api-keys`, `/admin/notifications`. Vaatii 2FA-verifioidun
  superadminin. Hyväksyy `{200, 302, 303, 403, 404}`, hylkää 500.
- `test_admin_list_pages_do_not_500_as_admin` — sama parametrisointi
  organisaation adminilla (joka saa 200 vain `_admin_pms_access`-
  reiteillä, 403 superadmin-reiteillä). Hylkää 500.

Kaikki viisi reittiä rekisteröityvät projektissa (varmistettu manuaalisesti
`grep "@admin_bp.get" app/admin/routes.py`).

## Final status

- `/admin/notifications` palauttaa 200 paikallisesti.
- Tyhjä taulu renderöityy (Ei ilmoituksia).
- Seed-rivi renderöityy.
- Optional `None`-kentät eivät kaada sivua eivätkä vuoda "None"-tekstiä.
- Sentry / Sentry-mock ei käytössä paikallisessa pytest-ympäristössä
  (`SENTRY_DSN` tyhjä → `init_sentry` ohitetaan), joten uutta poikkeusta
  ei tallennu — manuaalinen `docker compose logs web --tail=200`
  -tarkistus suositellaan ennen tuotantotagia.

Testien tila:

- `pytest tests/test_notifications.py -v` → 9 passed.
- `pytest tests/test_admin_pms.py -v` → 120 passed (sisältää 10 uutta
  smoke-testiparametrisaatiota).
- `ruff check app/admin/routes.py app/templates/admin/notifications.html
  tests/test_admin_pms.py` → vihreä (uusiin riveihin ei tullut errejä;
  `tests/test_notifications.py` sisältää 2 ennestään olemassa ollutta
  `I001`/`B011`-erroria, joita ei korjattu tässä — ne eivät liity
  bugiin).

## Commit

- Commit SHA (short): `535c825`
- Commit SHA (full): `535c82560752be6986fd238b75dc458273396f1e`
- Branch: `main`
- Commit message: `fix(admin-notifications): render grouped list without
  dict.items shadow`
