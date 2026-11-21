"""Fetch the description for postings whose source didn't include one (Simplify, carpet,
Workday). Runs only on postings that already passed the pre-filter, so the volume stays small.

- Workday links use Workday's JSON detail endpoint.
- Other pages: the JobPosting description in JSON-LD if present (most ATS pages have it),
  else the page's <main>/<article>, else the body without nav/header/footer.
- Pages behind a login or a bot challenge (CAPTCHA, Cloudflare, DataDome...) are skipped and
  not retried. A CAPTCHA widget on an apply form doesn't count; only a page that gates the
  description does.
- Nothing is stored unless at least MIN_TEXT_CHARS of text came out.
- Short timeout, at most one retry, and at least PER_HOST_INTERVAL seconds between requests
  to the same host.
"""
import json
import logging
import re
import time
from urllib.parse import urlsplit

import requests

from . import http
from .normalize import html_to_text
from .sources import workday

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 3
MIN_TEXT_CHARS = 200          # less than this usually means a JavaScript-only page
TIMEOUT = 15                  # seconds per request
PER_HOST_INTERVAL = 5.0       # seconds between requests to one host
MIN_INTERVAL = 1.0            # seconds between any two requests
MAX_HTML_CHARS = 3_000_000

_LOGIN_PATH = re.compile(r"/(login|log-in|signin|sign-in|sign_in|auth|sso|oauth2?|session/new|account/login)\b", re.I)
_LOGIN_HOSTS = ("accounts.google.com", "login.microsoftonline.com", "auth0.com", "okta.com")
# Markers of an interstitial challenge page. Not "/cdn-cgi/challenge-platform" or Turnstile /
# hCaptcha scripts: Cloudflare injects the first into ordinary pages and apply forms embed the rest.
_CHALLENGE = re.compile(
    r"_cf_chl_opt|cf-chl-widget|geo\.captcha-delivery\.com|id=[\"']px-captcha|"
    r"verify (that )?you are (a )?human|are you a robot|unusual traffic from your computer|"
    r"request unsuccessful\. incapsula", re.I)
_CHALLENGE_TITLE = re.compile(r"just a moment|attention required|captcha|security check|"
                              r"access denied|sign ?in|log ?in", re.I)
_PASSWORD = re.compile(r"<input\b[^>]*type=[\"']?password", re.I)
_LD_JSON = re.compile(r"<script\b[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>", re.S | re.I)
_TITLE = re.compile(r"<title\b[^>]*>(.*?)</title>", re.S | re.I)


class Blocked(Exception):
    """The page is behind a login or a bot challenge."""


class RateLimiter:
    def __init__(self, per_host: float = PER_HOST_INTERVAL, overall: float = MIN_INTERVAL,
                 clock=time.monotonic, sleep=time.sleep):
        self.per_host, self.overall, self.clock, self.sleep = per_host, overall, clock, sleep
        self.last_host: dict[str, float] = {}
        self.last_any: float | None = None

    def wait(self, url: str) -> None:
        host = urlsplit(url).netloc.lower()
        now = self.clock()
        due = max(self.last_host.get(host, -1e18) + self.per_host,
                  (self.last_any if self.last_any is not None else -1e18) + self.overall)
        if due > now:
            self.sleep(due - now)
            now = due
        self.last_host[host] = self.last_any = now


def _workday_api_url(url: str) -> str | None:
    parts = urlsplit(url)
    if not parts.netloc.endswith(("myworkdayjobs.com", "myworkdaysite.com")) or "/job/" not in parts.path:
        return None
    site_path, job_path = parts.path.split("/job/", 1)
    base = workday.api_base(f"https://{parts.netloc}{site_path}")
    return f"{base}/job/{job_path}"


def page_url(url: str) -> str:
    """Simplify often links to an ATS's apply form; the description is on the posting page."""
    parts = urlsplit(url)
    if parts.netloc.lower() in ("jobs.lever.co", "jobs.eu.lever.co") and parts.path.endswith("/apply"):
        return parts._replace(path=parts.path[: -len("/apply")]).geturl()
    return url


