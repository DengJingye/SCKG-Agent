from core import settings
from pydantic import SecretStr


def test_dataless_dotenv_placeholder_is_skipped_without_read(monkeypatch):
    calls = []

    class Placeholder:
        def stat(self):
            return type("Metadata", (), {"st_size": 1213, "st_blocks": 0})()

    monkeypatch.setattr(settings, "load_dotenv", lambda path: calls.append(path))
    assert settings._load_materialized_dotenv(Placeholder()) is False
    assert calls == []


def test_materialized_dotenv_is_loaded(monkeypatch):
    calls = []

    class Materialized:
        def stat(self):
            return type("Metadata", (), {"st_size": 1213, "st_blocks": 8})()

    monkeypatch.setattr(
        settings,
        "load_dotenv",
        lambda path: calls.append(path) or True,
    )
    source = Materialized()
    assert settings._load_materialized_dotenv(source) is True
    assert calls == [source]


def test_require_llm_accepts_documented_chat_api_base():
    configured = settings.Settings(
        openai_api_base=None,
        chat_api_base="https://api.deepseek.example",
        openai_api_key=SecretStr("test-key"),
        model_name="deepseek-test",
        external_network_allowed=True,
    )

    base, key, model = configured.require_llm()

    assert base == "https://api.deepseek.example"
    assert key == "test-key"
    assert model == "deepseek-test"
