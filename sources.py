"""Input preprocessing: domain routing, URL scraping, X CLI, screenshot bytes.

Everything here normalizes an input into either text (for the text block) or an
image block, which extract.py then feeds to the same LLM call.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

WALLED_DOMAINS = {"linkedin.com", "instagram.com", "facebook.com"}
X_DOMAINS = {"x.com", "twitter.com"}

FETCH_TIMEOUT = 10  # seconds, generic HTTP
X_CLI_TIMEOUT = 15  # seconds, twitter CLI subprocess
MAX_CONTENT_CHARS = 15_000
THIN_CONTENT_CHARS = 200

# Substrings suggesting a login/challenge/cookie wall rather than real content.
_WALL_MARKERS = (
    "sign in",
    "log in",
    "login",
    "enable javascript",
    "verify you are human",
    "verify you're human",
    "are you a robot",
    "captcha",
    "cookies",
    "access denied",
    "please wait",
)


def registered_domain(url: str) -> str:
    """Best-effort registered domain (last two labels), lowercased, no www."""
    host = (urlparse(url).netloc or "").lower()
    host = host.split("@")[-1].split(":")[0]  # strip creds/port
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def host_label(url: str) -> str:
    """A readable host for a URL-only row's title (no www, no scheme)."""
    host = (urlparse(url).netloc or "").lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else (host or url)


def classify_url(url: str) -> str:
    """Return 'walled', 'x', or 'generic'. Pure."""
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    reg = registered_domain(url)
    if reg in WALLED_DOMAINS:
        return "walled"
    if reg in X_DOMAINS or host in X_DOMAINS:
        return "x"
    return "generic"


def is_soft_fail(text: str | None) -> bool:
    """True if extracted content is missing, too thin, or looks like a wall. Pure."""
    if not text:
        return True
    if len(text) < THIN_CONTENT_CHARS:
        return True
    low = text.lower()
    hits = sum(1 for m in _WALL_MARKERS if m in low)
    # A couple of wall markers in otherwise-short content == almost certainly a wall.
    return hits >= 2 and len(text) < 600


# --- Generic fetch ---------------------------------------------------------


def _fetch_generic_sync(url: str, user_agent: str) -> str | None:
    try:
        r = requests.get(url, headers={"User-Agent": user_agent}, timeout=FETCH_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as e:
        logger.info("Generic fetch failed for %s: %s", url, e)
        return None

    html = r.text
    text = trafilatura.extract(html) or ""
    if len(text) < THIN_CONTENT_CHARS:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
    text = (text or "").strip()
    return text[:MAX_CONTENT_CHARS] if text else None


async def fetch_generic(url: str, user_agent: str) -> str | None:
    """Async wrapper — runs the blocking fetch off the event loop."""
    return await asyncio.to_thread(_fetch_generic_sync, url, user_agent)


# --- X / Twitter via the `twitter` CLI ------------------------------------


def parse_x_cli_output(raw: bytes) -> str | None:
    """Turn `twitter tweet <url> --json` output into thread text. Pure.

    Takes the root tweet plus any same-author replies (a self-thread), in order.
    Returns None if the payload has no usable text.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, list) or not data:
        return None

    root = data[0]
    if not isinstance(root, dict) or not root.get("text"):
        return None

    def handle(tweet: dict) -> str:
        author = tweet.get("author") or {}
        return (author.get("screenName") or "").lower()

    root_handle = handle(root)
    when = root.get("createdAtISO") or root.get("createdAt") or ""
    parts = [t.get("text", "") for t in data if isinstance(t, dict) and handle(t) == root_handle]
    body = "\n\n".join(p for p in parts if p).strip()
    if not body:
        return None
    header = f"Tweet by @{root_handle} ({when}):" if root_handle else "Tweet:"
    return f"{header}\n{body}"


async def fetch_x(url: str, cfg) -> str | None:
    """Shell out to the `twitter` CLI to pull tweet/thread text. None on any failure."""
    env = dict(os.environ)
    if cfg.twitter_auth_token:
        env["TWITTER_AUTH_TOKEN"] = cfg.twitter_auth_token
    if cfg.twitter_ct0:
        env["TWITTER_CT0"] = cfg.twitter_ct0

    try:
        proc = await asyncio.create_subprocess_exec(
            cfg.twitter_cli_bin,
            "tweet",
            url,
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except (FileNotFoundError, OSError) as e:
        logger.info("twitter CLI not runnable (%s): %s", cfg.twitter_cli_bin, e)
        return None

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=X_CLI_TIMEOUT)
    except asyncio.TimeoutError:
        logger.info("twitter CLI timed out for %s", url)
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return None

    if proc.returncode != 0 or not out:
        logger.info("twitter CLI failed (rc=%s) for %s: %s", proc.returncode, url, (err or b"")[:200])
        return None

    return parse_x_cli_output(out)


# --- Telegram photo -> Claude image block ---------------------------------


async def download_photo_as_image_block(message, bot) -> dict:
    """Download the largest PhotoSize in-memory and return a base64 image block."""
    photo = message.photo[-1]  # last size == largest
    tg_file = await bot.get_file(photo.file_id)
    buf = bytearray()
    await tg_file.download_to_memory(buf)
    b64 = base64.standard_b64encode(bytes(buf)).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
    }
