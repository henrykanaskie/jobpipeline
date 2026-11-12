"""Discord notifications via channel webhooks (one-way pushes; no bot process needed).

DISCORD_WEBHOOK_URL        new postings feed (can be muted on your phone)
DISCORD_ALERT_WEBHOOK_URL  matches, CAPTCHAs, breakage (keep phone notifications ON);
                           falls back to DISCORD_WEBHOOK_URL if unset
"""
import logging
import os

import requests

log = logging.getLogger(__name__)
MAX_ITEMS_PER_MESSAGE = 10   # Discord allows 10 embeds per message
MAX_NEW_JOB_POSTS = 30       # above this (e.g. first crawl), send a summary instead


def _post(payload: dict, channel: str = "feed") -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL")
    if channel == "alert":
        url = os.environ.get("DISCORD_ALERT_WEBHOOK_URL") or url
    if not url:
        log.info("no Discord webhook set; would have sent: %s", payload.get("content") or payload)
        return
    try:
        requests.post(url, json=payload, timeout=10).raise_for_status()
    except requests.RequestException as e:   # notifications must never crash a service
        log.warning("Discord post failed: %s", e)


def alert(message: str) -> None:
    _post({"content": f":warning: {message}"}, "alert")


def match(row: dict) -> None:
    _post({"content": f":dart: Match {round(float(row['fit_score']))}%", "embeds": [{
        "title": f"{row['company_display']} · {row['title']}"[:256],
        "url": row["url"],
        "description": (row.get("fit_reasons") or "")[:1000],
    }]}, "alert")


def captcha(posting: dict, note: str | None) -> None:
    live = os.environ.get("LIVE_BROWSER_URL", "(set LIVE_BROWSER_URL)")
    _post({"content": (f":lock: CAPTCHA on {posting['company_display']} · {posting['title']}\n"
                       f"Solve it here: {live}\n{note or ''}\n"
                       "Times out to needs_manual in 30 min.")}, "alert")


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


def heartbeat(env_var: str) -> None:
    """Ping an external dead-man's switch (e.g. healthchecks.io) so you hear about it
    when the host itself is down, which no in-process alert can report."""
    url = os.environ.get(env_var)
    if url:
        try:
            requests.get(url, timeout=10)
        except requests.RequestException as e:
            log.warning("heartbeat failed: %s", e)
