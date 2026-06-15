"""Environment configuration, loaded once from .env.

Mirrors the dotenv + dataclass + singleton pattern used elsewhere in these
projects. Required vars missing -> print to stderr and sys.exit(1).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from dotenv import load_dotenv

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Required for the bot to start at all.
_REQUIRED = ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY", "AIRTABLE_TOKEN", "AIRTABLE_BASE_ID"]


@dataclass
class Config:
    telegram_token: str
    anthropic_api_key: str
    model: str
    airtable_token: str
    airtable_base_id: str
    airtable_table_name: str
    allowed_user_ids: set[int] = field(default_factory=set)
    twitter_auth_token: str = ""
    twitter_ct0: str = ""
    twitter_cli_bin: str = "twitter"
    user_agent: str = DEFAULT_USER_AGENT


_config: Config | None = None


def _parse_ids(raw: str) -> set[int]:
    ids: set[int] = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            try:
                ids.add(int(part))
            except ValueError:
                print(f"Ignoring non-integer ALLOWED_USER_IDS entry: {part!r}", file=sys.stderr)
    return ids


def load_config() -> Config:
    """Read .env and build a Config, exiting if required vars are missing."""
    load_dotenv()

    missing = [v for v in _REQUIRED if not os.environ.get(v)]
    if missing:
        print(
            "Missing required environment variables: " + ", ".join(missing) + "\n"
            "Copy .env.example to .env and fill them in.",
            file=sys.stderr,
        )
        sys.exit(1)

    allowed = _parse_ids(os.environ.get("ALLOWED_USER_IDS", ""))
    if not allowed:
        print(
            "WARNING: ALLOWED_USER_IDS is empty — the bot will ignore every message. "
            "Add your Telegram user ID (from @userinfobot).",
            file=sys.stderr,
        )

    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
        airtable_token=os.environ["AIRTABLE_TOKEN"],
        airtable_base_id=os.environ["AIRTABLE_BASE_ID"],
        airtable_table_name=os.environ.get("AIRTABLE_TABLE_NAME", "Opportunities"),
        allowed_user_ids=allowed,
        twitter_auth_token=os.environ.get("TWITTER_AUTH_TOKEN", ""),
        twitter_ct0=os.environ.get("TWITTER_CT0", ""),
        twitter_cli_bin=os.environ.get("TWITTER_CLI_BIN", "twitter"),
        user_agent=os.environ.get("USER_AGENT", DEFAULT_USER_AGENT),
    )


def get_config() -> Config:
    """Return the process-wide Config, building it on first call."""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    """Drop the cached Config (used by tests)."""
    global _config
    _config = None
