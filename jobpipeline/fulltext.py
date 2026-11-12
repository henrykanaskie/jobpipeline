"""Fetch the description for postings whose source didn't include one (Simplify, Workday).
Runs only on postings that already passed the pre-filter, so the volume stays small."""
import re
from urllib.parse import urlsplit

from . import http
from .normalize import html_to_text
from .sources import workday

MAX_ATTEMPTS = 3
MIN_TEXT_CHARS = 200     # less than this usually means a JavaScript-only page


def _workday_api_url(url: str) -> str | None:
    parts = urlsplit(url)
    if "myworkdayjobs.com" not in parts.netloc or "/job/" not in parts.path:
        return None
    site_path, job_path = parts.path.split("/job/", 1)
    base = workday.api_base(f"https://{parts.netloc}{site_path}")
    return f"{base}/job/{job_path}"


def fetch_text(sess, url: str) -> str:
    if api := _workday_api_url(url):
        info = http.get_json(sess, api).get("jobPostingInfo") or {}
        return html_to_text(info.get("jobDescription"))
    html = http.request(sess, "GET", url).text
    html = re.sub(r"<(script|style|noscript)\b.*?</\1>", " ", html, flags=re.S | re.I)
    return html_to_text(html)


def fill_missing(conn, limit: int = 20) -> int:
    """Try to fetch text for up to `limit` postings. Returns how many got text."""
    rows = conn.execute(
        """SELECT id, url FROM postings
           WHERE status = 'pending_score' AND full_text IS NULL AND fulltext_attempts < %s
           ORDER BY first_seen_at LIMIT %s""", (MAX_ATTEMPTS, limit)).fetchall()
    sess, got = http.session(), 0
    for r in rows:
        try:
            text = fetch_text(sess, r["url"])
        except Exception:
            text = ""
        ok = len(text) >= MIN_TEXT_CHARS
        conn.execute(
            "UPDATE postings SET full_text = %s, fulltext_attempts = fulltext_attempts + 1 WHERE id = %s",
            (text if ok else None, r["id"]))
        got += ok
    conn.commit()
    return got
