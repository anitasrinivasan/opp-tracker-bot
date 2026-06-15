from dataclasses import dataclass

from bot import (
    added_reply,
    extract_urls,
    is_continuation_caption,
    parse_edit_command,
    strip_urls,
)
from models import Opportunity


@dataclass
class Ent:
    type: str
    offset: int = 0
    length: int = 0
    url: str = ""


def test_extract_urls_regex_fallback():
    assert extract_urls("see https://example.org/grant for info") == ["https://example.org/grant"]


def test_extract_urls_strips_trailing_punct_and_dedupes():
    text = "(https://a.org/x). also https://a.org/x"
    assert extract_urls(text) == ["https://a.org/x"]


def test_extract_urls_from_entities():
    text = "click here"
    ents = [Ent(type="text_link", url="https://hidden.org/job")]
    assert extract_urls(text, ents) == ["https://hidden.org/job"]


def test_extract_urls_url_entity_offset():
    text = "go https://e.org/p now"
    ents = [Ent(type="url", offset=3, length=len("https://e.org/p"))]
    assert extract_urls(text, ents) == ["https://e.org/p"]


def test_extract_urls_none():
    assert extract_urls("just plain text, no links") == []


def test_strip_urls():
    assert strip_urls("deadline next week https://a.org/x", ["https://a.org/x"]) == "deadline next week"
    assert strip_urls("https://a.org/x", ["https://a.org/x"]) == ""  # nothing but the url


def test_is_continuation_caption():
    assert is_continuation_caption("+") is True
    assert is_continuation_caption(" same ") is True
    assert is_continuation_caption("SAME") is True
    assert is_continuation_caption("deadline July 1") is False
    assert is_continuation_caption(None) is False


def test_parse_edit_command_valid():
    assert parse_edit_command("deadline 2026-07-01") == ("deadline", "2026-07-01")
    assert parse_edit_command("status applied") == ("status", "applied")
    assert parse_edit_command("STATUS Applied") == ("status", "applied")
    assert parse_edit_command("category grant") == ("category", "grant")
    assert parse_edit_command("title Senior Counsel at X") == ("title", "Senior Counsel at X")


def test_parse_edit_command_clear_deadline():
    assert parse_edit_command("deadline none") == ("deadline", "")
    assert parse_edit_command("deadline clear") == ("deadline", "")


def test_parse_edit_command_invalid():
    assert parse_edit_command("deadline reminder for me") is None  # not a date
    assert parse_edit_command("status pending") is None  # not an enum value
    assert parse_edit_command("category misc") is None
    assert parse_edit_command("notafield value") is None
    assert parse_edit_command("edit") is None  # single token
    assert parse_edit_command("") is None


def test_added_reply():
    opps = [Opportunity(title="Grant A", deadline="2026-08-01"), Opportunity(title="Job B")]
    out = added_reply(opps)
    assert "✅ Added: Grant A — deadline 2026-08-01" in out
    assert "✅ Added: Job B — deadline —" in out
    assert 'Reply "edit"' in out
