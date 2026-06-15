import pytest

import config as config_module
from config import _parse_ids, load_config


def test_load_config_ok():
    cfg = load_config()
    assert cfg.model == "claude-sonnet-4-6"
    assert cfg.airtable_base_id == "appTEST123"
    assert cfg.airtable_table_name == "Opportunities"
    assert cfg.allowed_user_ids == {111, 222}


def test_missing_required_var_exits(monkeypatch):
    monkeypatch.delenv("AIRTABLE_BASE_ID", raising=False)
    with pytest.raises(SystemExit):
        load_config()


def test_default_model_when_unset(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert load_config().model == "claude-sonnet-4-6"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("111,222", {111, 222}),
        ("111; 222 ;333", {111, 222, 333}),
        ("", set()),
        ("111, notanint, 333", {111, 333}),
    ],
)
def test_parse_ids(raw, expected):
    assert _parse_ids(raw) == expected
