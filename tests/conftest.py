"""Shared test fixtures — isolate config from any real .env."""

import pytest

import config as config_module

_STUB_ENV = {
    "TELEGRAM_BOT_TOKEN": "test-telegram-token",
    "ANTHROPIC_API_KEY": "test-anthropic-key",
    "ANTHROPIC_MODEL": "claude-sonnet-4-6",
    "AIRTABLE_TOKEN": "pat-test-token",
    "AIRTABLE_BASE_ID": "appTEST123",
    "AIRTABLE_TABLE_NAME": "Opportunities",
    "ALLOWED_USER_IDS": "111,222",
    "TWITTER_AUTH_TOKEN": "tok",
    "TWITTER_CT0": "ct0",
}


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """Stub required env vars and reset the cached Config before each test."""
    for k, v in _STUB_ENV.items():
        monkeypatch.setenv(k, v)
    # Don't let a real .env on disk override our stubs.
    monkeypatch.setattr(config_module, "load_dotenv", lambda *a, **k: None)
    config_module.reset_config()
    yield
    config_module.reset_config()
