# jobpipeline

Job crawler → Postings DB → screening → MCP, per the build plan. This repo holds the
**mechanical** parts; the judgment-heavy parts are listed under *Not built yet*.

## What's here

| Piece | Command | Plan phase |
| --- | --- | --- |
| Postgres schema (`postings`, `applications`, `source_runs`) | `db/schema.sql`, applied on start | 1 |
| Crawler: Greenhouse, Lever, Ashby, Simplify; URL dedupe; zero-result/error alerts | `python -m jobpipeline.crawler [--once]` | 2, 3 (partial) |
| Screening (deterministic): applied-company skip, keyword pre-filter, 30-min CAPTCHA timeout | `python -m jobpipeline.screening [--once]` | 4 (partial), 8 (timeout) |
| Discord webhook: new jobs, source breakage/recovery, CAPTCHA timeouts | `jobpipeline/notify.py` | 4 (partial) |
| `data.json` export + static browse page + Vercel deploy script | `python -m jobpipeline.export`, `scripts/publish_web.sh` | 5 |
| MCP server: `search_jobs`, `get_posting`, `record_application` | `python -m jobpipeline.mcp_server [--http]` | 6 |
| Templates: `data/profile.md`, `data/standard_answers.yaml` | — | prerequisites |

Posting status flow: `new` → `skipped_applied` | `filtered_out` | `pending_score` → (`screened` → `tailored`, not built).

## Run it

```bash
cp .env.example .env        # set POSTGRES_PASSWORD, DISCORD_WEBHOOK_URL
docker compose up -d --build
docker compose logs -f crawler
```

Edit `config/sources.yaml` (boards) and `config/preferences.yaml` (pre-filter); both are
mounted read-only and picked up on the next loop.

**Reach it from the Mac over Tailscale** (ports bind to localhost on the host on purpose):

```bash
tailscale serve --bg --tcp 5432 tcp://localhost:5432
tailscale serve --bg --tcp 8765 tcp://localhost:8765
```

**Claude Code → MCP** (on the Mac): `claude mcp add --transport http jobs http://<host-tailscale-name>:8765/mcp`

**Web UI**: deploy `web/` as a Vercel project, put `VERCEL_TOKEN` in `.env`, cron `scripts/publish_web.sh` every 2 h.
Note the site is public by default; anyone with the URL sees your fit scores and application statuses.

## Tests

```bash
pip install -e '.[dev]'
pytest                                                   # unit tests
TEST_DATABASE_URL=postgresql://... pytest                # + DB integration tests (drops tables!)
```

## Not built yet (needs real design work)

- **LLM fit scoring** (`pending_score` → `screened`): prompt, model choice, daily spend cap, and the 50-job hand check.
- **Full-text fetch for Simplify** postings (they link out to Workday/iCIMS/etc.; no description in the feed).
- **Workday and Hacker News** sources: Workday's endpoints are unofficial and per-tenant; HN "Who's hiring" is free text that needs parsing.
- **Cross-source dedupe**: URL dedupe only catches the same link. The same job on Greenhouse and Simplify with different URLs is stored twice.
- **Tailoring integration**, **live browser + Codex**, **Discord bot** (two-way; the webhook here is one-way), **outcome review**.
