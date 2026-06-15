from models import Opportunity
from store import last_row_from_response, to_row


def test_to_row_order_and_stamps():
    o = Opportunity(title="Grant A", deadline="2026-08-01", url="https://a.org", description="desc",
                    category="grant", status="interested")
    row = to_row(o, "url", override_url="https://override.org")
    assert row[0] == "Grant A"
    assert row[1] == "2026-08-01"
    assert row[2] == "https://override.org"  # override wins
    assert row[4] == "grant"
    assert row[7] == "url"  # source_type
    assert "T" in row[6]  # added_at ISO timestamp


def test_to_row_blank_deadline_and_url_fallback():
    o = Opportunity(title="t")
    row = to_row(o, "text")
    assert row[1] == ""  # no deadline
    assert row[2] == ""  # no url, no override


def test_last_row_single():
    resp = {"updates": {"updatedRange": "Opportunities!A7:H7"}}
    assert last_row_from_response(resp) == 7


def test_last_row_multi():
    resp = {"updates": {"updatedRange": "Opportunities!A7:H9"}}
    assert last_row_from_response(resp) == 9


def test_last_row_quoted_sheet_name():
    resp = {"updates": {"updatedRange": "'My Sheet'!A2:H2"}}
    assert last_row_from_response(resp) == 2


def test_last_row_missing():
    assert last_row_from_response({}) is None
    assert last_row_from_response({"updates": {}}) is None
