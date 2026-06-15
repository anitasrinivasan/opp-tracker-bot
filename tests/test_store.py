from models import FIELD_MAP, Opportunity
from store import to_fields


def test_to_fields_full_uses_mapped_names():
    o = Opportunity(title="Grant A", deadline="2026-08-01", url="https://a.org", description="desc",
                    category="grant", status="interested")
    f = to_fields(o, "url", override_url="https://override.org")
    assert f[FIELD_MAP["title"]] == "Grant A"
    assert f[FIELD_MAP["deadline"]] == "2026-08-01"
    assert f[FIELD_MAP["url"]] == "https://override.org"  # override wins
    assert f[FIELD_MAP["category"]] == "grant"
    assert f[FIELD_MAP["source_type"]] == "url"
    assert "T" in f[FIELD_MAP["added_at"]]  # added_at ISO timestamp


def test_to_fields_omits_empty_deadline_and_url():
    f = to_fields(Opportunity(title="t"), "text")
    assert FIELD_MAP["deadline"] not in f  # blank -> omitted so the cell stays empty
    assert FIELD_MAP["url"] not in f
    assert f[FIELD_MAP["source_type"]] == "text"
    assert f[FIELD_MAP["status"]] == "interested"


def test_to_fields_url_fallback_to_opp_url():
    f = to_fields(Opportunity(title="t", url="https://opp.org"), "text")
    assert f[FIELD_MAP["url"]] == "https://opp.org"
