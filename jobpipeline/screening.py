"""Screening Service — deterministic stages only.

Every SCREEN_INTERVAL seconds:
  0. applications in captcha_wait for 30+ min           -> needs_manual
  1. postings from companies already in `applications` -> skipped_applied
  2. postings failing the keyword pre-filter            -> filtered_out
  3. the rest                                           -> pending_score

The LLM fit-score stage (pending_score -> screened, with fit_score) is intentionally NOT
implemented here yet; see README "Not built yet".
"""
import argparse
import logging
import os
import time

from . import config, db, notify, prefilter

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


def screen_once(conn) -> dict:
    expired = expire_captchas(conn)
    if expired:
        notify.alert(f"{expired} application(s) timed out on CAPTCHA -> needs_manual")
    skipped = skip_applied(conn)
    kept, dropped = apply_prefilter(conn, config.load("preferences.yaml"))
    return {"captcha_expired": expired, "skipped_applied": skipped, "pending_score": kept, "filtered_out": dropped}


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
            if any(stats.values()):
                log.info("screened: %s", stats)
            if args.once:
                return
            time.sleep(interval)


if __name__ == "__main__":
    main()
