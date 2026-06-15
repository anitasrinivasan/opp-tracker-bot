import json

import pytest
import responses

import sources
from sources import (
    classify_url,
    host_label,
    is_soft_fail,
    parse_x_cli_output,
    registered_domain,
    _fetch_generic_sync,
)


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.linkedin.com/jobs/view/123", "walled"),
        ("https://linkedin.com/in/someone", "walled"),
        ("https://instagram.com/p/abc", "walled"),
        ("https://www.facebook.com/events/1", "walled"),
        ("https://x.com/user/status/123", "x"),
        ("https://twitter.com/user/status/123", "x"),
        ("https://mobile.twitter.com/user/status/123", "x"),
        ("https://grants.example.gov/post/5", "generic"),
        ("https://jobs.lever.co/org/role", "generic"),
    ],
)
def test_classify_url(url, expected):
    assert classify_url(url) == expected


def test_registered_domain_and_host_label():
    assert registered_domain("https://www.linkedin.com/x") == "linkedin.com"
    assert registered_domain("https://jobs.lever.co/a") == "lever.co"
    assert host_label("https://www.example.com/path") == "example.com"


def test_is_soft_fail():
    assert is_soft_fail(None) is True
    assert is_soft_fail("") is True
    assert is_soft_fail("too short") is True
    # Short content full of wall markers -> fail
    assert is_soft_fail("Please sign in. Log in to continue. Accept cookies.") is True
    # Long, real content -> not a fail
    assert is_soft_fail("A real grant posting. " * 30) is False


def test_parse_x_cli_output_thread_same_author():
    payload = json.dumps(
        [
            {"text": "Fellowship open!", "author": {"screenName": "OrgX"}, "createdAtISO": "2026-06-01T00:00:00Z"},
            {"text": "Apply by July 1.", "author": {"screenName": "OrgX"}},  # self-reply
            {"text": "Nice!", "author": {"screenName": "randomFan"}},  # other author
        ]
    ).encode()
    out = parse_x_cli_output(payload)
    assert "Fellowship open!" in out
    assert "Apply by July 1." in out
    assert "Nice!" not in out
    assert "@orgx" in out.lower()


def test_parse_x_cli_output_empty_or_bad():
    assert parse_x_cli_output(b"[]") is None
    assert parse_x_cli_output(b"not json") is None
    assert parse_x_cli_output(json.dumps([{"author": {"screenName": "a"}}]).encode()) is None


@responses.activate
def test_fetch_generic_bs4_fallback_and_truncation():
    body = "<html><body><p>" + ("Grant details and eligibility. " * 50) + "</p></body></html>"
    responses.add(responses.GET, "https://example.org/grant", body=body, status=200)
    text = _fetch_generic_sync("https://example.org/grant", "UA")
    assert text is not None and len(text) > 200
    assert len(text) <= sources.MAX_CONTENT_CHARS


@responses.activate
def test_fetch_generic_http_error_returns_none():
    responses.add(responses.GET, "https://example.org/missing", status=404)
    assert _fetch_generic_sync("https://example.org/missing", "UA") is None
