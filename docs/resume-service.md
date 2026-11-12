# Resume service contract

What the Screening service expects from your resume service. Screening is the client; your
service implements these three endpoints. Base URL comes from `RESUME_SERVICE_URL`; if
`RESUME_SERVICE_TOKEN` is set, every request carries `Authorization: Bearer <token>`.

## Job object (request body for `/score` and `/tailor`)

```json
{
  "job_id": "uuid string, stable; use it as your idempotency key",
  "company": "Stripe",
  "title": "Software Engineer, New Grad",
  "location": "Seattle, WA",
  "url": "https://boards.greenhouse.io/stripe/jobs/123",
  "posting_text": "full description; may be empty if it couldn't be fetched"
}
```

## `POST /score` (synchronous)

Response `200`:

```json
{ "fit_score": 82, "reasons": "one short paragraph, shown in the Discord match alert" }
```

- `fit_score` must be a number from 0 to 100. Anything else is treated as a refusal.
- Postings scoring at least `MATCH_THRESHOLD` (default 75) go to `/tailor`.
- Screening sends at most `SCORE_DAILY_LIMIT` (default 300) calls per 24 hours and at most 20 per minute. Your service should still enforce its own spend cap.

## `POST /tailor` (asynchronous: queue it and return)

Response `202` (or `200`) with any JSON body, e.g. `{"status": "queued"}`.

- Must be idempotent on `job_id`: Screening re-sends it if an earlier attempt got a network error or a 5xx.
- Do the work in the background. Usage-limit waits belong here, not in the request.

## `GET /tailor/{job_id}`

Response `200`:

```json
{ "status": "queued | running | done | failed",
  "resume_path": "resumes/2026-11/stripe-swe-new-grad.pdf",
  "summary": "what changed and why",
  "error": "only when failed" }
```

- `done` requires `resume_path`. A `done` without one is recorded as a failure.
- Screening polls every loop. A job still `queued`/`running` 24 hours after the request is marked `tailor_failed` with an alert.

## Status codes, and how Screening reacts

| Your response | Screening does |
| --- | --- |
| 2xx | uses the result |
| 429 or 5xx, timeout, connection refused | leaves the posting as is and retries next loop; alerts once if this lasts 30+ minutes |
| other 4xx | treats it as a refusal for that job: `/score` → `screened` with no score; `/tailor` → `tailor_failed` plus an alert |

Send `429` while you're waiting out a usage-limit reset; that is exactly what it's for.

## Rules the service must hold to (from the build plan)

- Every claim in a tailored resume traces back to `profile.md` or the base resume.
- It never fails silently: a job it can't finish ends as `failed` with an `error`.
