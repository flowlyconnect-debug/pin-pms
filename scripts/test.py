#!/usr/bin/env python3
"""Yhden komennon testiajuri (toimii Windows/macOS/Linux).

Käyttö:
    python scripts/test.py            # kaikki: backend + e2e
    python scripts/test.py backend    # vain pytest-yksikkö/reittitestit
    python scripts/test.py e2e        # vain Playwright-selaintestit
    python scripts/test.py journeys   # vain kriittiset käyttäjäpolut (nopea savutesti)

HTML-raportit kirjoitetaan reports/-kansioon:
    reports/backend.html   reports/e2e.html
Epäonnistuneista selaintesteistä tallentuu kuvakaappaus reports/e2e-artifacts/.

Ilman Postgresia backend-testit voi pakottaa SQLiteen:
    FORCE_SQLITE_TEST_DB=1 python scripts/test.py backend
E2E käyttää aina omaa SQLite-kantaansa eikä vaadi Postgresia.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS = REPO_ROOT / "reports"


def _run(name: str, args: list[str]) -> int:
    print(f"\n=== {name} ===\n$ {' '.join(args)}", flush=True)
    return subprocess.call(args, cwd=REPO_ROOT)


def backend() -> int:
    return _run(
        "Backend-testit (pytest)",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            f"--html={REPORTS / 'backend.html'}",
            "--self-contained-html",
        ],
    )


def journeys() -> int:
    return _run(
        "Kriittiset käyttäjäpolut",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_critical_journeys.py",
            "-v",
            f"--html={REPORTS / 'journeys.html'}",
            "--self-contained-html",
        ],
    )


def e2e() -> int:
    return _run(
        "Playwright E2E -testit",
        [
            sys.executable,
            "-m",
            "pytest",
            "e2e",
            "-q",
            "--browser",
            "chromium",
            "--screenshot",
            "only-on-failure",
            "--output",
            str(REPORTS / "e2e-artifacts"),
            f"--html={REPORTS / 'e2e.html'}",
            "--self-contained-html",
        ],
    )


def main() -> int:
    REPORTS.mkdir(exist_ok=True)
    # Some tests write uploads; the production default (/var/lib/pindora) is
    # not writable on dev machines or CI runners. Keep test uploads repo-local.
    os.environ.setdefault("UPLOADS_DIR", str(REPO_ROOT / ".test-uploads"))
    target = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()

    if target == "backend":
        return backend()
    if target == "e2e":
        return e2e()
    if target == "journeys":
        return journeys()
    if target != "all":
        print(__doc__)
        return 2

    results = {"backend": backend(), "e2e": e2e()}
    print("\n=== Yhteenveto ===")
    for name, code in results.items():
        print(f"  {name}: {'OK' if code == 0 else f'FAIL (exit {code})'}")
    print(f"  Raportit: {REPORTS}/backend.html, {REPORTS}/e2e.html")
    return max(results.values())


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUTF8", "1")
    raise SystemExit(main())
