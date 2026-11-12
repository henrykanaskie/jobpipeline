"""Hacker News monthly "Ask HN: Who is hiring?" thread, via the free Algolia API.

board = {"token": "whoishiring"}
Each top-level comment is one company. The first line is usually
"Company | Role | Location | ..." but the format is informal, so parsing is best-effort.
"""
import re

from .. import http
from ..normalize import html_to_text
from ._common import posting

NAME = "hackernews"
SEARCH = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=20"
ITEM = "https://hn.algolia.com/api/v1/items/{}"
_ROLE = re.compile(r"engineer|developer|scientist|swe\b|programmer|analyst|designer|researcher|devops|sre\b", re.I)
_LOC = re.compile(r"remote|onsite|on-site|hybrid|\b[A-Z]{2}\b|new york|nyc|san francisco|sf\b|london|seattle|boston", re.I)


def fetch(sess, board: dict) -> dict:
    hits = http.get_json(sess, SEARCH).get("hits", [])
    story = next((h for h in hits if h.get("title", "").lower().startswith("ask hn: who is hiring")), None)
    if story is None:
        return {"children": []}
    return http.get_json(sess, ITEM.format(story["objectID"]))


def split_header(text: str) -> tuple[str, str, str | None] | None:
    """First line 'Acme | Backend Engineer | Remote (US)' -> (company, role, location)."""
    first = text.split("\n", 1)[0]
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company, rest = parts[0], parts[1:]
    role = next((p for p in rest if _ROLE.search(p)), rest[0])
    loc = next((p for p in rest if p is not role and _LOC.search(p)), None)
    return company[:120], role[:200], loc[:200] if loc else None


def parse(payload: dict, board: dict) -> list[dict]:
    out = []
    for c in payload.get("children", []):
        if not c.get("text"):
            continue                          # deleted / flagged
        text = html_to_text(c["text"])
        header = split_header(text)
        if header is None:
            continue
        company, role, loc = header
        out.append(posting(NAME, company, role, loc,
                           f"https://news.ycombinator.com/item?id={c['id']}", text))
    return out
