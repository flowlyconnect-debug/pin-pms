"""Safe Flask-Migrate runner for production startup.

This script logs migration state before upgrade and fails fast when the
migration graph is not in a safe state for unattended deploy.
"""

from __future__ import annotations

import re
import subprocess
import sys


HEAD_RE = re.compile(r"^([0-9a-z]+)\s+\(head\)")


def _run_flask_db_command(*args: str) -> str:
    cmd = [sys.executable, "-m", "flask", "db", *args]
    print(f"[safe-migrate] running: {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    if result.stderr:
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n", flush=True)
    if result.returncode != 0:
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result.stdout


def _parse_heads(heads_output: str) -> list[str]:
    heads: list[str] = []
    for raw_line in heads_output.splitlines():
        line = raw_line.strip()
        match = HEAD_RE.match(line)
        if match:
            heads.append(match.group(1))
    return heads


def main() -> int:
    try:
        print("[safe-migrate] inspecting current revision", flush=True)
        _run_flask_db_command("current")

        print("[safe-migrate] inspecting migration heads", flush=True)
        heads_output = _run_flask_db_command("heads")
        heads = _parse_heads(heads_output)

        if len(heads) != 1:
            print(
                "[safe-migrate] ERROR: migration graph is ambiguous "
                f"(expected 1 head, got {len(heads)}: {heads}).",
                flush=True,
            )
            print("[safe-migrate] Aborting before upgrade.", flush=True)
            return 1

        print(f"[safe-migrate] single head confirmed: {heads[0]}", flush=True)
        print("[safe-migrate] applying migrations", flush=True)
        _run_flask_db_command("upgrade")
        print("[safe-migrate] migration upgrade completed", flush=True)
        return 0
    except Exception as exc:  # pragma: no cover - runtime safety guard
        print(f"[safe-migrate] migration preflight failed: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
