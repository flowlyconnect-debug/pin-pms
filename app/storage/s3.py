from __future__ import annotations

import boto3
from botocore.client import Config
from flask import current_app


class S3Storage:
    def __init__(self) -> None:
        endpoint = (current_app.config.get("S3_ENDPOINT_URL") or "").strip() or None
        self.bucket = (current_app.config.get("S3_BUCKET") or "").strip()
        self.region = (current_app.config.get("S3_REGION") or "").strip() or None
        self.public_base = (current_app.config.get("S3_PUBLIC_BASE_URL") or "").strip()
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=(current_app.config.get("S3_ACCESS_KEY_ID") or "").strip() or None,
            aws_secret_access_key=(current_app.config.get("S3_SECRET_ACCESS_KEY") or "").strip() or None,
            region_name=self.region,
            config=Config(signature_version="s3v4"),
        )

    def upload(self, *, file_bytes: bytes, key: str, content_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=file_bytes, ContentType=content_type)
        return key

    def delete(self, *, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def get_url(self, *, key: str) -> str:
        if self.public_base:
            return f"{self.public_base.rstrip('/')}/{key.lstrip('/')}"
        endpoint = (current_app.config.get("S3_ENDPOINT_URL") or "").strip()
        if endpoint:
            return f"{endpoint.rstrip('/')}/{self.bucket}/{key.lstrip('/')}"
        region_part = f".{self.region}" if self.region else ""
        return f"https://{self.bucket}.s3{region_part}.amazonaws.com/{key.lstrip('/')}"