def _jsonld_description(html: str) -> str | None:
    def walk(node):
        if isinstance(node, list):
            for n in node:
                yield from walk(n)
        elif isinstance(node, dict):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                yield node
            yield from walk(node.get("@graph"))
    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for jp in walk(data):
            if isinstance(jp.get("description"), str) and jp["description"].strip():
                return jp["description"]
    return None


def check_blocked(final_url: str, html: str, has_jsonld: bool) -> None:
    """Raise Blocked if the response is a login wall or a bot challenge."""
    parts = urlsplit(final_url)
    if parts.netloc.lower().endswith(_LOGIN_HOSTS) or _LOGIN_PATH.search(parts.path):
        raise Blocked(f"redirected to a login page: {final_url}")
    if has_jsonld:
        return       # the description is in the page; a widget elsewhere on it doesn't matter
    title = html_to_text(m.group(1)) if (m := _TITLE.search(html)) else ""
    if _CHALLENGE_TITLE.search(title):
        raise Blocked(f"page title looks like a challenge or login: {title[:80]!r}")
    if _CHALLENGE.search(html):
        raise Blocked("bot challenge on page")
    if _PASSWORD.search(html):
        raise Blocked("password field on page")


def extract(html: str) -> str:
    """Description text from a job page (JSON-LD JobPosting, else main content)."""
    if desc := _jsonld_description(html):
        return html_to_text(desc)
    html = re.sub(r"<(script|style|noscript|svg|template)\b.*?</\1>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    for tag in ("main", "article"):
        if m := re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", html, flags=re.S | re.I):
            return html_to_text(m.group(1))
    body = m.group(1) if (m := re.search(r"<body\b[^>]*>(.*)</body>", html, flags=re.S | re.I)) else html
    body = re.sub(r"<(nav|header|footer|form)\b.*?</\1>", " ", body, flags=re.S | re.I)
    return html_to_text(body)


def fetch_text(sess, url: str, limiter: RateLimiter | None = None) -> str:
    """Description text for `url`, or "" if nothing usable came back.
    Raises Blocked for login walls and challenges; other request errors propagate."""
    url = page_url(url)
    if limiter:
        limiter.wait(url)
    if api := _workday_api_url(url):
        info = http.get_json(sess, api, attempts=2, timeout=TIMEOUT,
                             headers={"Accept": "application/json"}).get("jobPostingInfo") or {}
        return html_to_text(info.get("jobDescription"))
    try:
        r = http.request(sess, "GET", url, attempts=2, timeout=TIMEOUT)
    except requests.HTTPError as e:
        if e.response is not None and e.response.status_code in (401, 403, 407):
            raise Blocked(f"HTTP {e.response.status_code}") from None
        raise
    ctype = r.headers.get("content-type", "")
    if "html" not in ctype.lower():
        return ""     # PDFs, JSON, images: not worth guessing at
    html = r.text[:MAX_HTML_CHARS]
    check_blocked(r.url or url, html, _jsonld_description(html) is not None)
    return extract(html)


def fill_missing(conn, limit: int = 20, limiter: RateLimiter | None = None) -> int:
    """Try to fetch text for up to `limit` postings. Returns how many got text."""
    rows = conn.execute(
        """SELECT id, url FROM postings
           WHERE status = 'pending_score' AND full_text IS NULL AND fulltext_attempts < %s
           ORDER BY first_seen_at LIMIT %s""", (MAX_ATTEMPTS, limit)).fetchall()
    sess, got = http.session(), 0
    limiter = limiter or RateLimiter()
    for r in rows:
        attempts = "fulltext_attempts + 1"
        try:
            text = fetch_text(sess, r["url"], limiter)
        except Blocked as e:
            log.info("full text skipped for %s: %s", r["url"], e)
            text, attempts = "", str(MAX_ATTEMPTS)     # don't retry a login wall or challenge
        except Exception as e:
            log.info("full text failed for %s: %s", r["url"], e)
            text = ""
        ok = len(text) >= MIN_TEXT_CHARS
        conn.execute(
            f"UPDATE postings SET full_text = %s, fulltext_attempts = {attempts} WHERE id = %s",
            (text if ok else None, r["id"]))
        got += ok
    conn.commit()
    return got
