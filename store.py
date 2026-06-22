"""Airtable persistence via pyairtable + a Personal Access Token.

Rows are records in an Airtable table the user owns. pyairtable is synchronous,
so every network call is wrapped in asyncio.to_thread to keep the bot's event
loop responsive. Records are addressed by their Airtable record id (recXXX),
which is returned on create — cleaner than tracking spreadsheet row numbers.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from pyairtable import Api

from models import FIELD_MAP, Opportunity

logger = logging.getLogger(__name__)


def open_table(cfg):
    """Open the configured Airtable table (sync).

    A (connect, read) timeout ensures a stalled write fails fast instead of
    hanging a handler forever on a flaky network.
    """
    api = Api(cfg.airtable_token, timeout=(10, 30))
    return api.table(cfg.airtable_base_id, cfg.airtable_table_name)


def check_access(table) -> None:
    """Fail fast at startup with a clear message if the table isn't reachable (sync)."""
    try:
        table.all(max_records=1)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            f"Could not read the Airtable table '{table.name}'. Check AIRTABLE_TOKEN "
            f"(needs data.records:read + data.records:write on this base), AIRTABLE_BASE_ID, "
            f"and that the table exists with the documented fields. Original error: {e}"
        ) from e


def to_fields(opp: Opportunity, source_type: str, override_url: str | None = None) -> dict:
    """Build an Airtable fields dict (keyed by column display name). Pure.

    Stamps added_at now. Empty deadline/url are omitted so the cells stay blank.
    """
    fields: dict[str, str] = {
        FIELD_MAP["title"]: opp.title,
        FIELD_MAP["description"]: opp.description,
        FIELD_MAP["category"]: opp.category,
        FIELD_MAP["status"]: opp.status,
        FIELD_MAP["added_at"]: datetime.now(timezone.utc).isoformat(),
        FIELD_MAP["source_type"]: source_type,
    }
    url = override_url or opp.url
    if opp.deadline:
        fields[FIELD_MAP["deadline"]] = opp.deadline
    if url:
        fields[FIELD_MAP["url"]] = url
    return fields


def _create_sync(table, fields_list: list[dict]) -> str | None:
    records = table.batch_create(fields_list, typecast=True)
    return records[-1]["id"] if records else None


async def append_opportunities(
    table, opps: list[Opportunity], source_type: str, override_url: str | None = None
) -> str | None:
    """Create one record per opportunity; return the last record id."""
    fields_list = [to_fields(o, source_type, override_url) for o in opps]
    if not fields_list:
        return None
    return await asyncio.to_thread(_create_sync, table, fields_list)


async def append_url_only(table, url: str, title: str) -> str | None:
    """Create a placeholder record capturing just the URL (soft-fail fallback)."""
    opp = Opportunity(title=title, url=url)
    return await append_opportunities(table, [opp], "url", override_url=url)


async def update_field(table, record_id: str, field: str, value: str) -> None:
    """Update a single editable field on a record. Empty value clears the cell.

    `field` is the internal key (e.g. "deadline"); it's mapped to the column name.
    """
    await asyncio.to_thread(
        table.update, record_id, {FIELD_MAP[field]: (value or None)}, typecast=True
    )


async def overwrite_record(
    table, record_id: str, opp: Opportunity, override_url: str | None = None
) -> None:
    """Overwrite the editable fields of a record (leaves added_at/source_type)."""
    fields = {
        FIELD_MAP["title"]: opp.title,
        FIELD_MAP["deadline"]: opp.deadline or None,
        FIELD_MAP["url"]: override_url or opp.url or None,
        FIELD_MAP["description"]: opp.description,
        FIELD_MAP["category"]: opp.category,
        FIELD_MAP["status"]: opp.status,
    }
    await asyncio.to_thread(table.update, record_id, fields, typecast=True)
