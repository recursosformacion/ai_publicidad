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
