# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal terminal tool that polls LinkedIn's public job-search page and companies' own career sites for new intern/co-op postings and fires a macOS notification (with a link) the moment one matches. No auto-submission, no drafting — it only watches and notifies. The entrypoint is `run_pipeline.py --watch` (or `--watch-linkedin` / `--watch-companies` for one side only).

## Commands

```bash
# Poll LinkedIn + company career sites and send a macOS notification (with a link) on each new match
python run_pipeline.py --watch
python run_pipeline.py --watch-linkedin              # LinkedIn only
python run_pipeline.py --watch-companies             # company career sites only (COMPANY_BOARDS)
python run_pipeline.py --watch-linkedin --keywords "Software Engineer Intern" --location Canada --interval 300
python run_pipeline.py --watch --once                # single pass, for cron/launchd

pytest                                               # run tests
```

## Architecture

```
run_pipeline.py  ←── CLI entrypoint; cmd_watch() loops (or, with --once, runs a
      │              single pass) calling run_pipeline(source="linkedin", ...) and
      │              run_pipeline(source="company", name, url) per COMPANY_BOARDS
      │              entry (each isolated so one broken board doesn't block the
      │              rest), then queries for postings with status="new" and
      │              notified_at IS NULL and fires a notification for each,
      │              marking notified_at so it isn't repeated.
      │              Only genuinely new postings notify: the first successful
      │              poll of a company marks everything already on its site as
      │              notified without alerting, and postings whose posted_at is
      │              older than NEW_POSTING_MAX_AGE (3 days) are marked silently.
      ▼
app/pipeline.py  ←── orchestrates ingest → filter
      │
      ├── app/ingestion/fetcher.py   fetch_and_store(source="linkedin", db, **kwargs)
      │     Fetches LinkedIn's public guest job-search endpoint (no login),
      │     HTML parsed with BeautifulSoup. Dedupes by URL. Stores posted_at
      │     from the posting's <time> element.
      │     Polled with a 24h f_TPR window, paging through every result
      │     (the guest endpoint returns 10 per page in relevance order and
      │     ignores sortBy), so missed polls during sleep and late-indexed
      │     postings are still caught; re-fetches are deduped out by URL.
      │
      ├── app/ingestion/company_boards.py   fetch_company_board(name, url)
      │     Detects the ATS from the careers URL (Greenhouse, Lever incl. EU,
      │     Ashby, Workday) and hits its public JSON API. Greenhouse/Lever/
      │     Ashby return the whole board; Workday is searched for intern/co-op/
      │     student terms since boards are large and paginated.
      │     Any other URL is fetched: a SuccessFactors site (detected by its
      │     rmkcdn.successfactors.com assets) is searched via /search/ HTML;
      │     otherwise the page is a hand-made list and each link to an ATS
      │     host is a posting titled "<nearest heading> — <page h1>".
      │     Posting.source is the ATS name, "successfactors", or "page".
      │
      └── app/filtering/filter.py    is_relevant(title, description)
            Three required checks (all must pass):
            1. _keyword_match   — target role keywords (ML/AI, full-stack, SaaS, etc.),
                                  or a broad tech term (engineer, IT, data, technology…)
                                  in the title that isn't another engineering discipline
            2. _intern_match    — title must say intern/co-op/student/PEY (or French
                                  equivalents), or name a term + length ("Winter
                                  2027 … (8 months)"); senior titles are rejected
            3. _location_ok     — remote OK anywhere; onsite/hybrid must be in Canada.
                                  Non-LinkedIn sources use strict=True: must be
                                  remote or Canada (career sites list jobs
                                  worldwide as bare city names).

app/notify/notifier.py
  notify(title, subtitle, message, url) shells out to `osascript` to show a
  native `display alert` dialog with an "Open" button (click opens the job
  URL). Values are always passed as separate argv entries, never interpolated
  into a shell or AppleScript string, since posting titles/companies are
  untrusted scraped text.
```

## Data model

Single table `postings` in `pipeline.db` (SQLite):

| Column | Notes |
|---|---|
| `url` | Primary key / dedup key |
| `title`, `company`, `description`, `source` | Raw from fetcher (`source` is `"linkedin"`, the ATS name `greenhouse`/`lever`/`ashby`/`workday`/`successfactors`, or `"page"` for hand-made careers pages) |
| `posted_at` | When the job was originally posted (nullable) |
| `fetched_at` | When we stored it |
| `status` | `new` (passed the filter) or `rejected` (set by `is_relevant`) |
| `notified_at` | Set once a notification has fired for this posting, or once it was suppressed as pre-existing (first poll of a company, or older than 3 days) — NULL until then |

SQLAlchemy does not auto-migrate. Add columns manually with `ALTER TABLE` when the schema changes.

## Key files

- `app/config.py` — `Settings` via pydantic-settings; `target_keywords` controls the software + AI/ML keyword filter (word-boundary matched), `linkedin_keywords`/`linkedin_location` control the default search, `company_boards` maps company name → careers-board URL. Override via `.env` (`COMPANY_BOARDS` as JSON).
- `run_pipeline.py` — all CLI logic.

## Running unattended

A `launchd` agent (`~/Library/LaunchAgents/com.ivanxie.linkedin-watch.plist`, outside this repo) runs `run_pipeline.py --watch-linkedin --once` from this project's directory every 5 minutes, so notifications keep arriving without a terminal open.
