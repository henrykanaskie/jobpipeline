"""Hacker News monthly "Ask HN: Who is hiring?" thread, via the free Algolia API.

board = {"token": "whoishiring"}
Each top-level comment is one company. The first line is usually
"Company | Role | Location | ..." but the format is informal, so parsing is heuristic and
conservative: a comment is skipped unless its first line has a plausible company and a part
that looks like a role. Every kept posting stores the comment's full text, so nothing the
heuristics miss is lost. The posting URL is the HN comment (stable and unique per company per
month); the first outbound link is exposed by parse_comment as `apply_url`.
"""
import re
from datetime import datetime, timezone

from .. import http
from ..normalize import html_to_text
from ._common import posting

NAME = "hackernews"
SEARCH = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=20"
ITEM = "https://hn.algolia.com/api/v1/items/{}"
COMMENT_URL = "https://news.ycombinator.com/item?id={}"
# Last month's thread is still the current one until the new one is posted (first weekday
# of the month), so it is accepted for this many days into a month.
GRACE_DAYS = 5

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_TITLE = re.compile(r"^ask hn: who is hiring\?\s*\((\w+)\s+(\d{4})\)", re.I)

_URLISH = re.compile(r"https?://|www\.|^\S+\.(com|io|ai|co|org|net|dev|app)\b\S*$", re.I)
_COMP = re.compile(r"[$€£¥]\s?\d|\b\d+(\.\d+)?\s?k\b|\bsalary\b|\bequity\b|\bstipend\b|\bcompensation\b", re.I)
_EMPLOYMENT = re.compile(r"^(full[- ]?time|part[- ]?time|contract(or)?|freelance|permanent|"
                         r"temporary|internships?|ft|pt|w2|1099)\b", re.I)
_ARRANGEMENT = re.compile(r"^(100%\s*)?(remote|onsite|on-site|on site|hybrid|in[- ]office|wfh)\b", re.I)
_ROLE = re.compile(
    r"engineer|engineering|developer|scientist|\bswe\b|\bsre\b|programmer|analyst|designer|"
    r"researcher|devops|architect|manager|\bpms?\b|product|\blead\b|director|head of|founding|"
    r"intern\b|consultant|specialist|administrator|technician|recruiter|operator|"
    r"officer|representative|\bcto\b|\bvp\b", re.I)
# Too vague alone: "NYC + Toronto (most roles require...)" is a location, not a role.
_ROLE_GENERIC = re.compile(r"\b(positions|roles|openings)\b", re.I)
_PLACE_WORDS = re.compile(
    r"\b(remote|onsite|on-site|on site|hybrid|in[- ]office|anywhere|worldwide|global|"
    r"new york|nyc|san francisco|bay area|silicon valley|los angeles|seattle|boston|"
    r"austin|chicago|denver|atlanta|miami|washington|toronto|vancouver|montreal|london|"
    r"berlin|munich|paris|amsterdam|dublin|stockholm|zurich|lisbon|barcelona|madrid|"
    r"singapore|tokyo|sydney|bangalore|tel aviv|europe|canada|germany)\b", re.I)
# Case-sensitive: "Austin, TX", "Reno NV", "US", "SF". Lowercase "us" in prose must not match.
_PLACE_CODES = re.compile(r"\b[A-Z][a-zA-Z.\-]+,? (?:[A-Z]{2}|USA|UK)\b|\b(?:US|USA|UK|EU|SF|DC|NYC)\b")
_REMOTE = re.compile(r"\bremote(ly)?\b|\bwfh\b|\banywhere\b", re.I)
_NOT_REMOTE = re.compile(r"\bno remote\b|\bnot remote\b|\bremote:? no\b", re.I)
_HREF = re.compile(r'href="([^"]+)"', re.I)
_PAREN = re.compile(r"\s*[(\[][^)\]]*[)\]]\s*")


class ThreadNotFound(Exception):
    pass


def pick_thread(hits: list[dict], now: datetime | None = None) -> dict:
    """The "Who is hiring?" story for the current month, or last month's during the first
    GRACE_DAYS of a month. Raises (=> crawler error alert) if neither is in the results."""
    now = now or datetime.now(timezone.utc)
    prev = (now.year, now.month - 1) if now.month > 1 else (now.year - 1, 12)
    wanted = [(now.year, now.month)] + ([prev] if now.day <= GRACE_DAYS else [])
    by_month = {}
    for h in hits:
        m = _TITLE.match(h.get("title") or "")
        if m and m.group(1).lower() in _MONTHS:
            by_month.setdefault((int(m.group(2)), _MONTHS.index(m.group(1).lower()) + 1), h)
    for ym in wanted:
        if ym in by_month:
            return by_month[ym]
    raise ThreadNotFound(f"no 'Who is hiring?' thread for {now:%B %Y} in the Algolia results")


def fetch(sess, board: dict) -> dict:
    hits = http.get_json(sess, SEARCH).get("hits", [])
    return http.get_json(sess, ITEM.format(pick_thread(hits)["objectID"]))


def _kind(part: str) -> str:
    if _URLISH.search(part):
        return "url"
    if _ARRANGEMENT.match(part):
        return "location"
    if _EMPLOYMENT.match(part):
        return "employment"
    place = bool(_PLACE_WORDS.search(part) or _PLACE_CODES.search(part))
    if _ROLE.search(part) or (_ROLE_GENERIC.search(part) and not place):
        return "role"
    if _COMP.search(part):
        return "comp"
    if place:
        return "location"
    return "other"


def split_header(text: str) -> tuple[str, str, str | None] | None:
    """First line 'Acme | Backend Engineer | Remote (US)' -> (company, role, location).
    None if the line doesn't look like a header (fewer than two parts, a sentence where the
    company should be, or no part that reads as a role)."""
    first = text.split("\n", 1)[0]
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = _PAREN.sub(" ", parts[0]).strip(" -:,*")
    if not company or len(company) > 60 or len(company.split()) > 6 or re.search(r"https?://|www\\.", company):
        return None
    kinds = [(p, _kind(p)) for p in parts[1:]]
    role = next((p for p, k in kinds if k == "role"), None)
    if role is None:
        return None
    locs = [p for p, k in kinds if k == "location"]
    return company, role[:200], ("; ".join(locs)[:200] or None)


def is_remote(header_line: str) -> bool:
    return bool(_REMOTE.search(header_line)) and not _NOT_REMOTE.search(header_line)


def parse_comment(c: dict) -> dict | None:
    """One top-level comment -> {company, title, location, remote, url, apply_url, text},
    or None if it was deleted or its header can't be read with confidence."""
    if not c.get("text") or c.get("deleted") or c.get("dead"):
        return None
    text = html_to_text(c["text"])
    header = split_header(text)
    if header is None:
        return None
    company, title, location = header
    remote = is_remote(text.split("\n", 1)[0])
    # The pre-filter matches the whole word "remote" in location; make sure it's there.
    if remote and not (location and re.search(r"\bremote\b", location, re.I)):
        location = f"Remote; {location}" if location else "Remote"
    links = [html_to_text(h) for h in _HREF.findall(c["text"])]
    apply_url = next((u for u in links if "ycombinator.com" not in u), None)
    return {"company": company, "title": title, "location": location, "remote": remote,
            "url": COMMENT_URL.format(c["id"]), "apply_url": apply_url, "text": text}


def parse(payload: dict, board: dict) -> list[dict]:
    out = []
    for c in payload.get("children", []):
        p = parse_comment(c)
        if p is not None:
            out.append(posting(NAME, p["company"], p["title"], p["location"], p["url"], p["text"]))
    return out
