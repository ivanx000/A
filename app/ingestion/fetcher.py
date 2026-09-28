"""
Ingestion layer — fetches postings and stores new ones (deduped by URL).

Sources:
  linkedin — LinkedIn's public guest job-search endpoint (no login required),
             polled at low frequency; HTML is parsed with BeautifulSoup.
  company  — a company's own career site (see app/ingestion/company_boards.py).
"""
from datetime import datetime, timedelta, timezone
import re
import httpx
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.config import settings
from app.db.database import Posting
from app.ingestion.company_boards import fetch_company_board


# ---------------------------------------------------------------------------
# LinkedIn (public guest job-search endpoint — no login required)
# ---------------------------------------------------------------------------

LINKEDIN_GUEST_SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

# Only the last hour is fetched, since only postings that new notify (see
# NEW_POSTING_MAX_AGE in run_pipeline.py). Results come back in relevance order
# (sortBy=DD is ignored by the guest endpoint), 10 per page, so a poll pages
# through the whole window — the first page alone drops anything ranked lower.
LINKEDIN_TIME_POSTED_FILTER = "r3600"
LINKEDIN_PAGE_SIZE = 10
LINKEDIN_MAX_PAGES = 25


def _fetch_linkedin(keywords: str | None = None, location: str | None = None) -> list[dict]:
    keywords = keywords if keywords is not None else settings.linkedin_keywords
    location = location if location is not None else settings.linkedin_location

    params = {"keywords": keywords, "f_TPR": LINKEDIN_TIME_POSTED_FILTER}
    if location:
        params["location"] = location

    postings = []
    for page in range(LINKEDIN_MAX_PAGES):
        resp = httpx.get(
            LINKEDIN_GUEST_SEARCH_URL,
            params={**params, "start": page * LINKEDIN_PAGE_SIZE},
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
                )
            },
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        if not resp.text.strip():
            break
        batch = _parse_linkedin_html(resp.text)
        postings.extend(batch)
        if len(batch) < LINKEDIN_PAGE_SIZE:
            break

    # Pages can overlap as the result set shifts between requests
    return list({p["url"]: p for p in postings}.values())


_RELATIVE_AGE_RE = re.compile(r"(\d+)\s+(second|minute|hour|day|week)s?\s+ago", re.IGNORECASE)


def _parse_linkedin_posted_at(time_el) -> datetime | None:
    """The <time> datetime attribute is only a date ("2026-09-28"), so prefer
    its text ("37 minutes ago"), which is precise enough to tell a posting
    from the last hour apart from one posted earlier the same day."""
    m = _RELATIVE_AGE_RE.search(time_el.get_text(" ", strip=True))
    if m:
        return datetime.now(timezone.utc) - timedelta(**{f"{m.group(2).lower()}s": int(m.group(1))})
    if time_el.get("datetime"):
        try:
            return datetime.fromisoformat(time_el["datetime"]).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def _parse_linkedin_html(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")

    postings = []
    for card in soup.select("div.base-card"):
        try:
            urn = card.get("data-entity-urn", "")
            job_id = urn.rsplit(":", 1)[-1] if urn else None

            title_el = card.select_one("h3.base-search-card__title")
            company_el = card.select_one("h4.base-search-card__subtitle")
            location_el = card.select_one("span.job-search-card__location")
            time_el = card.select_one("time")

            if not job_id or not title_el:
                continue

            title = title_el.get_text(strip=True)
            company = company_el.get_text(strip=True) if company_el else ""
            location_text = location_el.get_text(strip=True) if location_el else ""
            url = f"https://www.linkedin.com/jobs/view/{job_id}/"

            posted_at = _parse_linkedin_posted_at(time_el) if time_el else None

            postings.append({
                "url": url,
                "title": title[:200],
                "company": company[:200],
                "description": f"{title}\n{company}\n{location_text}",
                "source": "linkedin",
                "posted_at": posted_at,
            })
        except (AttributeError, KeyError):
            continue  # malformed card — LinkedIn markup shifts occasionally, skip rather than fail the whole batch

    return postings


# ---------------------------------------------------------------------------
# Store + entry point
# ---------------------------------------------------------------------------

SOURCES: dict[str, callable] = {
    "linkedin": _fetch_linkedin,
    "company": fetch_company_board,
}


def fetch_and_store(source: str, db: Session, **kwargs) -> dict:
    if source not in SOURCES:
        return {"error": f"Unknown source '{source}'. Available: {list(SOURCES.keys())}"}

    fetch_fn = SOURCES[source]
    raw = fetch_fn(**kwargs) if kwargs else fetch_fn()
    return _store(raw, db)


def _store(raw: list[dict], db: Session) -> dict:
    new_count = skipped = 0
    new_postings = []
    for p in raw:
        if db.query(Posting).filter(Posting.url == p["url"]).first():
            skipped += 1
            continue
        db.add(Posting(**p))
        new_postings.append({"url": p["url"], "title": p["title"], "company": p["company"]})
        new_count += 1
    db.commit()
    return {
        "fetched": len(raw),
        "new": new_count,
        "skipped": skipped,
        "new_postings": new_postings,
    }
