"""Client for YOUR resume service. The contract is in docs/resume-service.md.

RESUME_SERVICE_URL   e.g. http://localhost:8800  (unset = scoring/tailoring stages are skipped)
RESUME_SERVICE_TOKEN optional bearer token
"""
import os
import time

import requests

# Outage tracking so Screening can alert once when the service has been down too long.
down_since: float | None = None
outage_alerted = False


class Unavailable(Exception):
    """Service down, rate-limited or busy: leave the posting where it is and retry next loop."""


class Rejected(Exception):
    """Service answered but refused this job (4xx other than 429): don't retry automatically."""


def configured() -> bool:
    return bool(os.environ.get("RESUME_SERVICE_URL"))


def _call(method: str, path: str, body: dict | None = None) -> dict:
    base = os.environ["RESUME_SERVICE_URL"].rstrip("/")
    headers = {}
    if token := os.environ.get("RESUME_SERVICE_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    global down_since, outage_alerted
    try:
        r = requests.request(method, base + path, json=body, headers=headers, timeout=120)
    except requests.RequestException as e:
        down_since = down_since or time.time()
        raise Unavailable(str(e)) from e
    if r.status_code == 429 or r.status_code >= 500:
        down_since = down_since or time.time()
        raise Unavailable(f"HTTP {r.status_code}: {r.text[:200]}")
    down_since, outage_alerted = None, False
    if r.status_code >= 400:
        raise Rejected(f"HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _job(p: dict) -> dict:
    return {"job_id": str(p["id"]), "company": p["company_display"], "title": p["title"],
            "location": p.get("location"), "url": p["url"], "posting_text": p.get("full_text") or ""}


def score(p: dict) -> tuple[float, str]:
    data = _call("POST", "/score", _job(p))
    s = float(data["fit_score"])
    if not 0 <= s <= 100:
        raise Rejected(f"fit_score out of range: {s}")
    return s, str(data.get("reasons") or "")


def request_tailoring(p: dict) -> None:
    _call("POST", "/tailor", _job(p))


def tailoring_status(job_id: str) -> dict:
    """-> {"status": "queued"|"running"|"done"|"failed", "resume_path", "summary", "error"}"""
    return _call("GET", f"/tailor/{job_id}")
