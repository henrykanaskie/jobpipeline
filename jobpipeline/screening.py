"""Screening Service.

Every SCREEN_INTERVAL seconds:
  0. applications in captcha_wait for 30+ min           -> needs_manual
  1. postings from companies already in `applications` -> skipped_applied
  2. postings failing the keyword pre-filter            -> filtered_out
  3. the rest                                           -> pending_score
  4. fetch descriptions missing from the source feed
  5. ask the resume service for a fit score             -> screened, or tailoring if >= threshold
  6. poll the resume service for finished tailoring     -> tailored / tailor_failed

Stages 5-6 run only when RESUME_SERVICE_URL is set. If the service is down or rate-limited,
postings stay where they are and are retried on the next loop.
"""
import argparse
import logging
import os
import time

from . import config, db, fulltext, notify, prefilter, resume_client

log = logging.getLogger("screening")


def skip_applied(conn) -> int:
    cur = conn.execute(
        """UPDATE postings p SET status = 'skipped_applied'
           WHERE p.status IN ('new', 'pending_score')
             AND EXISTS (SELECT 1 FROM applications a WHERE a.company = p.company)""")
    conn.commit()
    return cur.rowcount


def apply_prefilter(conn, prefs: dict) -> tuple[int, int]:
    rows = conn.execute("SELECT id, title, location FROM postings WHERE status = 'new'").fetchall()
    keep, drop = [], []
    for r in rows:
        (keep if prefilter.passes(r["title"], r["location"], prefs) else drop).append(r["id"])
    with conn.cursor() as cur:
        cur.execute("UPDATE postings SET status = 'pending_score' WHERE id = ANY(%s)", (keep,))
        cur.execute("UPDATE postings SET status = 'filtered_out' WHERE id = ANY(%s)", (drop,))
    conn.commit()
    return len(keep), len(drop)


CAPTCHA_TIMEOUT_MINUTES = 30


def expire_captchas(conn) -> int:
    """Applications stuck on a CAPTCHA for 30+ min are handed back to you."""
    cur = conn.execute(
        """UPDATE applications SET status = 'needs_manual', updated_at = now()
           WHERE status = 'captcha_wait'
             AND captcha_started_at < now() - make_interval(mins => %s)""",
        (CAPTCHA_TIMEOUT_MINUTES,))
    conn.commit()
    return cur.rowcount


MATCH_THRESHOLD = float(os.environ.get("MATCH_THRESHOLD", "75"))
SCORE_DAILY_LIMIT = int(os.environ.get("SCORE_DAILY_LIMIT", "300"))
TAILOR_TIMEOUT_HOURS = 24
BATCH = 20
OUTAGE_ALERT_SECONDS = 30 * 60


def _score_calls_today(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM score_calls WHERE called_at > now() - interval '24 hours'"
                        ).fetchone()["n"]


def score_pending(conn) -> int:
    budget = min(BATCH, SCORE_DAILY_LIMIT - _score_calls_today(conn))
    if budget <= 0:
        return 0
    rows = conn.execute(
        """SELECT * FROM postings WHERE status = 'pending_score'
             AND (full_text IS NOT NULL OR fulltext_attempts >= %s)
           ORDER BY first_seen_at LIMIT %s""", (fulltext.MAX_ATTEMPTS, budget)).fetchall()
    done = 0
    for p in rows:
        conn.execute("INSERT INTO score_calls DEFAULT VALUES")
        conn.commit()
        try:
            score, reasons = resume_client.score(p)
        except resume_client.Unavailable as e:
            log.warning("resume service unavailable for /score, retrying next loop: %s", e)
            break
        except resume_client.Rejected as e:
            conn.execute("UPDATE postings SET status = 'screened', fit_reasons = %s, scored_at = now() "
                         "WHERE id = %s", (f"score rejected: {e}", p["id"]))
            conn.commit()
            continue
        p = {**p, "fit_score": score, "fit_reasons": reasons}
        is_match = score >= MATCH_THRESHOLD
        conn.execute(
            """UPDATE postings SET fit_score = %s, fit_reasons = %s, scored_at = now(), status = %s,
                   tailor_requested_at = NULL
               WHERE id = %s""",
            (score, reasons, "tailoring" if is_match else "screened", p["id"]))
        conn.commit()
        if is_match:
            notify.match(p)
            send_tailor_request(conn, p)
        done += 1
    return done


