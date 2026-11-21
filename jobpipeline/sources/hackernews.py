"""Hacker News monthly "Ask HN: Who is hiring?" thread, via the free Algolia API.

board = {"token": "whoishiring", "strict": false}
Each top-level comment is one company. The first line is usually
"Company | Role | Location | ..." but the format is informal, so parsing is heuristic.

Two passes. The first reads the header and keeps a comment only when its first line has a
plausible company and a part that looks like a role. The second picks up the comments the
first refuses, which on a real thread is about a third of it: headers that name the company
and the location but list the jobs further down ("Roles currently available:"), and sentences
written where a header should be ("Duranta is hiring a computer vision engineer"). It still
insists on naming both a company and a role, which is what keeps out the status updates, the
bare "Apply here:" links and the one-word locations that are also posted at top level.
Set `strict: true` on the board to run the first pass alone.

Measured against the November 2026 thread: 242 top-level comments, 166 kept by the first pass,
196 by both. Every kept posting stores the comment's full text, so nothing the heuristics miss
is lost. The posting URL is the HN comment (stable and unique per company per month); the
first outbound link is exposed by parse_comment as `apply_url`.
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
    r"interns?\b|consultant|specialist|administrator|technician|recruiter|operator|"
    r"officer|representative|\bcto\b|\bvp\b", re.I)
# Beyond software. "Charly | Sales / Account Executive GovTech | ..." named its
# role as plainly as any header in the thread and was still dropped, because the
# vocabulary above only knew engineering.
_ROLE_WIDER = re.compile(
    r"\bsales\b|account (executive|manager)|\bmarketing\b|customer success|support engineer|"
    r"\bcounsel\b|attorney|paralegal|accountant|bookkeeper|\bwriter\b|\beditor\b|"
    r"\bphd\b|studentship|post[- ]?doc(toral)?|fellow(ship)?|apprentice|"
    r"full[- ]?stack|front[- ]?end|back[- ]?end|\bios\b|\bandroid\b|\bsdet\b|\bqa\b|"
    r"\bnurse\b|therapist|teacher|\bchef\b|\bdriver\b|machinist|welder|"
    r"\btesters?\b|penetration|\b(coo|ceo|cfo|cio|ciso|cmo|cro)\b", re.I)
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
    if _ROLE.search(part) or _ROLE_WIDER.search(part) or (_ROLE_GENERIC.search(part) and not place):
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


# --- second pass: the postings that do not put the role in the header --------
# A third of the thread writes "Company | Location | Full-time" and then lists
# the jobs underneath, or writes a sentence instead of a header. Those are real
# postings, so a second, lower-confidence pass recovers them. It still refuses
# anything it cannot name a company AND a role for, which is what keeps the
# status updates, the "apply here" links and the bare locations out.
# `board = {"strict": true}` turns the pass off and restores header-only parsing.

# Status updates and fragments posted as top-level comments.
_NOISE_FIRST = re.compile(
    r"^\s*(update\b|edit\b|apply here\b|applications? (are |have )?clos|"
    r"(this|the) (position|role|job)s? (has |have |is |are )?(been )?filled|"
    r"no longer (taking|accepting)|thanks to everyone)", re.I)
# "Roles currently available:", "We're hiring for:", "Open roles (all remote):"
_ROLE_LIST_LEAD = re.compile(
    r"^\s*(we(?:'|\u2019)?re |we are |currently )?(hiring|open roles?|open positions?|"
    r"roles?|positions?|openings?|vacancies)\b[^.!?]{0,60}:\s*$", re.I)
_BULLET = re.compile(r"^\s*(?:[-*+\u2022\u00b7>]+|\d+[.)])\s*")
_TRAILING_LINK = re.compile(r"\s*(?:[-\u2013\u2014:]\s*)?(?:https?://|www\.)\S*.*$", re.I)
_SENTENCE_LEAD = re.compile(r"^(we|our|the|at|this|it|they|you|i)\b", re.I)
# "Duranta (https://...) is hiring a computer vision engineer", "DuckDuckGo - we are looking for"
_HIRING_PROSE = re.compile(
    r"^(?P<company>[A-Z][\w&.'\u2019]*(?:[ ][A-Z0-9][\w&.'\u2019]*){0,4})"
    r"(?:\s*\([^)]*\))?\s*(?:[,\u2013\u2014-]\s*)?"
    r"(?:is|are|we(?:'|\u2019)?re|we are)\s+(?:currently\s+)?"
    r"(?:hiring|looking for|seeking|recruiting)\b")
# "We are hiring for several roles at StudyTurtle, an edutainment brand"
_HIRING_AT = re.compile(
    r"\b(?:hiring|recruiting|roles?|positions?|openings?)\b[^.]{0,40}?\bat\s+"
    r"(?P<company>[A-Z][\w&.'\u2019]*(?:[ ][A-Z0-9][\w&.'\u2019]*){0,3})")


_ROLE_LEAD_INLINE = re.compile(
    r"^\s*(we(?:'|\u2019)?re |we are |currently )?(hiring|open roles?|open positions?|"
    r"roles?|positions?|openings?)\b[^:]{0,40}:\s*", re.I)


def _clean_role(line: str) -> str | None:
    """A body line reduced to the job title it names, or None if it is prose."""
    line = _TRAILING_LINK.sub("", _BULLET.sub("", line)).strip(" -:,*\u2013\u2014")
    line = _ROLE_LEAD_INLINE.sub("", line)
    line = re.sub(r"\s+", " ", line).split("|")[0].strip(" -:,")
    # "VP of Engineering: owns the platform end to end, from on-chain ..." is a
    # title followed by its description.
    if (len(line) > 90 or len(line.split()) > 12) and ":" in line:
        line = line.split(":", 1)[0].strip(" -,")
    if not line or len(line) > 90 or len(line.split()) > 12:
        return None
    if _SENTENCE_LEAD.match(line) or line.rstrip().endswith((".", "!", "?")):
        return None
    if not (_ROLE.search(line) or _ROLE_WIDER.search(line)):
        return None
    return line[:200]


def role_from_body(text: str) -> str | None:
    """The first job title listed under a header that did not carry one.

    Prefers the line after an explicit lead-in ("Roles currently available:"),
    then a bulleted line, then any short line that reads as a title rather than
    a sentence."""
    lines = [l.strip() for l in text.split("\n")[1:]]
    for i, line in enumerate(lines):
        if line and _ROLE_LIST_LEAD.match(line):
            for nxt in lines[i + 1:]:
                if not nxt:
                    continue
                role = _clean_role(nxt)
                if role:
                    return role
                break
    for line in lines:
        if line and _BULLET.match(line):
            role = _clean_role(line)
            if role:
                return role
    for line in lines:
        role = _clean_role(line) if line else None
        if role:
            return role
    return None


def _prose_company(first: str) -> str | None:
    """The company from a sentence that stands where a header should."""
    for rx in (_HIRING_PROSE, _HIRING_AT):
        m = rx.search(first)
        if m:
            company = _PAREN.sub(" ", m.group("company")).strip(" -:,*")
            if company and len(company) <= 60 and len(company.split()) <= 6:
                return company
    return None


def _role_from_sentence(first: str) -> str | None:
    """The role named in the sentence that stands where a header should:
    "... is hiring a computer vision engineer, ..." -> the first title in it."""
    m = re.search(r"\b(?:hiring|looking for|seeking|recruiting)\b\s*(?:for\s+)?(?:an?\s+)?"
                  r"(?P<rest>.{3,120})", first, re.I)
    if not m:
        return None
    for chunk in re.split(r",| and | & |\.|;", m.group("rest")):
        role = _clean_role(chunk)
        if role:
            return role
    return None


def recover_header(text: str) -> tuple[str, str, str | None] | None:
    """``split_header`` for the comments it refuses: the company from the header
    (or from a sentence), the role from the body. None when either is missing."""
    first = text.split("\n", 1)[0]
    if _NOISE_FIRST.match(first):
        return None
    parts = [p.strip() for p in first.split("|") if p.strip()]
    company = None
    if len(parts) >= 2:
        candidate = _PAREN.sub(" ", parts[0]).strip(" -:,*")
        if candidate and len(candidate) <= 60 and len(candidate.split()) <= 6 \
                and not re.search(r"https?://|www\.", candidate):
            company = candidate
    if company is None:
        company = _prose_company(first)
    if company is None:
        return None
    role = role_from_body(text) or _role_from_sentence(first)
    if role is None:
        return None
    locs = [p for p in parts[1:] if _kind(p) == "location"]
    return company, role[:200], ("; ".join(locs)[:200] or None)


def is_remote(header_line: str) -> bool:
    return bool(_REMOTE.search(header_line)) and not _NOT_REMOTE.search(header_line)


def parse_comment(c: dict, loose: bool = True) -> dict | None:
    """One top-level comment -> {company, title, location, remote, url, apply_url, text},
    or None if it was deleted, or neither pass could name a company and a role."""
    if not c.get("text") or c.get("deleted") or c.get("dead"):
        return None
    text = html_to_text(c["text"])
    header = split_header(text)
    if header is None and loose:
        header = recover_header(text)
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
    loose = not board.get("strict", False)
    out = []
    for c in payload.get("children", []):
        p = parse_comment(c, loose=loose)
        if p is not None:
            out.append(posting(NAME, p["company"], p["title"], p["location"], p["url"], p["text"]))
    return out
