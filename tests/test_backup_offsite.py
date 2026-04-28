from __future__ import annotations

import io
from pathlib import Path

import boto3
from moto import mock_aws


class _FakeCreateBackupPopen:
    def __init__(self, *args, **kwargs):
        self.stdout = io.BytesIO(b"select 1;\n")
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def communicate(self, timeout=None):
        _ = timeout
        return b"", b""


def test_create_backup_uploads_sql_and_uploads_archive_offsite(app, monkeypatch, tmp_path):
    from app.audit.models import AuditLog
    from app.backups.models import BackupStatus, BackupTrigger
    from app.backups.services import create_backup

    backup_dir = Path(tmp_path) / "backups"
    uploads_dir = Path(tmp_path) / "uploads"
    backup_dir.mkdir(parents=True)
    uploads_dir.mkdir(parents=True)
    (uploads_dir / "avatar.jpg").write_bytes(b"fake-image")

    with mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="pindora-offsite")

        app.config["BACKUP_DIR"] = str(backup_dir)
        app.config["UPLOADS_DIR"] = str(uploads_dir)
        app.config["BACKUP_S3_ENABLED"] = True
        app.config["BACKUP_S3_BUCKET"] = "pindora-offsite"
        app.config["BACKUP_S3_ACCESS_KEY"] = "test"
        app.config["BACKUP_S3_SECRET_KEY"] = "test"
        app.config["BACKUP_S3_ENDPOINT_URL"] = ""
        app.config["BACKUP_S3_PREFIX"] = "pindora-pms/"

        monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakeCreateBackupPopen)

        backup = create_backup(trigger=BackupTrigger.MANUAL)
        assert backup.status == BackupStatus.SUCCESS
        assert backup.s3_uri == f"s3://pindora-offsite/pindora-pms/{backup.filename}"
        assert backup.uploads_filename is not None

        objects = s3.list_objects_v2(Bucket="pindora-offsite", Prefix="pindora-pms/")
        keys = sorted([item["Key"] for item in objects.get("Contents", [])])
        assert f"pindora-pms/{backup.filename}" in keys
        assert f"pindora-pms/{backup.uploads_filename}" in keys

        offsite_audit = AuditLog.query.filter_by(action="backup.uploaded_offsite").first()
        assert offsite_audit is not None
        assert offsite_audit.status == "success"
