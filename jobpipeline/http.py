"""Shared HTTP helpers: polite User-Agent, timeouts, exponential backoff on 429/5xx."""
import time

import requests

USER_AGENT = "jobpipeline-crawler/0.1 (personal job search)"


def session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def _retryable(e: Exception) -> bool:
    if isinstance(e, requests.HTTPError):
        code = e.response.status_code if e.response is not None else 0
        return code == 429 or code >= 500
    return isinstance(e, (requests.ConnectionError, requests.Timeout))


def request(sess: requests.Session, method: str, url: str, attempts: int = 4, **kw) -> requests.Response:
    for i in range(attempts):
        try:
            r = sess.request(method, url, timeout=30, **kw)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if not _retryable(e) or i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))
    raise AssertionError("unreachable")


def get_json(sess, url, **kw):
    return request(sess, "GET", url, **kw).json()


def post_json(sess, url, body, **kw):
    return request(sess, "POST", url, json=body, **kw).json()
