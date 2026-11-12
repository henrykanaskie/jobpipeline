"""Integration tests; need TEST_DATABASE_URL pointing at a throwaway Postgres database."""
from unittest import mock

from jobpipeline import crawler, db, mcp_server, screening


def _p(url, title="Software Engineer", company="stripe", location="Remote"):
    return {"source": "greenhouse", "company": company, "company_display": company.title(),
            "title": title, "location": location, "url": url, "full_text": "x"}


def test_url_dedupe(conn):
    assert len(db.insert_postings(conn, [_p("https://a/1"), _p("https://a/2")])) == 2
    assert len(db.insert_postings(conn, [_p("https://a/1"), _p("https://a/3")])) == 1
    assert conn.execute("SELECT count(*) AS n FROM postings").fetchone()["n"] == 3


def test_screening_applied_skip_and_prefilter(conn, monkeypatch):
    db.insert_postings(conn, [_p("https://a/1"), _p("https://a/2", title="Senior Software Engineer"),
                              _p("https://b/1", company="ramp")])
    ramp_id = conn.execute("SELECT id FROM postings WHERE company='ramp'").fetchone()["id"]
    conn.execute("INSERT INTO applications (posting_id, company) VALUES (%s, 'ramp')", (ramp_id,))
    conn.commit()
    monkeypatch.setattr(screening.config, "load", lambda _: {
        "title_include": ["software engineer"], "title_exclude": ["senior"]})
    monkeypatch.delenv("RESUME_SERVICE_URL", raising=False)
    stats = screening.screen_once(conn)
    assert stats == {"captcha_expired": 0, "skipped_applied": 1, "pending_score": 1, "filtered_out": 1,
                     "fulltext_fetched": 0}


def test_captcha_timeout(conn):
    [p] = db.insert_postings(conn, [_p("https://a/1")])
    conn.execute("""INSERT INTO applications (posting_id, company, status, captcha_started_at)
                    VALUES (%s, 'stripe', 'captcha_wait', now() - interval '31 minutes')""", (p["id"],))
    conn.commit()
    assert screening.expire_captchas(conn) == 1
    assert conn.execute("SELECT status FROM applications").fetchone()["status"] == "needs_manual"


def test_zero_result_alert_fires_once_then_recovery(conn):
    mod = mock.Mock(NAME="greenhouse", url=lambda b: "u")
    board = {"token": "t", "company": "T"}
    alerts = []
    with mock.patch.object(crawler.notify, "alert", alerts.append), \
         mock.patch.object(crawler, "fetch_payload", return_value={}):
        mod.parse.return_value = [_p("https://a/1")]
        crawler.crawl_board(conn, None, mod, board)          # healthy
        mod.parse.return_value = []
        crawler.crawl_board(conn, None, mod, board)          # broken -> alert
        crawler.crawl_board(conn, None, mod, board)          # still broken -> silent
        mod.parse.return_value = [_p("https://a/2")]
        crawler.crawl_board(conn, None, mod, board)          # recovered -> alert
    assert len(alerts) == 2 and "zero" in alerts[0] and "recovered" in alerts[1]


def test_mcp_tools_roundtrip(conn, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", conn.info.dsn)
    db.insert_postings(conn, [_p("https://a/1", title="Backend Engineer"), _p("https://b/1", company="ramp")])
    [hit] = mcp_server.search_jobs("backend")
    assert hit["url"] == "https://a/1"
    assert mcp_server.get_posting(hit["id"])["application"] is None

    app = mcp_server.record_application(hit["id"], "captcha_wait")
    assert app["captcha_started_at"] is not None
    app = mcp_server.record_application(hit["id"], "submitted", resume_path="resumes/a.pdf")
    assert app["submitted_at"] is not None and app["resume_path"] == "resumes/a.pdf"
    # applying to stripe hides other stripe jobs from search by default
    assert [j["company"] for j in mcp_server.search_jobs("")] == ["Ramp"]
    assert len(mcp_server.search_jobs("", include_applied=True)) == 2
