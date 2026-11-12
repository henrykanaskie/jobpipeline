"""Monthly threshold review: do higher fit scores actually lead to more interviews?

    python -m jobpipeline.report
"""
from . import db

BUCKETS = [(0, 50), (50, 75), (75, 85), (85, 101)]


def outcome_table(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT p.fit_score::float AS s, a.status, a.outcome
           FROM applications a JOIN postings p ON p.id = a.posting_id
           WHERE p.fit_score IS NOT NULL""").fetchall()
    out = []
    for lo, hi in BUCKETS:
        b = [r for r in rows if lo <= r["s"] < hi]
        submitted = [r for r in b if r["status"] == "submitted"]
        known = [r for r in submitted if r["outcome"]]
        positive = [r for r in known if r["outcome"] in ("interview", "offer")]
        out.append({"bucket": f"{lo}-{min(hi, 100)}", "applications": len(b), "submitted": len(submitted),
                    "with_outcome": len(known), "interview_or_offer": len(positive),
                    "rate": (len(positive) / len(known)) if known else None})
    return out


def main():
    with db.connect() as conn:
        table = outcome_table(conn)
        unknown = conn.execute(
            """SELECT count(*) AS n FROM applications WHERE status = 'submitted' AND outcome IS NULL
               AND submitted_at < now() - interval '30 days'""").fetchone()["n"]
    print(f"{'fit score':<10}{'apps':>6}{'submitted':>11}{'w/ outcome':>12}{'interview+':>12}{'rate':>8}")
    for r in table:
        rate = "–" if r["rate"] is None else f"{r['rate']:.0%}"
        print(f"{r['bucket']:<10}{r['applications']:>6}{r['submitted']:>11}{r['with_outcome']:>12}"
              f"{r['interview_or_offer']:>12}{rate:>8}")
    if unknown:
        print(f"\n{unknown} submitted 30+ days ago with no outcome: record them as no_response.")
    print("\nRule of thumb: don't move the threshold until each bucket has 20+ outcomes.")


if __name__ == "__main__":
    main()
