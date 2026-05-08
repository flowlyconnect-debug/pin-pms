from __future__ import annotations


class _FakeS3Client:
    def __init__(self) -> None:
        self.put_calls: list[dict[str, object]] = []
        self.delete_calls: list[dict[str, object]] = []

    def put_object(self, **kwargs) -> None:
        self.put_calls.append(kwargs)

    def delete_object(self, **kwargs) -> None:
        self.delete_calls.append(kwargs)


def test_s3_storage_upload_delete_and_public_url(app, monkeypatch):
    from app.storage import s3 as s3_module
    from app.storage.s3 import S3Storage

    fake_client = _FakeS3Client()
    captured_client_kwargs: dict[str, object] = {}

    def fake_boto3_client(service_name, **kwargs):
        captured_client_kwargs["service_name"] = service_name
        captured_client_kwargs.update(kwargs)
        return fake_client

    monkeypatch.setattr(s3_module.boto3, "client", fake_boto3_client)

    app.config.update(
        S3_ENDPOINT_URL="https://s3.example.test",
        S3_BUCKET="pindora-assets",
        S3_REGION="eu-north-1",
        S3_PUBLIC_BASE_URL="https://cdn.example.test/assets/",
        S3_ACCESS_KEY_ID="key-id",
        S3_SECRET_ACCESS_KEY="secret",
    )

    with app.app_context():
        storage = S3Storage()
        uploaded_key = storage.upload(
            file_bytes=b"avatar", key="/avatars/1.png", content_type="image/png"
        )
        storage.delete(key="/avatars/1.png")
        url = storage.get_url(key="/avatars/1.png")

    assert captured_client_kwargs["service_name"] == "s3"
    assert captured_client_kwargs["endpoint_url"] == "https://s3.example.test"
    assert captured_client_kwargs["aws_access_key_id"] == "key-id"
    assert captured_client_kwargs["aws_secret_access_key"] == "secret"
    assert captured_client_kwargs["region_name"] == "eu-north-1"
    assert uploaded_key == "/avatars/1.png"
    assert fake_client.put_calls == [
        {
            "Bucket": "pindora-assets",
            "Key": "/avatars/1.png",
            "Body": b"avatar",
            "ContentType": "image/png",
        }
    ]
    assert fake_client.delete_calls == [{"Bucket": "pindora-assets", "Key": "/avatars/1.png"}]
    assert url == "https://cdn.example.test/assets/avatars/1.png"


def test_s3_storage_builds_endpoint_and_aws_urls(app, monkeypatch):
    from app.storage import s3 as s3_module
    from app.storage.s3 import S3Storage

    monkeypatch.setattr(s3_module.boto3, "client", lambda *args, **kwargs: _FakeS3Client())

    with app.app_context():
        app.config.update(
            S3_ENDPOINT_URL="https://s3.example.test/",
            S3_BUCKET="pindora-assets",
            S3_REGION="eu-north-1",
            S3_PUBLIC_BASE_URL="",
            S3_ACCESS_KEY_ID="",
            S3_SECRET_ACCESS_KEY="",
        )
        endpoint_storage = S3Storage()
        endpoint_url = endpoint_storage.get_url(key="/documents/invoice.pdf")

        app.config["S3_ENDPOINT_URL"] = ""
        aws_storage = S3Storage()
        aws_url = aws_storage.get_url(key="/documents/invoice.pdf")

    assert endpoint_url == "https://s3.example.test/pindora-assets/documents/invoice.pdf"
    assert aws_url == "https://pindora-assets.s3.eu-north-1.amazonaws.com/documents/invoice.pdf"
