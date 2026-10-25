from pathlib import Path

from sqlalchemy.engine import make_url

from infrastructure.config import DATABASE_NAME, database_url_from_osap_toml


def test_osap_toml_connection_targets_separate_publicidad_database(tmp_path: Path) -> None:
    config_file = tmp_path / "osap.toml"
    config_file.write_text(
        '[db]\n'
        'host = "127.0.0.1"\n'
        'name = "osap-api"\n'
        'user = "osap_user"\n'
        'password = "p@ss:/word"\n'
        'port = 3307\n',
        encoding="utf-8",
    )

    url_text = database_url_from_osap_toml(config_file)
    assert url_text is not None
    url = make_url(url_text)

    assert url.drivername == "mysql+pymysql"
    assert url.host == "127.0.0.1"
    assert url.port == 3307
    assert url.username == "osap_user"
    assert url.password == "p@ss:/word"
    assert url.database == DATABASE_NAME == "OSAP_PUBLICIDAD"
    assert url.query["charset"] == "utf8mb4"


def test_osap_toml_missing_connection_is_not_used(tmp_path: Path) -> None:
    config_file = tmp_path / "osap.toml"
    config_file.write_text('[db]\nhost = "127.0.0.1"\n', encoding="utf-8")

    assert database_url_from_osap_toml(config_file) is None


def test_missing_osap_toml_returns_none(tmp_path: Path) -> None:
    assert database_url_from_osap_toml(tmp_path / "does-not-exist.toml") is None


def test_settings_reads_osap_config_env_and_overrides_database_name(
    tmp_path: Path, monkeypatch
) -> None:
    from infrastructure.config import Settings

    config_file = tmp_path / "osap.toml"
    config_file.write_text(
        '[db]\n'
        'host = "db.example.test"\n'
        'name = "osap-api"\n'
        'user = "ad_service"\n'
        'password = "not-a-real-secret"\n'
        'port = 3306\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("AI_PUBLICIDAD_DATABASE_URL", raising=False)
    monkeypatch.setenv("OSAP_CONFIG", str(config_file))
    monkeypatch.setenv("AI_PUBLICIDAD_ENV", "development")

    settings = Settings(_env_file=None)
    url = make_url(settings.database_url)

    assert settings.osap_config_path == str(config_file)
    assert url.database == "OSAP_PUBLICIDAD"
    assert url.host == "db.example.test"
    assert url.username == "ad_service"


def test_settings_does_not_read_sibling_osap_api_toml(
    tmp_path: Path, monkeypatch
) -> None:
    from infrastructure.config import Settings

    app_dir = tmp_path / "ai_publicidad"
    osap_api_dir = tmp_path / "osap-api"
    app_dir.mkdir()
    osap_api_dir.mkdir()
    (osap_api_dir / "osap.toml").write_text(
        '[db]\n'
        'host = "127.0.0.1"\n'
        'name = "osap-api"\n'
        'user = "osap_user"\n'
        'password = "not-a-real-secret"\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(app_dir)
    for variable in (
        "AI_PUBLICIDAD_DATABASE_URL",
        "AI_PUBLICIDAD_OSAP_CONFIG",
        "OSAP_CONFIG",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("AI_PUBLICIDAD_ENV", "development")

    settings = Settings(_env_file=None)
    assert make_url(settings.database_url).drivername == "sqlite"
