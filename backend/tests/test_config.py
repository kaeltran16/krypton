from app.config import Settings, load_yaml_config


def test_default_settings(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/krypton")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")

    settings = Settings()
    assert settings.openrouter_api_key == "test-or-key"
    assert len(settings.pairs) > 0
    assert len(settings.timeframes) > 0


def test_load_yaml_config(tmp_path):
    yaml_content = """
pairs:
  - BTC-USDT-SWAP
timeframes:
  - 15m
collector:
  mode: scheduled
  polling_interval_seconds: 600
  rest_poll_interval_seconds: 120
engine:
  signal_threshold: 60
  llm_threshold: 40
  llm_timeout_seconds: 20
  traditional_weight: 0.70
  llm_weight: 0.30
api:
  ws_heartbeat_seconds: 15
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    config = load_yaml_config(yaml_file)
    assert config["pairs"] == ["BTC-USDT-SWAP"]
    assert config["collector"]["mode"] == "scheduled"
    assert config["engine"]["traditional_weight"] == 0.70


def test_load_yaml_config_empty_file(tmp_path):
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("")

    config = load_yaml_config(yaml_file)
    assert config == {}


def test_settings_with_yaml_override(tmp_path, monkeypatch):
    yaml_content = """
pairs:
  - ETH-USDT-SWAP
collector:
  mode: scheduled
  polling_interval_seconds: 600
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-or-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost:5432/krypton")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KRYPTON_CONFIG_PATH", str(yaml_file))

    settings = Settings()
    assert settings.pairs == ["ETH-USDT-SWAP"]
    assert settings.collector_mode == "scheduled"
    assert settings.collector_polling_interval_seconds == 600
