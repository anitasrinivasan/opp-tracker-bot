"""LLM extraction: one prompt for text, scraped-URL content, and screenshots.

Text/scraped content goes in as a text block; screenshots go in as N image
blocks. Same system prompt, same JSON-array output schema. The current date is
injected into the *user* turn so the system prefix stays stable and relative
dates resolve correctly.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from anthropic import AsyncAnthropic
from pydantic import ValidationError

from models import Opportunity

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You extract structured "opportunity" listings (jobs, grants, calls for \
proposals/papers, fellowships, residencies, awards) from text, web pages, or screenshots.

Return opportunities matching the provided schema. Rules:
- title: required. Concise — the role/program/CFP name plus the organization if clear.
- deadline: ISO format YYYY-MM-DD. NEVER guess or invent a deadline. If none is stated, use null.
  Resolve relative dates ("next Friday", "in two weeks", "by end of month") against the \
CURRENT_DATE given in the user message. If a listing says "rolling", "open until filled", or \
otherwise has no fixed date, set deadline to null AND note that detail in the description.
- url: the listing's URL if one appears in the input, else null.
- description: 1-2 sentences capturing what it is and any deadline nuance.
- category: one of job | grant | cfp | fellowship | other.
- status: always "interested" (the default).
- A single input may contain SEVERAL distinct opportunities — return one array element for each.
- If the input is NOT an opportunity (chit-chat, an error/login page, unrelated content), \
return an empty array. Do not fabricate a row.

When MULTIPLE IMAGES are provided, they may be parts of ONE listing (a single posting \
screenshotted across several images) OR several separate listings. Read them together as one \
continuous document first; only split into multiple opportunities if they are clearly distinct \
postings."""

# Wrapper object schema — structured outputs work most reliably with an object
# root, so the array lives under "opportunities". deadline is a nullable string;
# the YYYY-MM-DD constraint is enforced by the Opportunity validator, not the
# schema (JSON Schema can't enforce date format here).
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "opportunities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "deadline": {"type": ["string", "null"]},
                    "url": {"type": ["string", "null"]},
                    "description": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["job", "grant", "cfp", "fellowship", "other"],
                    },
                    "status": {
                        "type": "string",
                        "enum": ["interested", "applied", "passed"],
                    },
                },
                "required": ["title", "deadline", "url", "description", "category", "status"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["opportunities"],
    "additionalProperties": False,
}

MAX_TOKENS = 4096

_FENCE_OPEN = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"\s*```\s*$")


def build_user_blocks(
    today_iso: str,
    *,
    text: Optional[str] = None,
    image_blocks: Optional[list[dict]] = None,
) -> list[dict]:
    """Build the user-turn `content` list. Pure — no API calls.

    `image_blocks` -> screenshot path (text, if given, is treated as a caption
    note). Otherwise -> text path.
    """
    if image_blocks:
        n = len(image_blocks)
        hint = (
            f"CURRENT_DATE: {today_iso}\n"
            f"The following {n} image(s) may be parts of a single listing, or separate "
            "listings. Read them together before deciding."
        )
        if text and text.strip():
            hint += f"\nUser note: {text.strip()}"
        return [{"type": "text", "text": hint}, *image_blocks]

    return [
        {
            "type": "text",
            "text": f"CURRENT_DATE: {today_iso}\n\n--- INPUT ---\n{text or ''}",
        }
    ]


def _strip_fences(raw: str) -> str:
    raw = _FENCE_OPEN.sub("", raw.strip())
    raw = _FENCE_CLOSE.sub("", raw)
    return raw.strip()


def parse_opportunities(raw_json: str) -> list[Opportunity]:
    """Parse the model's JSON into validated Opportunity objects.

    Accepts either the wrapper object {"opportunities": [...]} or a bare array.
    Invalid items are skipped (logged), not fatal — one bad row never sinks the
    rest. Pure and unit-testable.
    """
    raw_json = _strip_fences(raw_json)
    if not raw_json:
        return []
    try:
        data = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.warning("Could not parse extraction JSON: %s | %r", e, raw_json[:300])
        return []

    if isinstance(data, dict):
        items = data.get("opportunities", [])
    elif isinstance(data, list):
        items = data
    else:
        items = []

    out: list[Opportunity] = []
    for item in items:
        try:
            out.append(Opportunity.model_validate(item))
        except (ValidationError, ValueError) as e:
            logger.warning("Skipping invalid opportunity: %s | %r", e, item)
    return out


def _first_text(content) -> str:
    for block in content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


async def extract(
    client: AsyncAnthropic,
    model: str,
    today_iso: str,
    *,
    text: Optional[str] = None,
    image_blocks: Optional[list[dict]] = None,
) -> list[Opportunity]:
    """Run one extraction call and return validated opportunities (possibly empty)."""
    content = build_user_blocks(today_iso, text=text, image_blocks=image_blocks)
    messages = [{"role": "user", "content": content}]

    try:
        resp = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_config={"format": {"type": "json_schema", "schema": EXTRACTION_SCHEMA}},
        )
    except Exception as e:  # noqa: BLE001 — structured outputs can fail; retry plain
        logger.warning("Structured-output call failed (%s); retrying without schema", e)
        resp = await client.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT + "\n\nRespond with ONLY a JSON object of the form "
            '{"opportunities": [...]}. No prose, no markdown fences.',
            messages=messages,
        )

    return parse_opportunities(_first_text(resp.content))
