from app.config import Settings, get_settings


def test_settings_default_values():
    settings = Settings(
        _env_file=None,
        clerk_publishable_key="pk_test",
        clerk_secret_key="sk_test",
    )
    assert settings.app_name == "Gallopics API"
    assert settings.app_version == "1.0.0"
    assert settings.debug is False
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.database_url == "postgresql+asyncpg://localhost/gallopics_dev"
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.storage_backend == "local"


def test_settings_from_env_vars(monkeypatch):
    monkeypatch.setenv("APP_NAME", "Test App")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test_db")
    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    settings = Settings(_env_file=None)
    assert settings.app_name == "Test App"
    assert settings.debug is True
    assert settings.database_url == "postgresql+asyncpg://localhost/test_db"
    assert settings.storage_backend == "s3"


def test_get_settings_returns_same_instance():
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()
