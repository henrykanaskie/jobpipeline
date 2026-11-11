import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

SCHEMA = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or os.environ["DATABASE_URL"], row_factory=dict_row)


def migrate(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA.read_text())
    conn.commit()


def insert_postings(conn: psycopg.Connection, postings: list[dict]) -> list[dict]:
    """Insert postings, skipping URLs already present. Returns the rows actually inserted."""
    inserted = []
    with conn.cursor() as cur:
        for p in postings:
            cur.execute(
                """INSERT INTO postings (source, company, company_display, title, location, url, full_text)
                   VALUES (%(source)s, %(company)s, %(company_display)s, %(title)s, %(location)s,
                           %(url)s, %(full_text)s)
                   ON CONFLICT (url) DO NOTHING
                   RETURNING id, source, company_display, title, location, url""",
                p,
            )
            row = cur.fetchone()
            if row:
                inserted.append(row)
    conn.commit()
    return inserted


def record_run(conn, source: str, board: str, fetched: int, inserted: int, error: str | None):
    conn.execute(
        "INSERT INTO source_runs (source, board, fetched, inserted, error) VALUES (%s, %s, %s, %s, %s)",
        (source, board, fetched, inserted, error),
    )
    conn.commit()


def previous_run_healthy(conn, source: str, board: str) -> bool | None:
    """Health of the run before the latest one; None if there was no earlier run."""
    row = conn.execute(
        """SELECT fetched, error FROM source_runs WHERE source = %s AND board = %s
           ORDER BY ran_at DESC, id DESC OFFSET 1 LIMIT 1""",
        (source, board),
    ).fetchone()
    if row is None:
        return None
    return row["error"] is None and row["fetched"] > 0
