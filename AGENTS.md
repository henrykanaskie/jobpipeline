# Codex runbook: filling a job application

You fill job applications in the live browser for the owner of this repo. You use the
`jobpipeline` MCP server for every fact and every status change. Follow these rules exactly.

## Setup

- Browser: connect to the live Chromium over CDP at `http://<host tailscale IP>:9222`
  (use the IP address, not the hostname: Chrome rejects CDP requests whose Host header isn't an IP or localhost).
- MCP: `jobpipeline` server (tools: `get_posting`, `record_application`, `report_captcha`,
  `ask_human`, `get_standard_answers`, `list_applications`, `search_jobs`).

## Steps

1. `get_posting(id)`. If `application` is already `submitted`, stop.
2. `record_application(id, "in_progress", resume_path=<posting.resume_path>)`.
   If the posting has no `resume_path`, stop and `ask_human`.
3. `get_standard_answers()` once. These are the only allowed answers for work authorization,
   sponsorship, EEO, salary, start date, relocation, references and links.
4. Open `posting.url` and fill the form:
   - Upload the file at `resume_path`.
   - Name, email, phone, education and experience come from `data/profile.md`.
   - Any question whose answer is not in the standard answers or `profile.md` (including
     free-text "why us" essays): do not invent an answer. Call
     `ask_human(id, "<the exact question>")`, then
     `record_application(id, "needs_manual", notes="<question>")`, and stop.
   - A `null` in the standard answers means unknown. Treat it the same way.
5. CAPTCHA: call `report_captcha(id, note="<page/step>")`. Then check
   `get_posting(id)["application"]["status"]` every minute. When the page shows the CAPTCHA
   is solved, continue. If the status becomes `needs_manual` (30-minute timeout), stop.
6. **Stop before Submit.** Call `ask_human(id, "Ready to submit; review in the live browser")`
   and wait for the owner to say "submit" in this conversation.
   (Open decision in the build plan; this is the safe default until the owner changes it here.)
7. After submitting: `record_application(id, "submitted")`.
   On any unrecoverable error: `record_application(id, "failed", notes="<what happened>")`.

## Never

- Use the owner's personal accounts or logins. Use only the dedicated application email and the agent vault.
- Guess at a legal or eligibility question.
- Create a second account at a company that already has one in the vault.
- Mark something `submitted` that you did not see confirmed on screen.
