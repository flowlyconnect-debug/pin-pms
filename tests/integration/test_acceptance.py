from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pyotp
import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 240


def _run_cmd(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        args,
        cwd=REPO_ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        capture_output=True,
    )
    if check and proc.returncode != 0:
        raise AssertionError(
            f"Command failed: {' '.join(args)}\n"
            f"exit={proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return proc


def _compose_exec(
    service: str,
    *cmd: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    args = ["docker", "compose", "exec", "-T"]
    if env:
        for key, value in env.items():
            args.extend(["-e", f"{key}={value}"])
    args.extend([service, *cmd])
    return _run_cmd(args, check=check)


def _compose_port(service: str, container_port: int) -> int:
    proc = _run_cmd(
        ["docker", "compose", "port", service, str(container_port)],
        check=True,
    )
    value = proc.stdout.strip().splitlines()[-1]
    host_port = int(value.rsplit(":", 1)[-1])
    return host_port


def _service_container_id(service: str) -> str:
    proc = _run_cmd(["docker", "compose", "ps", "-q", service], check=True)
    cid = proc.stdout.strip()
    if not cid:
        raise AssertionError(f"No container id found for service {service}")
    return cid


def _docker_health_status(container_id: str) -> str:
    proc = _run_cmd(
        [
            "docker",
            "inspect",
            "-f",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
            container_id,
        ],
        check=True,
    )
    return proc.stdout.strip()


def _wait_for_web_http(base_url: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout
    last_error: str | None = None
    while time.time() < deadline:
        try:
            res = requests.get(f"{base_url}/api/v1/health", timeout=3)
            if res.status_code == 200:
                return
            last_error = f"HTTP {res.status_code}: {res.text[:200]}"
        except requests.RequestException as err:
            last_error = str(err)
        time.sleep(2)
    raise AssertionError(f"Web never became reachable at {base_url}: {last_error}")


def _wait_for_db_ready(db_service: str, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        proc = _compose_exec(
            db_service,
            "pg_isready",
            "-U",
            os.environ.get("POSTGRES_USER", "postgres"),
            "-d",
            os.environ.get("POSTGRES_DB", "pindora"),
            check=False,
        )
        if proc.returncode == 0:
            return
        time.sleep(2)
    raise AssertionError("DB never became ready")


def _wait_for_health(
    service: str,
    *,
    base_url: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    db_service: str | None = None,
) -> None:
    cid = _service_container_id(service)
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _docker_health_status(cid)
        if status == "healthy":
            return
        if status == "none":
            if base_url:
                _wait_for_web_http(base_url, timeout=int(max(5, deadline - time.time())))
                return
            if db_service:
                _wait_for_db_ready(db_service, timeout=int(max(5, deadline - time.time())))
                return
        if status == "unhealthy":
            raise AssertionError(f"Service {service} is unhealthy")
        time.sleep(2)
    raise AssertionError(f"Timed out waiting for service health: {service}")


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found in form")
    return match.group(1)


def _query_json(web_service: str, expr: str) -> dict:
    proc = _compose_exec(
        web_service,
        "python",
        "-c",
        expr,
    )
    return json.loads(proc.stdout.strip())


@pytest.fixture(scope="session")
def compose_stack() -> dict[str, str]:
    web_service = os.getenv("ACCEPTANCE_WEB_SERVICE", "web")
    db_service = os.getenv("ACCEPTANCE_DB_SERVICE", "db")
    superadmin_email = os.getenv(
        "ACCEPTANCE_SUPERADMIN_EMAIL",
        "acceptance-superadmin@example.com",
    )
    superadmin_password = os.getenv(
        "ACCEPTANCE_SUPERADMIN_PASSWORD",
        "ChangeMeAcceptance123!",
    )
    org_name = os.getenv("ACCEPTANCE_ORG_NAME", "Acceptance Test Org")

    compose_env = {
        "MAIL_DEV_LOG_ONLY": "1",
        "ACCEPTANCE_SUPERADMIN_EMAIL": superadmin_email,
        "ACCEPTANCE_SUPERADMIN_PASSWORD": superadmin_password,
        "ACCEPTANCE_ORG_NAME": org_name,
    }

    _run_cmd(["docker", "compose", "up", "-d", "--build"], env=compose_env)
    base_url = os.getenv("ACCEPTANCE_BASE_URL")
    if not base_url:
        host_port = _compose_port(web_service, 5000)
        base_url = f"http://localhost:{host_port}"

    try:
        _wait_for_health(db_service, db_service=db_service)
        _wait_for_health(web_service, base_url=base_url)

        _compose_exec(web_service, "flask", "db", "upgrade")
        _compose_exec(
            web_service,
            "flask",
            "create-superadmin",
            "--email",
            superadmin_email,
            "--password",
            superadmin_password,
            "--organization-name",
            org_name,
        )
        yield {
            "web_service": web_service,
            "db_service": db_service,
            "base_url": base_url,
            "superadmin_email": superadmin_email,
            "superadmin_password": superadmin_password,
            "org_name": org_name,
        }
    finally:
        _run_cmd(["docker", "compose", "down", "-v"], check=False)


@pytest.mark.integration
def test_acceptance_init_template_criteria(compose_stack: dict[str, str]) -> None:
    web_service = compose_stack["web_service"]
    base_url = compose_stack["base_url"]
    email = compose_stack["superadmin_email"]
    password = compose_stack["superadmin_password"]

    health = requests.get(f"{base_url}/api/v1/health", timeout=5)
    assert health.status_code == 200
    payload = health.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "ok"

    superadmin_info = _query_json(
        web_service,
        (
            "import json; "
            "from app import create_app; "
            "from app.users.models import User; "
            f"app=create_app(); "
            "ctx=app.app_context(); ctx.push(); "
            f"u=User.query.filter_by(email={email!r}).first(); "
            "print(json.dumps({'exists': bool(u), 'role': (u.role.value if hasattr(u.role, 'value') else u.role) if u else None, 'is_active': bool(u.is_active) if u else False, 'totp_secret': u.totp_secret if u else None})); "
            "ctx.pop()"
        ),
    )
    assert superadmin_info["exists"] is True
    assert superadmin_info["role"] == "superadmin"
    assert superadmin_info["is_active"] is True

    session = requests.Session()
    login_page = session.get(f"{base_url}/login", timeout=5)
    assert login_page.status_code == 200
    csrf_login = _extract_csrf(login_page.text)
    login_res = session.post(
        f"{base_url}/login",
        data={
            "csrf_token": csrf_login,
            "email": email,
            "password": password,
        },
        allow_redirects=False,
        timeout=5,
    )
    assert login_res.status_code in (302, 303)
    assert "/2fa/" in (login_res.headers.get("Location") or "")

    admin_redirect = session.get(f"{base_url}/admin/properties", allow_redirects=False, timeout=5)
    assert admin_redirect.status_code in (302, 303)
    assert "/2fa/" in (admin_redirect.headers.get("Location") or "")

    create_key = _compose_exec(
        web_service,
        "flask",
        "create-api-key",
        "--name",
        "Acceptance Key",
        "--user-email",
        email,
        "--scopes",
        "reports:read,properties:read,admin:*",
    )
    key_match = re.search(r"^\s*Key:\s*(pms_[A-Za-z0-9_\-]+)\s*$", create_key.stdout, re.MULTILINE)
    assert key_match, f"API key not found in CLI output:\n{create_key.stdout}"
    raw_api_key = key_match.group(1)

    me_bearer = requests.get(
        f"{base_url}/api/v1/me",
        headers={"Authorization": f"Bearer {raw_api_key}"},
        timeout=5,
    )
    assert me_bearer.status_code == 200
    assert me_bearer.json()["success"] is True

    me_x_api = requests.get(
        f"{base_url}/api/v1/me",
        headers={"X-API-Key": raw_api_key},
        timeout=5,
    )
    assert me_x_api.status_code == 200

    api_key_db = _query_json(
        web_service,
        (
            "import json; "
            "from app import create_app; "
            "from app.api.models import ApiKey; "
            "from app.extensions import db; "
            "app=create_app(); "
            "ctx=app.app_context(); ctx.push(); "
            "rows = db.session.execute(\"\"\"SELECT column_name FROM information_schema.columns WHERE table_name='api_keys'\"\"\").fetchall(); "
            "cols=[r[0] for r in rows]; "
            "row=ApiKey.query.order_by(ApiKey.id.desc()).first(); "
            "print(json.dumps({'columns': cols, 'key_hash': row.key_hash if row else '', 'key_prefix': row.key_prefix if row else ''})); "
            "ctx.pop()"
        ),
    )
    assert "key_hash" in api_key_db["columns"]
    assert "plaintext" not in api_key_db["columns"]
    assert "key" not in api_key_db["columns"]
    assert "raw_key" not in api_key_db["columns"]
    assert api_key_db["key_hash"]
    assert api_key_db["key_hash"] != raw_api_key

    email_cmd = _compose_exec(
        web_service,
        "flask",
        "send-test-email",
        "--to",
        "a@example.com",
        "--template",
        "admin_notification",
        env={"MAIL_DEV_LOG_ONLY": "1"},
    )
    assert email_cmd.returncode == 0
    assert "Traceback" not in (email_cmd.stdout + email_cmd.stderr)

    totp_secret = superadmin_info["totp_secret"]
    assert totp_secret
    verify_page = session.get(f"{base_url}/2fa/verify", timeout=5)
    csrf_verify = _extract_csrf(verify_page.text)
    verify_res = session.post(
        f"{base_url}/2fa/verify",
        data={
            "csrf_token": csrf_verify,
            "code": pyotp.TOTP(totp_secret).now(),
        },
        allow_redirects=False,
        timeout=5,
    )
    assert verify_res.status_code in (302, 303)

    edit_page = session.get(f"{base_url}/admin/email-templates/admin_notification", timeout=5)
    assert edit_page.status_code == 200
    csrf_edit = _extract_csrf(edit_page.text)
    updated_subject = "Acceptance Subject"
    edit_res = session.post(
        f"{base_url}/admin/email-templates/admin_notification",
        data={
            "csrf_token": csrf_edit,
            "subject": updated_subject,
            "body_text": "Acceptance plain text body",
            "body_html": "<p>Acceptance html body</p>",
            "action": "save",
        },
        allow_redirects=False,
        timeout=5,
    )
    assert edit_res.status_code in (302, 303)

    template_db = _query_json(
        web_service,
        (
            "import json; "
            "from app import create_app; "
            "from app.email.models import EmailTemplate; "
            "app=create_app(); "
            "ctx=app.app_context(); ctx.push(); "
            "row=EmailTemplate.query.filter_by(key='admin_notification').first(); "
            "print(json.dumps({'subject': row.subject if row else ''})); "
            "ctx.pop()"
        ),
    )
    assert template_db["subject"] == updated_subject

    backup_create = _compose_exec(web_service, "flask", "backup-create")
    assert backup_create.returncode == 0
    assert "Traceback" not in backup_create.stdout
    file_match = re.search(r"SQL dump:\s+(.+\.sql\.gz)", backup_create.stdout)
    assert file_match, f"Backup filename missing from output:\n{backup_create.stdout}"
    backup_filename = Path(file_match.group(1).strip()).name

    backup_restore = _compose_exec(
        web_service,
        "flask",
        "backup-restore",
        "--filename",
        backup_filename,
        "--no-confirm",
    )
    assert backup_restore.returncode == 0
    assert "Traceback" not in (backup_restore.stdout + backup_restore.stderr)

    audit = _query_json(
        web_service,
        (
            "import json; "
            "from app import create_app; "
            "from app.audit.models import AuditLog; "
            f"app=create_app(); "
            "ctx=app.app_context(); ctx.push(); "
            f"row=AuditLog.query.filter(AuditLog.actor_email=={email!r}, AuditLog.action.in_(['login','auth.login.success','user.login','login.success'])).order_by(AuditLog.id.desc()).first(); "
            "print(json.dumps({'found': bool(row), 'action': row.action if row else None})); "
            "ctx.pop()"
        ),
    )
    assert audit["found"] is True


@pytest.mark.integration
def test_readme_has_required_acceptance_sections() -> None:
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8").lower()
    required = [
        "acceptance criteria",
        "backup usage",
        "environment",
        "api",
        "security",
        "2fa",
        "audit",
        "docker",
    ]
    missing = [item for item in required if item not in readme]
    assert not missing, f"README is missing required sections: {missing}"
