"""Discord notifications via a channel webhook (no bot process needed for one-way pushes)."""
import logging
import os

import requests

log = logging.getLogger(__name__)
MAX_ITEMS_PER_MESSAGE = 10   # Discord allows 10 embeds per message
MAX_NEW_JOB_POSTS = 30       # above this (e.g. first crawl), send a summary instead


def _post(payload: dict) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not url:
        log.info("DISCORD_WEBHOOK_URL unset; would have sent: %s", payload.get("content"))
        return
    try:
        requests.post(url, json=payload, timeout=10).raise_for_status()
    except requests.RequestException as e:   # notifications must never crash the crawler
        log.warning("Discord post failed: %s", e)


def alert(message: str) -> None:
    _post({"content": f":warning: {message}"})


def new_jobs(rows: list[dict]) -> None:
    if not rows:
        return
    if len(rows) > MAX_NEW_JOB_POSTS:
        _post({"content": f"{len(rows)} new postings this run (too many to list)."})
        return
    for i in range(0, len(rows), MAX_ITEMS_PER_MESSAGE):
        chunk = rows[i:i + MAX_ITEMS_PER_MESSAGE]
        _post({"embeds": [{
            "title": f"{r['company_display']} · {r['title']}"[:256],
            "url": r["url"],
            "description": (r.get("location") or "")[:200],
        } for r in chunk]})
