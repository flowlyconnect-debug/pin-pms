# Pindora PMS — testikomennot. Sama toiminnallisuus ilman makea:
#   python scripts/test.py [all|backend|e2e|journeys]

.PHONY: test test-all test-backend test-e2e test-journeys test-setup

## Aja kaikki testit (backend + Playwright E2E), raportit reports/-kansioon
test: test-all
test-all:
	python scripts/test.py all

## Vain backend-/API-testit (pytest)
test-backend:
	python scripts/test.py backend

## Vain Playwright-selaintestit
test-e2e:
	python scripts/test.py e2e

## Vain kriittiset käyttäjäpolut (nopea savutesti)
test-journeys:
	python scripts/test.py journeys

## Kertaluonteinen asennus: dev-riippuvuudet + Chromium Playwrightille
test-setup:
	pip install -r requirements-dev.txt
	python -m playwright install chromium
