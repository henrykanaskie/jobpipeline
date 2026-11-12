"""carpet-crawler (crawler.carsonsecrest.me): an existing crawler covering ~4,300 ATS boards
(Workday, iCIMS, Greenhouse, Oracle, SmartRecruiters, Ashby, Workable, Lever) plus Simplify,
newgrad-jobs.com and Hacker News. We read its public data.json snapshot.

board = {"token": "carpet",
         "url": "https://crawler.carsonsecrest.me/data.json",   # optional
         "tracks": ["software", "data"],     # optional; feed tracks: software, data, data-science, product
         "new_grad_only": false,             # optional; uses the feed's own new_grad flag
         "max_age_days": 60,                 # optional; drop postings older than this (by posted_at)
         "max_stale_hours": 3}               # optional; error (=> alert) if the feed stops updating
The feed has no descriptions; Screening fetches them for postings that pass the pre-filter.
"""
from datetime import datetime, timedelta, timezone

from ._common import posting

NAME = "carpet"
DEFAULT_URL = "https://crawler.carsonsecrest.me/data.json"


class StaleFeed(Exception):
    pass


def url(board: dict) -> str:
    return board.get("url", DEFAULT_URL)


def _ts(s: str | None) -> datetime | None:
    """ISO timestamp -> aware datetime. The feed mixes '...Z' and timezone-less values;
    timezone-less ones are taken as UTC. Unparseable -> None (the posting is kept)."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse(payload: dict, board: dict, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    generated = _ts(payload.get("generatedAt"))
    max_stale = timedelta(hours=board.get("max_stale_hours", 3))
    if generated is None or now - generated > max_stale:
        # Raising turns into a crawler error, which triggers the "board broke" alert.
        raise StaleFeed(f"feed last generated {payload.get('generatedAt')}; older than {max_stale}")

    tracks = set(board.get("tracks") or [])
    oldest = now - timedelta(days=board["max_age_days"]) if board.get("max_age_days") else None
    out = []
    for j in payload.get("jobs", []):
        if tracks and j.get("track") not in tracks:
            continue
        if board.get("new_grad_only") and not j.get("new_grad"):
            continue
        if oldest and (posted := _ts(j.get("posted_at"))) and posted < oldest:
            continue
        if not (j.get("absolute_url") and j.get("title") and j.get("company")):
            continue
        # source keeps the upstream ATS, e.g. "carpet/workday"
        out.append(posting(f"{NAME}/{j.get('source', 'unknown')}", j["company"], j["title"],
                           j.get("location"), j["absolute_url"], None))
    return out
