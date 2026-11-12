# What's left

Ordered roughly by when it blocks you. ⚠ marks things only you can decide or do.

## 1. Resume service (yours)

- [ ] Implement `POST /score`, `POST /tailor`, `GET /tailor/{job_id}` per `docs/resume-service.md`
- [ ] Scoring prompt and model choice; give `/score` its own cheap model and queue, separate from tailoring
- [ ] Spend cap inside the service (Screening also caps at `SCORE_DAILY_LIMIT` calls/day)
- [ ] Return `429` while waiting out usage limits; make `/tailor` idempotent on `job_id`
- [ ] "No invented claims" check: every resume claim traces to `profile.md` or the base resume
- [ ] ⚠ Unattended use: check your Claude plan's terms; use an API key for the 24/7 parts
- [ ] Where tailored resumes are written (`resume_path`) and how they reach the repo
- [ ] Set `RESUME_SERVICE_URL` (and token) in `.env`

## 2. Accounts and host setup

- [ ] ⚠ Host decision (Linux mini PC vs Mac mini); Docker installed, sleep disabled, starts on boot
- [ ] Tailscale on host, Mac, iPhone; run the `tailscale serve` lines from the README
- [ ] Discord private server with two channels (feed, alerts) and a webhook for each; phone notifications on for alerts
- [ ] healthchecks.io (or similar) checks for crawler and screening; put the ping URLs in `.env`
- [ ] Vercel project for `web/`, `VERCEL_TOKEN` in `.env`, cron for `scripts/publish_web.sh`
- [ ] Dedicated application email; agent-only password-manager vault for ATS logins
- [ ] ⚠ Plan for Workday's one-account-per-company sign-ups
- [ ] Make the GitHub repo private (it holds personal data)

## 3. Content only you can write

- [ ] `data/profile.md`: education, experience, projects, skills, "never claim" list
- [ ] Base resume
- [ ] `data/standard_answers.yaml`: every `null` filled or deliberately left unknown
- [ ] `config/preferences.yaml`: real title/location keywords. The example rejects ~96% of Simplify postings; look at 20–30 `filtered_out` rows before trusting it
- [ ] `config/sources.yaml`: the companies you actually want; check each board returns jobs

## 4. First-run verification (couldn't be tested from the build sandbox)

- [ ] `docker compose run --rm crawler python -m jobpipeline.crawler --once`: every board shows `fetched > 0`. Greenhouse, Lever, Ashby, Workday and HN parsers were only tested on sample responses
- [ ] `docker compose build browser` and open noVNC from your phone; check Codex can connect over CDP (use the host's Tailscale IP, not its name)
- [ ] Run a week of crawls: no duplicates, no crashes (phase 2 "done when")
- [ ] Restore a backup once into a scratch database, so you know the backups work

## 5. Decisions still open (from the build plan)

- [ ] ⚠ Submit step: `AGENTS.md` currently makes Codex stop before Submit and ask. Change it there if you decide otherwise
- [ ] ⚠ CAPTCHA concurrency: one browser now; parallel applications need more `browser` containers
- [ ] ⚠ Workday scope: full auto-apply vs pre-filled drafts
- [ ] ⚠ Web UI: is the 2-hour snapshot enough?
- [ ] ⚠ Check each ATS's terms on automated applications

## 6. Ongoing

- [ ] Hand-check 50 scored jobs against the 75% cut (phase 4 "done when")
- [ ] Record `outcome` for every submitted application (`record_application(..., outcome=...)`)
- [ ] Monthly `python -m jobpipeline.report`; don't move the threshold until each bucket has 20+ outcomes

## Known limitations (acceptable for now)

- Cross-source dedupe matches on company + exact normalized title; a retitled duplicate gets through
- Descriptions for JavaScript-only pages (e.g. Ashby links from Simplify) can't be fetched; those postings are scored on title and company only
- Hacker News parsing assumes `Company | Role | Location` on the first line; unusual formats are skipped or misread
- Workday reads at most 200 postings per board per crawl, so set a `search` term
