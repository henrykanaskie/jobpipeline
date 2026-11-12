"""Crawling Service: fetch every configured board, insert new postings, alert on breakage.

    python -m jobpipeline.crawler          # loop every CRAWL_INTERVAL seconds
    python -m jobpipeline.crawler --once   # single pass
"""
import argparse
import logging
import os
import time

from . import config, db, http, notify
from .sources import SOURCES

log = logging.getLogger("crawler")
PAUSE_BETWEEN_BOARDS = 1.0   # seconds; be polite to public APIs


def fetch_payload(sess, source_mod, board: dict):
    if hasattr(source_mod, "fetch"):
        return source_mod.fetch(sess, board)
    return http.get_json(sess, source_mod.url(board))


def crawl_board(conn, session, source_mod, board: dict) -> list[dict]:
    name, token = source_mod.NAME, board["token"]
    fetched, inserted, error = 0, [], None
    try:
        postings = source_mod.parse(fetch_payload(session, source_mod, board), board)
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
    session = http.session()
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
            notify.heartbeat("HEARTBEAT_URL_CRAWLER")
            if args.once:
                return
            time.sleep(max(0, interval - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
