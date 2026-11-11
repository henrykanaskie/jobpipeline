-- Postings DB: single source of truth. Idempotent; safe to run on every start.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS postings (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source         text NOT NULL,                -- workday, greenhouse, lever, ashby, simplify, ...
    company        text NOT NULL,                -- normalized; used for the applied filter
    company_display text NOT NULL,               -- as shown by the source
    title          text NOT NULL,
    location       text,
    url            text NOT NULL UNIQUE,         -- normalized; dedupe key
    full_text      text,
    fit_score      numeric CHECK (fit_score BETWEEN 0 AND 100),
    first_seen_at  timestamptz NOT NULL DEFAULT now(),
    status         text NOT NULL DEFAULT 'new' CHECK (status IN (
                     'new',             -- just crawled
                     'skipped_applied', -- company already in applications
                     'filtered_out',    -- failed keyword pre-filter
                     'pending_score',   -- passed pre-filter, waiting for the LLM scorer
                     'screened',        -- scored
                     'tailored'))       -- tailored resume produced
);
CREATE INDEX IF NOT EXISTS postings_status_idx  ON postings (status);
CREATE INDEX IF NOT EXISTS postings_company_idx ON postings (company);
CREATE INDEX IF NOT EXISTS postings_seen_idx    ON postings (first_seen_at DESC);

CREATE TABLE IF NOT EXISTS applications (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    posting_id         uuid NOT NULL UNIQUE REFERENCES postings(id),
    company            text NOT NULL,             -- normalized; Screening skips matches
    resume_path        text,
    status             text NOT NULL DEFAULT 'in_progress' CHECK (status IN (
                         'in_progress', 'captcha_wait', 'submitted', 'needs_manual', 'failed')),
    captcha_started_at timestamptz,
    submitted_at       timestamptz,
    outcome            text CHECK (outcome IN ('no_response', 'rejected', 'interview', 'offer')),
    notes              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS applications_company_idx ON applications (company);

-- One row per board per crawl; drives "alert on zero results, don't fail silently".
CREATE TABLE IF NOT EXISTS source_runs (
    id        bigserial PRIMARY KEY,
    source    text NOT NULL,
    board     text NOT NULL,
    ran_at    timestamptz NOT NULL DEFAULT now(),
    fetched   integer NOT NULL,
    inserted  integer NOT NULL,
    error     text
);
CREATE INDEX IF NOT EXISTS source_runs_board_idx ON source_runs (source, board, ran_at DESC);
