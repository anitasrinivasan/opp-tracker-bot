"""Pydantic models and the fixed field order."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, field_validator

# The fields stored per opportunity, in display order. The first six come from
# the LLM (via Opportunity); added_at and source_type are set by application
# code at write time. These are the field names to create in the Airtable table.
COLUMNS = [
    "title",
    "deadline",
    "url",
    "description",
    "category",
    "status",
    "added_at",
    "source_type",
]

Category = Literal["job", "grant", "cfp", "fellowship", "other"]
Status = Literal["interested", "applied", "passed"]

# Fields a user may edit via the `edit` flow (added_at/source_type are app-managed).
EDITABLE_FIELDS = ("title", "deadline", "url", "description", "category", "status")


class Opportunity(BaseModel):
    """One opportunity as returned by the LLM and validated before writing."""

    model_config = ConfigDict(extra="ignore")

    title: str
    deadline: Optional[str] = None  # "YYYY-MM-DD" or None — never guessed
    url: Optional[str] = None
    description: str = ""
    category: Category = "other"
    status: Status = "interested"

    @field_validator("deadline", mode="before")
    @classmethod
    def _normalize_deadline(cls, v):
        """Accept None/""/"null" as no-deadline; otherwise require ISO YYYY-MM-DD.

        A malformed date raises here, which the per-item validation loop in
        extract.py catches and skips — one bad item never sinks the batch.
        """
        if v in (None, "", "null", "None"):
            return None
        if not isinstance(v, str):
            raise ValueError("deadline must be a string or null")
        v = v.strip()
        if not v:
            return None
        datetime.strptime(v, "%Y-%m-%d")  # raises ValueError on bad format
        return v

    @field_validator("title")
    @classmethod
    def _title_nonempty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("title is required")
        return v
