"""
Ingestion layer — fetches postings and stores new ones (deduped by URL).

Sources:
  linkedin — LinkedIn's public guest job-search endpoint (no login required),
             polled at low frequency; HTML is parsed with BeautifulSoup.
  company  — a company's own career site (see app/ingestion/company_boards.py).
"""
from datetime import datetime, timezone
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

# Kept short (last hour) since this source is meant to be polled repeatedly by
# --watch-linkedin — a wide window would just re-fetch postings already
# deduped out on every poll.
LINKEDIN_TIME_POSTED_FILTER = "r3600"


def _fetch_linkedin(keywords: str | None = None, location: str | None = None) -> list[dict]:
    keywords = keywords if keywords is not None else settings.linkedin_keywords
    location = location if location is not None else settings.linkedin_location

    params = {"keywords": keywords, "f_TPR": LINKEDIN_TIME_POSTED_FILTER, "start": 0}
    if location:
        params["location"] = location

    resp = httpx.get(
        LINKEDIN_GUEST_SEARCH_URL,
        params=params,
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
        return []

    return _parse_linkedin_html(resp.text)


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

            posted_at = None
            if time_el and time_el.get("datetime"):
                try:
                    posted_at = datetime.fromisoformat(time_el["datetime"]).replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

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
