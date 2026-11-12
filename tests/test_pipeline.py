"""Scoring/tailoring flow against a fake resume service. Needs TEST_DATABASE_URL."""
import pytest

from jobpipeline import db, report, resume_client, screening


def _p(url, company="stripe", title="Software Engineer", source="greenhouse"):
    return {"source": source, "company": company, "company_display": company.title(), "title": title,
            "location": "Remote", "url": url, "full_text": "x" * 300}


@pytest.fixture
def fake_service(monkeypatch):
    state = {"scores": {}, "tailor": {}, "requested": [], "down": False}
    monkeypatch.setenv("RESUME_SERVICE_URL", "http://fake")
    monkeypatch.setattr(screening.notify, "alert", lambda m: state.setdefault("alerts", []).append(m))
    monkeypatch.setattr(screening.notify, "match", lambda p: state.setdefault("matches", []).append(p["url"]))

    def score(p):
        if state["down"]:
            raise resume_client.Unavailable("down")
        return state["scores"][p["url"]], "because"

    def request_tailoring(p):
        if state["down"]:
            raise resume_client.Unavailable("down")
        state["requested"].append(p["url"])

    monkeypatch.setattr(resume_client, "score", score)
    monkeypatch.setattr(resume_client, "request_tailoring", request_tailoring)
    monkeypatch.setattr(resume_client, "tailoring_status", lambda jid: state["tailor"].get(jid, {"status": "queued"}))
    return state


def test_cross_source_dedupe(conn):
    assert len(db.insert_postings(conn, [_p("https://gh/1", title="Software Engineer, New Grad")])) == 1
    # same company + title from another source under a different URL: skipped
    assert db.insert_postings(conn, [_p("https://simplify/9", title="Software Engineer - New Grad",
                                        source="simplify")]) == []
    # same source, different URL: kept (could be a separate req)
    assert len(db.insert_postings(conn, [_p("https://gh/2", title="Software Engineer, New Grad")])) == 1


def test_score_match_tailor_done(conn, fake_service):
    db.insert_postings(conn, [_p("https://a/1"), _p("https://a/2", company="ramp")])
    conn.execute("UPDATE postings SET status = 'pending_score'")
    conn.commit()
    fake_service["scores"] = {"https://a/1": 90, "https://a/2": 40}
    assert screening.score_pending(conn) == 2
    rows = {r["url"]: r for r in conn.execute("SELECT * FROM postings").fetchall()}
    assert rows["https://a/1"]["status"] == "tailoring" and rows["https://a/1"]["tailor_requested_at"]
    assert rows["https://a/2"]["status"] == "screened"
    assert fake_service["matches"] == ["https://a/1"] and fake_service["requested"] == ["https://a/1"]

    jid = str(rows["https://a/1"]["id"])
    fake_service["tailor"][jid] = {"status": "done", "resume_path": "resumes/a.pdf", "summary": "s"}
    assert screening.poll_tailoring(conn) == 1
    r = conn.execute("SELECT status, resume_path FROM postings WHERE id = %s", (jid,)).fetchone()
    assert r == {"status": "tailored", "resume_path": "resumes/a.pdf"}


def test_tailor_request_retried_without_rescoring(conn, fake_service):
    db.insert_postings(conn, [_p("https://a/1")])
    conn.execute("UPDATE postings SET status = 'pending_score'")
    conn.commit()
    fake_service["scores"] = {"https://a/1": 90}
    calls = []
    real = resume_client.request_tailoring

    def flaky(p):
        calls.append(1)
        if len(calls) == 1:
            raise resume_client.Unavailable("blip")
        real(p)
    resume_client.request_tailoring = flaky
    try:
        screening.score_pending(conn)
        assert conn.execute("SELECT tailor_requested_at FROM postings").fetchone()["tailor_requested_at"] is None
        screening.poll_tailoring(conn)       # re-sends the request
    finally:
        resume_client.request_tailoring = real
    assert len(calls) == 2
    assert conn.execute("SELECT count(*) AS n FROM score_calls").fetchone()["n"] == 1


def test_service_down_leaves_posting_and_daily_cap(conn, fake_service, monkeypatch):
    db.insert_postings(conn, [_p(f"https://a/{i}", company=f"c{i}") for i in range(5)])
    conn.execute("UPDATE postings SET status = 'pending_score'")
    conn.commit()
    fake_service["down"] = True
    assert screening.score_pending(conn) == 0
    assert conn.execute("SELECT count(*) AS n FROM postings WHERE status='pending_score'").fetchone()["n"] == 5
    fake_service["down"] = False
    fake_service["scores"] = {f"https://a/{i}": 10 for i in range(5)}
    monkeypatch.setattr(screening, "SCORE_DAILY_LIMIT", 3)    # 1 call already spent while down
    assert screening.score_pending(conn) == 2


def test_tailor_failure_and_timeout_alert(conn, fake_service):
    [a, b] = db.insert_postings(conn, [_p("https://a/1"), _p("https://a/2", company="ramp")])
    conn.execute("UPDATE postings SET status = 'tailoring', tailor_requested_at = now()")
    conn.execute("UPDATE postings SET tailor_requested_at = now() - interval '25 hours' WHERE id = %s", (b["id"],))
    conn.commit()
    fake_service["tailor"][str(a["id"])] = {"status": "failed", "error": "usage limit"}
    screening.poll_tailoring(conn)
    st = {r["url"]: (r["status"], r["tailor_error"]) for r in conn.execute("SELECT * FROM postings").fetchall()}
    assert st["https://a/1"] == ("tailor_failed", "usage limit")
    assert st["https://a/2"][0] == "tailor_failed" and "timed out" in st["https://a/2"][1]
    assert len(fake_service["alerts"]) == 2


def test_outcome_report(conn):
    [a] = db.insert_postings(conn, [_p("https://a/1")])
    conn.execute("UPDATE postings SET fit_score = 80")
    conn.execute("INSERT INTO applications (posting_id, company, status, outcome) VALUES (%s,'stripe','submitted','interview')",
                 (a["id"],))
    conn.commit()
    row = next(r for r in report.outcome_table(conn) if r["bucket"] == "75-85")
    assert row["interview_or_offer"] == 1 and row["rate"] == 1.0
