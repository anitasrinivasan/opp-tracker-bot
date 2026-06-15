from models import Opportunity
from store import to_fields


def test_to_fields_full():
    o = Opportunity(title="Grant A", deadline="2026-08-01", url="https://a.org", description="desc",
                    category="grant", status="interested")
    f = to_fields(o, "url", override_url="https://override.org")
    assert f["title"] == "Grant A"
    assert f["deadline"] == "2026-08-01"
    assert f["url"] == "https://override.org"  # override wins
    assert f["category"] == "grant"
    assert f["source_type"] == "url"
    assert "T" in f["added_at"]  # added_at ISO timestamp


def test_to_fields_omits_empty_deadline_and_url():
    f = to_fields(Opportunity(title="t"), "text")
    assert "deadline" not in f  # blank -> omitted so the cell stays empty
    assert "url" not in f
    assert f["source_type"] == "text"
    assert f["status"] == "interested"


def test_to_fields_url_fallback_to_opp_url():
    f = to_fields(Opportunity(title="t", url="https://opp.org"), "text")
    assert f["url"] == "https://opp.org"
