import json

from extract import build_user_blocks, parse_opportunities


def _img(n=1):
    return [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "x"}}] * n


def test_build_text_blocks_injects_date():
    blocks = build_user_blocks("2026-06-15", text="Apply by next Friday")
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"
    assert "CURRENT_DATE: 2026-06-15" in blocks[0]["text"]
    assert "Apply by next Friday" in blocks[0]["text"]


def test_build_image_blocks_hint_and_count():
    imgs = _img(3)
    blocks = build_user_blocks("2026-06-15", image_blocks=imgs)
    assert blocks[0]["type"] == "text"
    assert "3 image(s)" in blocks[0]["text"]
    assert "CURRENT_DATE: 2026-06-15" in blocks[0]["text"]
    assert sum(1 for b in blocks if b["type"] == "image") == 3


def test_build_image_blocks_with_caption_note():
    blocks = build_user_blocks("2026-06-15", text="deadline is Sept 1", image_blocks=_img(1))
    assert "User note: deadline is Sept 1" in blocks[0]["text"]


def test_parse_wrapper_object():
    raw = json.dumps({"opportunities": [{"title": "Grant A", "deadline": "2026-08-01"}]})
    opps = parse_opportunities(raw)
    assert len(opps) == 1 and opps[0].title == "Grant A"


def test_parse_bare_array():
    raw = json.dumps([{"title": "Job B"}, {"title": "Job C"}])
    assert len(parse_opportunities(raw)) == 2


def test_parse_skips_bad_items_keeps_good():
    raw = json.dumps(
        {
            "opportunities": [
                {"title": "Good", "deadline": "2026-08-01"},
                {"title": "Bad date", "deadline": "not-a-date"},
                {"title": "", "deadline": None},  # missing title
                {"title": "Also good"},
            ]
        }
    )
    titles = [o.title for o in parse_opportunities(raw)]
    assert titles == ["Good", "Also good"]


def test_parse_empty_array():
    assert parse_opportunities('{"opportunities": []}') == []


def test_parse_strips_markdown_fences():
    raw = "```json\n{\"opportunities\": [{\"title\": \"Fenced\"}]}\n```"
    assert parse_opportunities(raw)[0].title == "Fenced"


def test_parse_garbage_returns_empty():
    assert parse_opportunities("not json at all") == []
    assert parse_opportunities("") == []
