"""Google Sheets persistence via gspread + a service account.

The Sheet is one the user owns and has shared (Editor) with the service
account's email. gspread is synchronous, so every network call is wrapped in
asyncio.to_thread to keep the bot's event loop responsive.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import gspread

from models import COL_INDEX, COLUMNS, Opportunity

logger = logging.getLogger(__name__)

_RANGE_ROW = re.compile(r"![A-Z]+(\d+)(?::[A-Z]+(\d+))?")


def open_worksheet(cfg):
    """Authenticate as the service account and open the target worksheet (sync)."""
    gc = gspread.service_account(filename=cfg.service_account_file)
    return gc.open_by_key(cfg.sheet_id).worksheet(cfg.worksheet_name)


def ensure_header_row(ws) -> None:
    """Write the header row if the sheet is empty or its header doesn't match (sync)."""
    try:
        first = ws.row_values(1)
    except gspread.exceptions.APIError:
        first = []
    if first[: len(COLUMNS)] != COLUMNS:
        ws.update(range_name="A1", values=[COLUMNS])
        logger.info("Wrote header row to worksheet %r", ws.title)


def to_row(opp: Opportunity, source_type: str, override_url: str | None = None) -> list[str]:
    """Build a sheet row in COLUMNS order. Pure. added_at stamped now."""
    return [
        opp.title,
        opp.deadline or "",
        override_url or opp.url or "",
        opp.description,
        opp.category,
        opp.status,
        datetime.now(timezone.utc).isoformat(),
        source_type,
    ]


def last_row_from_response(resp: dict) -> int | None:
    """Parse the last written row index out of an append response's updatedRange.

    e.g. {"updates": {"updatedRange": "Opportunities!A7:H9"}} -> 9. Pure.
    """
    try:
        rng = resp["updates"]["updatedRange"]
    except (KeyError, TypeError):
        return None
    m = _RANGE_ROW.search(rng)
    if not m:
        return None
    start, end = m.group(1), m.group(2)
    return int(end or start)


def _append_sync(ws, rows: list[list[str]]) -> int | None:
    resp = ws.append_rows(rows, value_input_option="USER_ENTERED")
    return last_row_from_response(resp)


async def append_opportunities(
    ws, opps: list[Opportunity], source_type: str, override_url: str | None = None
) -> int | None:
    """Append one or more opportunities; return the last written row index."""
    rows = [to_row(o, source_type, override_url) for o in opps]
    if not rows:
        return None
    return await asyncio.to_thread(_append_sync, ws, rows)


async def append_url_only(ws, url: str, title: str) -> int | None:
    """Append a placeholder row capturing just the URL (soft-fail fallback)."""
    opp = Opportunity(title=title, url=url)
    return await append_opportunities(ws, [opp], "url", override_url=url)


async def update_field(ws, row: int, field: str, value: str) -> None:
    """Update a single editable cell (1-based row)."""
    col = COL_INDEX[field]
    await asyncio.to_thread(ws.update_cell, row, col, value)


async def overwrite_row(ws, row: int, opp: Opportunity, override_url: str | None = None) -> None:
    """Overwrite the editable columns A:F of `row` (leaves added_at/source_type)."""
    values = [[
        opp.title,
        opp.deadline or "",
        override_url or opp.url or "",
        opp.description,
        opp.category,
        opp.status,
    ]]
    await asyncio.to_thread(
        ws.update, range_name=f"A{row}:F{row}", values=values, value_input_option="USER_ENTERED"
    )