def send_tailor_request(conn, p: dict) -> bool:
    """Ask the resume service to tailor. On failure tailor_requested_at stays NULL and
    poll_tailoring re-sends it next loop (the score is kept; no second /score call)."""
    try:
        resume_client.request_tailoring(p)
    except resume_client.Unavailable as e:
        log.warning("tailor request failed, will retry: %s", e)
        return False
    except resume_client.Rejected as e:
        conn.execute("UPDATE postings SET status = 'tailor_failed', tailor_error = %s WHERE id = %s",
                     (str(e), p["id"]))
        conn.commit()
        notify.alert(f"Resume service refused to tailor {p['company_display']} · {p['title']}: {e}")
        return False
    conn.execute("UPDATE postings SET tailor_requested_at = now() WHERE id = %s", (p["id"],))
    conn.commit()
    return True


def poll_tailoring(conn) -> int:
    for p in conn.execute("SELECT * FROM postings WHERE status = 'tailoring' AND tailor_requested_at IS NULL "
                          "LIMIT %s", (BATCH,)).fetchall():
        if not send_tailor_request(conn, p) and resume_client.configured():
            break
    rows = conn.execute("SELECT * FROM postings WHERE status = 'tailoring' AND tailor_requested_at IS NOT NULL "
                        "ORDER BY tailor_requested_at LIMIT %s", (BATCH,)).fetchall()
    finished = 0
    for p in rows:
        try:
            st = resume_client.tailoring_status(str(p["id"]))
        except resume_client.Unavailable as e:
            log.warning("resume service unavailable for status, retrying next loop: %s", e)
            break
        except resume_client.Rejected as e:
            st = {"status": "failed", "error": str(e)}
        state = st.get("status")
        if state == "done" and st.get("resume_path"):
            conn.execute("UPDATE postings SET status = 'tailored', resume_path = %s, tailor_summary = %s "
                         "WHERE id = %s", (st["resume_path"], st.get("summary"), p["id"]))
            notify.alert(f"Tailored resume ready: {p['company_display']} · {p['title']} -> {st['resume_path']}")
        elif state == "failed" or (state == "done" and not st.get("resume_path")):
            err = st.get("error") or "service reported done without resume_path"
            conn.execute("UPDATE postings SET status = 'tailor_failed', tailor_error = %s WHERE id = %s",
                         (err, p["id"]))
            notify.alert(f"Tailoring failed for {p['company_display']} · {p['title']}: {err}")
        else:
            continue
        conn.commit()
        finished += 1
    # Never fail silently: anything stuck for a day is surfaced.
    stuck = conn.execute(
        """UPDATE postings SET status = 'tailor_failed', tailor_error = 'timed out waiting for resume service'
           WHERE status = 'tailoring' AND tailor_requested_at < now() - make_interval(hours => %s)
           RETURNING company_display, title""", (TAILOR_TIMEOUT_HOURS,)).fetchall()
    conn.commit()
    for p in stuck:
        notify.alert(f"Tailoring timed out after {TAILOR_TIMEOUT_HOURS}h: {p['company_display']} · {p['title']}")
    return finished + len(stuck)


def screen_once(conn) -> dict:
    expired = expire_captchas(conn)
    if expired:
        notify.alert(f"{expired} application(s) timed out on CAPTCHA -> needs_manual")
    skipped = skip_applied(conn)
    kept, dropped = apply_prefilter(conn, config.load("preferences.yaml"))
    stats = {"captcha_expired": expired, "skipped_applied": skipped, "pending_score": kept,
             "filtered_out": dropped, "fulltext_fetched": fulltext.fill_missing(conn)}
    if resume_client.configured():
        stats["scored"] = score_pending(conn)
        stats["tailoring_finished"] = poll_tailoring(conn)
        rc = resume_client
        if rc.down_since and not rc.outage_alerted and time.time() - rc.down_since > OUTAGE_ALERT_SECONDS:
            notify.alert("Resume service unreachable or rate-limited for 30+ min; scoring and tailoring are paused.")
            rc.outage_alerted = True
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    interval = int(os.environ.get("SCREEN_INTERVAL", "60"))
    with db.connect() as conn:
        db.migrate(conn)
        while True:
            stats = screen_once(conn)
            notify.heartbeat("HEARTBEAT_URL_SCREENING")
            if any(stats.values()):
                log.info("screened: %s", stats)
            if args.once:
                return
            time.sleep(interval)


if __name__ == "__main__":
    main()
