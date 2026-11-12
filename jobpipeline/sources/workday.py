"""Workday career sites via the unofficial JSON endpoints their own web pages use. Expect breakage.

board = {"token": "nvidia", "company": "NVIDIA",
         "url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite",
         "search": "software engineer"}       # optional; strongly recommended (keeps page count low)
"""
import re
import time
from urllib.parse import urlsplit

from .. import http
from ._common import posting

NAME = "workday"
PAGE_SIZE = 20
MAX_PAGES = 10            # 200 postings per board per crawl at most
_LOCALE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def site_parts(career_url: str) -> tuple[str, str, str]:
    """-> (host, tenant, site) from a career-site URL, ignoring a locale segment like en-US."""
    parts = urlsplit(career_url)
    segs = [s for s in parts.path.split("/") if s and not _LOCALE.match(s)]
    if not segs:
        raise ValueError(f"can't find the Workday site name in {career_url}")
    return parts.netloc, parts.netloc.split(".")[0], segs[0]


def api_base(career_url: str) -> str:
    host, tenant, site = site_parts(career_url)
    return f"https://{host}/wday/cxs/{tenant}/{site}"


def fetch(sess, board: dict) -> dict:
    base = api_base(board["url"])
    jobs, total = [], None
    for page in range(MAX_PAGES):
        data = http.post_json(sess, f"{base}/jobs", {
            "appliedFacets": {}, "limit": PAGE_SIZE, "offset": page * PAGE_SIZE,
            "searchText": board.get("search", "")})
        batch = data.get("jobPostings") or []
        if total is None:
            total = data.get("total") or 0     # Workday only reports total on the first page
        jobs += batch
        if len(batch) < PAGE_SIZE or len(jobs) >= total:
            break
        time.sleep(1)
    return {"jobPostings": jobs}


def parse(payload: dict, board: dict) -> list[dict]:
    host, _, site = site_parts(board["url"])
    return [
        posting(NAME, board["company"], j["title"], j.get("locationsText"),
                f"https://{host}/{site}{j['externalPath']}", None)   # description fetched later
        for j in payload.get("jobPostings", [])
        if j.get("externalPath") and j.get("title")
    ]
