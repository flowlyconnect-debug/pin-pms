import types

from app import config as app_config


def _set_fake_dotenv(monkeypatch, values):
    fake_dotenv = types.SimpleNamespace(dotenv_values=lambda _path: values)
    monkeypatch.setitem(app_config.sys.modules, "dotenv", fake_dotenv)


def test_env_file_does_not_override_runtime_database_url_in_docker(monkeypatch):
    monkeypatch.setitem(
        app_config.os.environ,
        "DATABASE_URL",
        "postgresql+psycopg2://u:p@db:5432/pindora",
    )
    monkeypatch.setattr(app_config, "_running_in_docker", lambda: True)
    monkeypatch.setattr(app_config.Path, "is_file", lambda _self: True)
    monkeypatch.delitem(app_config.sys.modules, "pytest", raising=False)
    _set_fake_dotenv(
        monkeypatch,
        {"DATABASE_URL": "postgresql+psycopg2://u:p@127.0.0.1:5433/pindora"},
    )

    merged = app_config._env_for_database()

    assert merged["DATABASE_URL"] == "postgresql+psycopg2://u:p@db:5432/pindora"


def test_env_file_can_override_database_url_outside_docker(monkeypatch):
    monkeypatch.setitem(
        app_config.os.environ,
        "DATABASE_URL",
        "postgresql+psycopg2://u:p@db:5432/pindora",
    )
    monkeypatch.setattr(app_config, "_running_in_docker", lambda: False)
    monkeypatch.setattr(app_config.Path, "is_file", lambda _self: True)
    monkeypatch.delitem(app_config.sys.modules, "pytest", raising=False)
    _set_fake_dotenv(
        monkeypatch,
        {"DATABASE_URL": "postgresql+psycopg2://u:p@127.0.0.1:5433/pindora"},
    )

    merged = app_config._env_for_database()

    assert merged["DATABASE_URL"] == "postgresql+psycopg2://u:p@127.0.0.1:5433/pindora"


def test_docker_keeps_runtime_database_url_when_env_file_has_only_postgres_keys(monkeypatch):
    monkeypatch.setitem(
        app_config.os.environ,
        "DATABASE_URL",
        "postgresql+psycopg2://u:p@db:5432/pindora",
    )
    monkeypatch.setattr(app_config, "_running_in_docker", lambda: True)
    monkeypatch.setattr(app_config.Path, "is_file", lambda _self: True)
    monkeypatch.delitem(app_config.sys.modules, "pytest", raising=False)
    _set_fake_dotenv(
        monkeypatch,
        {"POSTGRES_HOST": "127.0.0.1", "POSTGRES_PORT": "5433"},
    )

    merged = app_config._env_for_database()

    assert merged["DATABASE_URL"] == "postgresql+psycopg2://u:p@db:5432/pindora"


def test_compose_db_hostname_not_rewritten_inside_docker(monkeypatch):
    monkeypatch.setattr(app_config, "_running_in_docker", lambda: True)

    resolved = app_config._loopback_if_compose_hostname_unresolvable("db", port=5432)

    assert resolved == "db"


def test_explicit_database_url_keeps_db_hostname_even_if_dns_lookup_fails(monkeypatch):
    monkeypatch.setitem(
        app_config.os.environ,
        "DATABASE_URL",
        "postgresql+psycopg2://u:p@db:5432/pindora",
    )
    monkeypatch.setitem(app_config.os.environ, "POSTGRES_PORT", "5433")
    monkeypatch.setattr(app_config.Path, "is_file", lambda _self: False)
    monkeypatch.delitem(app_config.sys.modules, "pytest", raising=False)

    resolved = app_config._resolved_database_url()

    assert resolved == "postgresql+psycopg2://u:p@db:5432/pindora"
