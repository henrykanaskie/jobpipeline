# jobpipeline

Job crawler → Postings DB → screening → your resume service → Codex in a live browser.
This repo holds everything except the resume service (scoring + tailoring), which is yours;
its contract is in [`docs/resume-service.md`](docs/resume-service.md). What's left to do is in
[`docs/TODO.md`](docs/TODO.md).

## Services (`docker compose up -d --build`)

| Service | What it does |
| --- | --- |
| `postgres` | Postings DB. Schema in `db/schema.sql`, applied/upgraded automatically on start |
| `crawler` | Every 15 min: reads [carpet-crawler](https://crawler.carsonsecrest.me/)'s `data.json` (~4,300 ATS boards plus Simplify, newgrad-jobs.com and Hacker News) → `postings`. Optional direct crawls of Greenhouse, Lever, Ashby, Workday, Simplify and HN for companies it misses. URL dedupe + cross-source dedupe (same company + title from another source within 45 days). Alerts when a source breaks, recovers, or the feed goes stale |
| `screening` | Every 60 s: CAPTCHA timeout → applied-company skip → keyword pre-filter → fetch missing descriptions → `/score` → `/tailor` for matches → poll until tailored |
| `mcp` | MCP server for Claude Code and Codex (tools below) |
| `browser` | Chromium + noVNC. You watch/solve CAPTCHAs from your phone; Codex drives it over CDP |
| `backup` | Nightly `pg_dump` to `./backups`, keeps 14 days |

Posting status flow:

```
new ─┬─> skipped_applied
     ├─> filtered_out
     └─> pending_score ─┬─> screened                  (score < MATCH_THRESHOLD)
                        └─> tailoring ─┬─> tailored    (resume_path set)
                                       └─> tailor_failed
```

MCP tools: `search_jobs`, `get_posting`, `record_application`, `report_captcha`, `ask_human`,
`list_applications`, `get_standard_answers`.

Notifications (Discord webhooks): new postings go to the feed channel; matches, CAPTCHAs, tailored resumes,
source breakage and resume-service outages go to the alert channel.

## Setup

```bash
cp .env.example .env          # fill it in; comments explain each value
docker compose up -d --build
docker compose logs -f crawler screening
```

Expose to your tailnet (all ports bind to localhost on the host):

```bash
tailscale serve --bg --tcp 8765 tcp://localhost:8765
tailscale serve --bg --https 6080 http://localhost:6080
tailscale serve --bg --tcp 9222 tcp://localhost:9222
```

- Claude Code (Mac): `claude mcp add --transport http jobs http://<host>:8765/mcp`
- Codex: same MCP URL, plus a Playwright/CDP connection to `http://<host tailscale IP>:9222`; runbook in [`AGENTS.md`](AGENTS.md)
- Phone: open `LIVE_BROWSER_URL` and log in with `VNC_PASSWORD`
- Web UI: `scripts/publish_web.sh` every 2 h from cron (see the script header)
- Threshold review: `python -m jobpipeline.report` monthly

Config files are mounted read-only and re-read on every loop: `config/sources.yaml` (boards),
`config/preferences.yaml` (pre-filter).

## Tests

```bash
pip install -e '.[dev]'
TEST_DATABASE_URL=postgresql://... pytest      # DB tests drop and recreate tables in that database
```

CI runs the same against Postgres 16 on every push (`.github/workflows/test.yml`).

## Security notes

- CDP on port 9222 gives full control of the browser and every account logged into it. Keep it on Tailscale only.
- The repo holds `data/standard_answers.yaml` and `data/profile.md`: keep it private.
- The Vercel site is public by default and shows fit scores and application statuses.
