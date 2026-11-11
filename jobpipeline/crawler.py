"""Crawling Service: fetch every configured board, insert new postings, alert on breakage.

    python -m jobpipeline.crawler          # loop every CRAWL_INTERVAL seconds
    python -m jobpipeline.crawler --once   # single pass
"""
import argparse
import logging
import os
import time

import requests

from . import config, db, notify
from .sources import SOURCES

log = logging.getLogger("crawler")
USER_AGENT = "jobpipeline-crawler/0.1 (personal job search)"
PAUSE_BETWEEN_BOARDS = 1.0   # seconds; be polite to public APIs


def fetch_json(session: requests.Session, url: str, attempts: int = 4):
    """GET with exponential backoff on 429/5xx and network errors."""
    for i in range(attempts):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError) as e:
            retryable = not isinstance(e, requests.HTTPError) or (
                e.response is not None and (e.response.status_code == 429 or e.response.status_code >= 500))
            if not retryable or i == attempts - 1:
                raise
            time.sleep(2 ** (i + 1))


def crawl_board(conn, session, source_mod, board: dict) -> list[dict]:
    name, token = source_mod.NAME, board["token"]
    fetched, inserted, error = 0, [], None
    try:
        postings = source_mod.parse(fetch_json(session, source_mod.url(board)), board)
        fetched = len(postings)
        inserted = db.insert_postings(conn, postings)
    except Exception as e:   # one broken board must not stop the rest
        conn.rollback()
        error = f"{type(e).__name__}: {e}"[:500]
        log.exception("%s/%s failed", name, token)

    db.record_run(conn, name, token, fetched, len(inserted), error)
    healthy = error is None and fetched > 0
    was_healthy = db.previous_run_healthy(conn, name, token)
    if not healthy and was_healthy is not False:      # first failure, or broken from the start
        notify.alert(f"{name}/{token}: {error or 'returned zero postings'}")
    elif healthy and was_healthy is False:
        notify.alert(f"{name}/{token} recovered ({fetched} postings).")
    log.info("%s/%s fetched=%d new=%d%s", name, token, fetched, len(inserted),
             f" error={error}" if error else "")
    return inserted


def crawl_once(conn) -> int:
    boards = config.load("sources.yaml")
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    new_rows = []
    for source_name, board_list in boards.items():
        mod = SOURCES.get(source_name)
        if mod is None:
            log.warning("unknown source %r in sources.yaml; skipping", source_name)
            continue
        for board in board_list or []:
            new_rows += crawl_board(conn, session, mod, board)
            time.sleep(PAUSE_BETWEEN_BOARDS)
    notify.new_jobs(new_rows)
    return len(new_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    interval = int(os.environ.get("CRAWL_INTERVAL", "900"))
    with db.connect() as conn:
        db.migrate(conn)
        while True:
            started = time.monotonic()
            log.info("crawl done: %d new postings", crawl_once(conn))
            if args.once:
                return
            time.sleep(max(0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
