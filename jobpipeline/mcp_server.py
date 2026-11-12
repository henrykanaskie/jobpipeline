"""MCP server over the live Postings DB.

    python -m jobpipeline.mcp_server                      # stdio (Claude Code on the same machine)
    python -m jobpipeline.mcp_server --http --port 8765   # streamable HTTP (reach it over Tailscale)
"""
import argparse
import os
from datetime import datetime
from pathlib import Path

import yaml
from mcp.server.mcpserver import MCPServer

from . import db, notify

STANDARD_ANSWERS = Path(__file__).resolve().parent.parent / "data" / "standard_answers.yaml"

APPLICATION_STATUSES = {"in_progress", "captcha_wait", "submitted", "needs_manual", "failed"}
OUTCOMES = {"no_response", "rejected", "interview", "offer"}

server = MCPServer("jobpipeline", instructions=(
    "Search crawled job postings, read a posting's full text, and record application progress."))


def _jsonable(row: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else
                float(v) if k == "fit_score" and v is not None else
                str(v) if k.endswith("id") and v is not None else v)
            for k, v in row.items()}


@server.tool()
def search_jobs(query: str = "", min_fit_score: float | None = None, company: str = "",
                include_applied: bool = False, limit: int = 20) -> list[dict]:
    """Search postings by keywords in title/company/location (all words must match).
    Ordered by fit score (unscored last), then newest. Excludes companies already applied to
    unless include_applied is true."""
    sql = ["""SELECT p.id, p.company_display AS company, p.title, p.location, p.url, p.source,
                     p.fit_score, p.status, p.first_seen_at
              FROM postings p WHERE p.status <> 'filtered_out'"""]
    params: list = []
    for word in query.split():
        sql.append("AND (p.title ILIKE %s OR p.company_display ILIKE %s OR p.location ILIKE %s)")
        params += [f"%{word}%"] * 3
    if company:
        sql.append("AND p.company_display ILIKE %s")
        params.append(f"%{company}%")
    if min_fit_score is not None:
        sql.append("AND p.fit_score >= %s")
        params.append(min_fit_score)
    if not include_applied:
        sql.append("AND NOT EXISTS (SELECT 1 FROM applications a WHERE a.company = p.company)")
    sql.append("ORDER BY p.fit_score DESC NULLS LAST, p.first_seen_at DESC LIMIT %s")
    params.append(max(1, min(limit, 100)))
    with db.connect() as conn:
        return [_jsonable(r) for r in conn.execute(" ".join(sql), params).fetchall()]


@server.tool()
def get_posting(posting_id: str) -> dict:
    """Full posting, including description text and any application recorded for it."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM postings WHERE id = %s", (posting_id,)).fetchone()
        if row is None:
            raise ValueError(f"no posting with id {posting_id}")
        app = conn.execute("SELECT * FROM applications WHERE posting_id = %s", (posting_id,)).fetchone()
    out = _jsonable(row)
    out["application"] = _jsonable(app) if app else None
    return out


@server.tool()
def record_application(posting_id: str, status: str, resume_path: str | None = None,
                       outcome: str | None = None, notes: str | None = None) -> dict:
    """Create or update the application for a posting.
    status: in_progress | captcha_wait | submitted | needs_manual | failed.
    outcome (optional): no_response | rejected | interview | offer.
    Setting captcha_wait starts the 30-minute CAPTCHA timer; submitted stamps submitted_at."""
    if status not in APPLICATION_STATUSES:
        raise ValueError(f"status must be one of {sorted(APPLICATION_STATUSES)}")
    if outcome is not None and outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOMES)}")
    with db.connect() as conn:
        posting = conn.execute("SELECT company FROM postings WHERE id = %s", (posting_id,)).fetchone()
        if posting is None:
            raise ValueError(f"no posting with id {posting_id}")
        row = conn.execute(
            """INSERT INTO applications (posting_id, company, resume_path, status, outcome, notes,
                                         captcha_started_at, submitted_at)
               VALUES (%(pid)s, %(company)s, %(resume)s, %(status)s, %(outcome)s, %(notes)s,
                       CASE WHEN %(status)s = 'captcha_wait' THEN now() END,
                       CASE WHEN %(status)s = 'submitted' THEN now() END)
               ON CONFLICT (posting_id) DO UPDATE SET
                 status = EXCLUDED.status,
                 resume_path = COALESCE(EXCLUDED.resume_path, applications.resume_path),
                 outcome = COALESCE(EXCLUDED.outcome, applications.outcome),
                 notes = COALESCE(EXCLUDED.notes, applications.notes),
                 captcha_started_at = CASE
                   WHEN EXCLUDED.status = 'captcha_wait' AND applications.status <> 'captcha_wait'
                   THEN now() ELSE applications.captcha_started_at END,
                 submitted_at = COALESCE(applications.submitted_at, EXCLUDED.submitted_at),
                 updated_at = now()
               RETURNING *""",
            {"pid": posting_id, "company": posting["company"], "resume": resume_path,
             "status": status, "outcome": outcome, "notes": notes},
        ).fetchone()
        conn.commit()
    return _jsonable(row)


@server.tool()
def report_captcha(posting_id: str, note: str | None = None) -> dict:
    """Call when a CAPTCHA blocks the application. Sets status captcha_wait (starting the
    30-minute timer) and pushes a Discord alert with the live-browser link so a human can solve it.
    Then wait, and check get_posting(...)['application']['status'] before continuing."""
    app = record_application(posting_id, "captcha_wait", notes=note)
    with db.connect() as conn:
        posting = conn.execute("SELECT company_display, title FROM postings WHERE id = %s",
                               (posting_id,)).fetchone()
    notify.captcha(posting, note)
    return app


@server.tool()
def ask_human(posting_id: str, message: str) -> str:
    """Push a Discord alert (with the live-browser link) when you need a decision: a form field
    not covered by get_standard_answers, an application ready for Submit approval, or anything
    unclear. Does not change application status."""
    with db.connect() as conn:
        p = conn.execute("SELECT company_display, title FROM postings WHERE id = %s", (posting_id,)).fetchone()
    if p is None:
        raise ValueError(f"no posting with id {posting_id}")
    live = os.environ.get("LIVE_BROWSER_URL", "")
    notify.alert(f":raising_hand: {p['company_display']} · {p['title']}: {message}\n{live}")
    return "sent"


@server.tool()
def list_applications(status: str | None = None, limit: int = 50) -> list[dict]:
    """Applications with their posting's company/title/url, newest first, optionally by status."""
    sql = """SELECT a.*, p.company_display, p.title, p.url FROM applications a
             JOIN postings p ON p.id = a.posting_id"""
    params: list = []
    if status:
        sql += " WHERE a.status = %s"
        params.append(status)
    sql += " ORDER BY a.updated_at DESC LIMIT %s"
    params.append(max(1, min(limit, 200)))
    with db.connect() as conn:
        return [_jsonable(r) for r in conn.execute(sql, params).fetchall()]


@server.tool()
def get_standard_answers() -> dict:
    """The ONLY allowed answers for work authorization, sponsorship, EEO, salary, start date and
    links. A null value means 'unknown': do not guess; mark the application needs_manual."""
    return yaml.safe_load(STANDARD_ANSWERS.read_text()) or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--http", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port)
    else:
        server.run()


if __name__ == "__main__":
    main()
