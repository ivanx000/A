# Job Watch Notifier

A personal terminal tool that polls LinkedIn's public job search and companies' own career sites for new intern/co-op postings and sends a macOS notification with a link to each one, the moment it appears.

## What it does

- Polls LinkedIn's public guest job-search page (no login) for postings matching a keyword search (default: "Software Engineer Intern")
- Polls company career sites directly (Greenhouse, Lever, Ashby, Workday, and SuccessFactors sites, plus hand-made pages that link to them), since not every role gets posted to LinkedIn
- Filters to intern/co-op/student roles in software + AI/ML, remote anywhere or onsite/hybrid in Canada
- Dedupes by URL and only notifies once per posting, tracked in a local SQLite DB
- Fires a native macOS alert (click "Open" to jump straight to the job) when a new match is found

## Setup

**Prerequisites:** Python 3.10+

```bash
pip install -r requirements.txt
```

## Usage

```bash
# Watch LinkedIn + company career sites and get a macOS notification (with a link) on each new match
python run_pipeline.py --watch

# Just one side
python run_pipeline.py --watch-linkedin
python run_pipeline.py --watch-companies

# Override the default keyword/location search
python run_pipeline.py --watch-linkedin --keywords "Software Engineer Intern" --location Canada

# Poll on a custom interval (default: every 5 minutes)
python run_pipeline.py --watch-linkedin --interval 300

# Single check-and-notify pass, e.g. for cron/launchd instead of a long-running loop
python run_pipeline.py --watch --once
```

`--watch-linkedin` polls LinkedIn's public job-search page for postings matching `--keywords`/`--location` (or `LINKEDIN_KEYWORDS`/`LINKEDIN_LOCATION` in `.env`), stores new ones after running them through the relevance filter (`is_relevant` in `app/filtering/filter.py`), and fires a notification for each one it hasn't notified about yet.

### Adding a company

Add the company's careers-board URL to `COMPANY_BOARDS` in `.env` (or `company_boards` in `app/config.py`):

```
COMPANY_BOARDS={"Cohere": "https://jobs.ashbyhq.com/cohere", "Ada": "https://job-boards.greenhouse.io/ada18", "RBC": "https://rbc.wd3.myworkdayjobs.com/en-US/RBCGLOBAL1"}
```

Supported URLs:

- **ATS boards** (polled via their JSON APIs): `job-boards.greenhouse.io/<token>`, `jobs[.eu].lever.co/<company>`, `jobs.ashbyhq.com/<name>`, `<tenant>.wd<N>.myworkdayjobs.com/<site>`. Many companies' careers pages (e.g. `stripe.com/jobs`) are a skin over one of these — click into a job and the apply link usually reveals the underlying board, which is more reliable to poll than the skin.
- **SuccessFactors career sites** on the company's own domain (e.g. `careers.celestica.com`) — detected automatically.
- **Hand-made pages** listing openings (e.g. an internship landing page) — every link on the page to one of the ATSes above is treated as a posting, titled by its nearest heading. Only new links trigger a notification.

Fully custom sites that don't link to any of these (Google, Amazon, Microsoft, Shopify) aren't supported.

Only postings that appear after you start watching a company notify you: the first poll of a newly-added company silently records everything already on its site, and postings the site reports as more than 3 days old are skipped (search results aren't strictly newest-first, so an old posting can surface late).

- Runs as a foreground loop by default — for it to fire while you're not watching a terminal, either leave it running in a background terminal tab, or run `--watch-linkedin --once` on a schedule via `cron`/`launchd`.
- LinkedIn markup and rate limiting can change without notice — this hits a public, unauthenticated endpoint, not an official API, so treat it as best-effort and keep polling infrequent (default: every 5 minutes).

## Stack

- **Python** — CLI
- **SQLite / SQLAlchemy** — local storage of seen postings (swap `DATABASE_URL` in `.env` for Postgres)
- **httpx / BeautifulSoup** — fetches and parses LinkedIn's guest job-search HTML and career-board JSON APIs
- **rich** — terminal formatting

## Config

Override defaults via a `.env` file:

```
DATABASE_URL=sqlite:///./pipeline.db
LINKEDIN_KEYWORDS=Software Engineer Intern
LINKEDIN_LOCATION=Canada
COMPANY_BOARDS={"Cohere": "https://jobs.ashbyhq.com/cohere"}
```
