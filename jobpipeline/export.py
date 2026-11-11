"""Write web/data.json: the browse-only snapshot the Vercel site serves.

    python -m jobpipeline.export [--out web/data.json] [--days 30]
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from . import db

DEFAULT_OUT = Path(__file__).resolve().parent.parent / "web" / "data.json"


def snapshot(conn, days: int) -> dict:
    rows = conn.execute(
        """SELECT p.id::text, p.source, p.company_display AS company, p.title, p.location, p.url,
                  p.fit_score::float AS fit_score, p.status, p.first_seen_at,
                  a.status AS application_status
           FROM postings p LEFT JOIN applications a ON a.posting_id = p.id
           WHERE p.first_seen_at > now() - make_interval(days => %s)
             AND p.status NOT IN ('filtered_out')
           ORDER BY p.fit_score DESC NULLS LAST, p.first_seen_at DESC""",
        (days,),
    ).fetchall()
    for r in rows:
        r["first_seen_at"] = r["first_seen_at"].isoformat()
    return {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(rows), "postings": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    with db.connect() as conn:
        data = snapshot(conn, args.days)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(args.out)   # atomic: the site never sees a half-written file
    print(f"wrote {data['count']} postings to {args.out}")


if __name__ == "__main__":
    main()
