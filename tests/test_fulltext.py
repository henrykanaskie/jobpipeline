from pathlib import Path

import pytest
import requests

from jobpipeline import fulltext

PAGES = Path(__file__).parent / "fixtures" / "pages"


def page(name: str) -> str:
    return (PAGES / name).read_text()


class FakeResponse:
    def __init__(self, text="", url="https://jobs.example.com/1", ctype="text/html; charset=utf-8", status=200):
        self.text, self.url, self.status_code = text, url, status
        self.headers = {"content-type": ctype}


@pytest.fixture
def serve(monkeypatch):
    """serve(resp) makes the next http.request return resp (or raise it); records calls."""
    calls, queue = [], []

    def fake_request(sess, method, url, **kw):
        calls.append((method, url, kw))
        r = queue.pop(0)
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(fulltext.http, "request", fake_request)

    def push(r):
        queue.append(r)
        return calls
    return push


def test_extract_prefers_jsonld_over_page_chrome():
    text = fulltext.extract(page("jsonld.html"))
    assert text.startswith("We are looking for a backend engineer")
    assert text.endswith("Python\n\nPostgres") and "Home | Jobs" not in text and "Loading" not in text


def test_extract_main_content_without_scripts_or_chrome():
    text = fulltext.extract(page("main.html"))
    assert text.startswith("Data Engineer") and "Airflow" in text
    assert "analytics" not in text and "Log in" not in text and "Copyright" not in text


def test_extract_body_drops_nav_and_footer():
    text = fulltext.extract(page("body_only.html"))
    assert "Platform Engineer" in text and "Menu items" not in text and "Footer" not in text


def test_fetch_text_jsonld_page_with_apply_captcha_is_not_blocked(serve):
    calls = serve(FakeResponse(page("jsonld.html")))
    assert len(fulltext.fetch_text(None, "https://jobs.example.com/1")) >= fulltext.MIN_TEXT_CHARS
    assert calls[0][2]["timeout"] == fulltext.TIMEOUT and calls[0][2]["attempts"] == 2


@pytest.mark.parametrize("name", ["cf_challenge.html", "login.html"])
def test_fetch_text_challenge_and_login_pages_are_blocked(serve, name):
    serve(FakeResponse(page(name)))
    with pytest.raises(fulltext.Blocked):
        fulltext.fetch_text(None, "https://jobs.example.com/1")


def test_fetch_text_redirect_to_login_is_blocked(serve):
    serve(FakeResponse(page("main.html"), url="https://example.icims.com/jobs/login?redirect=1"))
    with pytest.raises(fulltext.Blocked, match="login"):
        fulltext.fetch_text(None, "https://example.icims.com/jobs/1/job")


def test_fetch_text_forbidden_is_blocked(serve):
    resp = requests.Response()
    resp.status_code = 403
    serve(requests.HTTPError(response=resp))
    with pytest.raises(fulltext.Blocked):
        fulltext.fetch_text(None, "https://jobs.example.com/1")


def test_fetch_text_js_only_and_non_html_give_nothing(serve):
    serve(FakeResponse(page("spa.html")))
    assert len(fulltext.fetch_text(None, "https://jobs.example.com/1")) < fulltext.MIN_TEXT_CHARS
    serve(FakeResponse("%PDF-1.4", ctype="application/pdf"))
    assert fulltext.fetch_text(None, "https://jobs.example.com/2.pdf") == ""


def test_lever_apply_links_fetch_the_posting_page(serve):
    calls = serve(FakeResponse(page("main.html")))
    fulltext.fetch_text(None, "https://jobs.lever.co/acme/abc-123/apply")
    assert calls[0][1] == "https://jobs.lever.co/acme/abc-123"


def test_rate_limiter_spaces_requests_per_host_and_overall():
    t, slept = [0.0], []

    def sleep(s):
        slept.append(round(s, 2))
        t[0] += s
    lim = fulltext.RateLimiter(per_host=5, overall=1, clock=lambda: t[0], sleep=sleep)
    lim.wait("https://a.com/1")                     # first: no wait
    lim.wait("https://b.com/1")                     # other host: overall gap only
    lim.wait("https://a.com/2")                     # same host: 5 s after the first a.com
    assert slept == [1, 4]


class FakeConn:
    def __init__(self, rows):
        self.rows, self.updates, self.committed = rows, [], False

    def execute(self, sql, params=()):
        if sql.lstrip().startswith("UPDATE"):
            self.updates.append((" ".join(sql.split()), params))
        return self

    def fetchall(self):
        return self.rows

    def commit(self):
        self.committed = True


def test_fill_missing_stores_text_only_on_success_and_stops_retrying_blocked(monkeypatch):
    results = {"https://ok/1": "x" * 300, "https://short/1": "tiny",
               "https://blocked/1": fulltext.Blocked("login"), "https://err/1": TimeoutError("slow")}

    def fake_fetch(sess, url, limiter):
        r = results[url]
        if isinstance(r, Exception):
            raise r
        return r
    monkeypatch.setattr(fulltext, "fetch_text", fake_fetch)
    conn = FakeConn([{"id": i, "url": u} for i, u in enumerate(results)])
    assert fulltext.fill_missing(conn) == 1 and conn.committed
    stored = [(params[0], "fulltext_attempts = 3" in sql) for sql, params in conn.updates]
    assert stored == [("x" * 300, False), (None, False), (None, True), (None, False)]
