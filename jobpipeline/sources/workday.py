"""Workday career sites via the unofficial CXS JSON endpoints their own web pages use.
Expect breakage: every failure below raises, so the crawler records an error and alerts.

Either give the career-site URL:
    {"token": "nvidia", "company": "NVIDIA",
     "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
     "search": "software engineer"}
or the three parts explicitly (needed when the tenant isn't the first label of the host):
    {"token": "salesforce", "company": "Salesforce",
     "host": "salesforce.wd12.myworkdayjobs.com", "tenant": "salesforce",
     "site": "External_Career_Site", "search": "software engineer"}
Optional: "max_postings" (default 200) caps how many postings one crawl pages through.
Always set "search"; large tenants have thousands of postings.
"""
import logging
import re
import time
from urllib.parse import urlsplit

from .. import http
from ._common import posting

NAME = "workday"
PAGE_SIZE = 20
DEFAULT_MAX_POSTINGS = 200
PAUSE_BETWEEN_PAGES = 1.0
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
_MULTI_LOC = re.compile(r"^\d+ Locations$", re.I)
log = logging.getLogger(__name__)


class WorkdayError(Exception):
    pass


def site_parts(career_url: str) -> tuple[str, str, str]:
    """-> (host, tenant, site) from a career-site URL, ignoring a locale segment like en-US.
    Handles both <tenant>.wdN.myworkdayjobs.com/<site> and
    wdN.myworkdaysite.com/recruiting/<tenant>/<site>."""
    parts = urlsplit(career_url)
    segs = [s for s in parts.path.split("/") if s and not _LOCALE.match(s)]
    if len(segs) >= 3 and segs[0] == "recruiting":
        return parts.netloc, segs[1], segs[2]
    if not segs:
        raise ValueError(f"can't find the Workday site name in {career_url}")
    return parts.netloc, parts.netloc.split(".")[0], segs[0]


def board_parts(board: dict) -> tuple[str, str, str]:
    if board.get("host") and board.get("tenant") and board.get("site"):
        return board["host"], board["tenant"], board["site"]
    if board.get("url"):
        return site_parts(board["url"])
    raise ValueError("workday board needs `url`, or all of `host`, `tenant` and `site`")


def api_base(career_url: str) -> str:
    host, tenant, site = site_parts(career_url)
    return f"https://{host}/wday/cxs/{tenant}/{site}"


def _public_base(host: str, tenant: str, site: str) -> str:
    if "myworkdaysite.com" in host:
        return f"https://{host}/recruiting/{tenant}/{site}"
    return f"https://{host}/{site}"


def _post_page(sess, url: str, body: dict) -> dict:
    # Workday answers a maintenance window with a 303 to an HTML page; don't follow it.
    r = http.request(sess, "POST", url, json=body, allow_redirects=False,
                     headers={"Accept": "application/json"})
    if 300 <= r.status_code < 400:
        raise WorkdayError(f"redirected to {r.headers.get('location')!r} (maintenance or a moved site?)")
    try:
        data = r.json()
    except ValueError:
        raise WorkdayError(f"non-JSON response ({r.headers.get('content-type')}) from {url}") from None
    if not isinstance(data, dict) or not isinstance(data.get("jobPostings", []), list):
        raise WorkdayError(f"unexpected response shape from {url}")
    return data


def fetch(sess, board: dict) -> dict:
    host, tenant, site = board_parts(board)
    url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    cap = int(board.get("max_postings", DEFAULT_MAX_POSTINGS))
    jobs, total = [], None
    while len(jobs) < cap:
        data = _post_page(sess, url, {"appliedFacets": {}, "limit": PAGE_SIZE, "offset": len(jobs),
                                      "searchText": board.get("search", "")})
        if total is None:
            if "jobPostings" not in data:
                raise WorkdayError(f"no jobPostings in response from {url} (keys: {sorted(data)})")
            total = data.get("total") or 0     # Workday only reports total on the first page
        batch = data.get("jobPostings") or []
        jobs += batch
        if len(batch) < PAGE_SIZE or len(jobs) >= total:
            break
        time.sleep(PAUSE_BETWEEN_PAGES)
    if total and len(jobs) < total and len(jobs) >= cap:
        log.warning("workday/%s: stopped at %d of %d postings (max_postings); narrow `search`",
                    board.get("token"), len(jobs), total)
    return {"total": total, "jobPostings": jobs[:cap]}


def _location(j: dict) -> str | None:
    """locationsText, except '3 Locations' becomes the primary location from the path
    ('/job/California---San-Francisco/...' -> 'California - San Francisco (+2 more)')."""
    text = (j.get("locationsText") or "").strip()
    if not _MULTI_LOC.match(text):
        return text or None
    segs = j["externalPath"].split("/")
    if len(segs) < 4 or segs[1] != "job":
        return text
    primary = " - ".join(p.replace("-", " ") for p in segs[2].split("---"))
    return f"{primary} (+{int(text.split()[0]) - 1} more)"


def parse(payload: dict, board: dict) -> list[dict]:
    host, tenant, site = board_parts(board)
    base = _public_base(host, tenant, site)
    raw = payload.get("jobPostings", [])
    out = [
        posting(NAME, board["company"], j["title"], _location(j),
                f"{base}{j['externalPath']}", None)   # description fetched later
        for j in raw
        if j.get("externalPath") and j.get("title")
    ]
    if raw and not out:
        raise WorkdayError(f"{len(raw)} postings but none had a title and externalPath; format changed?")
    return out
