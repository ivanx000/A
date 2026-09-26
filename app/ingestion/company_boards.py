"""
Company career-site ingestion — polls a company's own job board directly,
since not every role gets cross-posted to LinkedIn.

Most company career pages are hosted on (or embed) an applicant-tracking
system with a public JSON endpoint, so a board is configured by its URL and
the ATS is detected from the host:

  Greenhouse  https://job-boards.greenhouse.io/<token>
  Lever       https://jobs[.eu].lever.co/<company>
  Ashby       https://jobs.ashbyhq.com/<name>
  Workday     https://<tenant>.wd<N>.myworkdayjobs.com/[<locale>/]<site>

Any other URL is fetched and handled by what's on the page:

  SuccessFactors  a career site on its own domain (e.g. careers.celestica.com)
                  is searched via its /search/ page
  Anything else   treated as a hand-made list of openings — every link to an
                  ATS on the page is a posting, titled by its nearest heading
"""
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, parse_qs, urljoin

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Workday boards are large (hundreds of postings) and paginate 20 at a time,
# so only search for student roles rather than walking the whole board.
WORKDAY_SEARCH_TERMS = ["intern", "co-op", "student"]
WORKDAY_PAGE_SIZE = 20
WORKDAY_MAX_PAGES = 5

# SuccessFactors keyword search is fuzzy ("intern" also matches "internal", so
# it returns most of the board) — these terms return just the student roles.
SUCCESSFACTORS_SEARCH_TERMS = ["student", "co-op", "internship"]
SUCCESSFACTORS_PAGE_SIZE = 25  # fixed by the site
SUCCESSFACTORS_MAX_PAGES = 4

_SUCCESSFACTORS_RE = re.compile(r"rmkcdn\.successfactors\.com|\.successfactors\.(?:com|eu)\b")

# Links to these hosts on a hand-made careers page are treated as postings
_ATS_LINK_RE = re.compile(r"(?:^|\.)(?:greenhouse\.io|lever\.co|ashbyhq\.com|myworkdayjobs\.com)$")

_LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")


def parse_board_url(url: str) -> tuple[str, dict]:
    """Return (ats, params) for a careers-page URL, or raise ValueError if unsupported."""
    u = urlparse(url)
    host = u.netloc.lower()
    parts = [p for p in u.path.split("/") if p]

    if host in ("boards.greenhouse.io", "job-boards.greenhouse.io"):
        # Embedded boards look like boards.greenhouse.io/embed/job_board?for=<token>
        token = parse_qs(u.query).get("for", [None])[0] if parts[:1] == ["embed"] else (parts[0] if parts else None)
        if token:
            return "greenhouse", {"board": token}
    elif host in ("jobs.lever.co", "jobs.eu.lever.co") and parts:
        return "lever", {"board": parts[0], "api_host": host.replace("jobs.", "api.", 1)}
    elif host == "jobs.ashbyhq.com" and parts:
        return "ashby", {"board": parts[0]}
    elif host.endswith(".myworkdayjobs.com"):
        site = next((p for p in parts if not _LOCALE_RE.match(p)), None)
        if site:
            return "workday", {"host": host, "tenant": host.split(".")[0], "site": site}

    raise ValueError(f"Unsupported careers URL '{url}' — expected a Greenhouse, Lever, Ashby, or Workday board")


def fetch_company_board(name: str, url: str) -> list[dict]:
    try:
        ats, params = parse_board_url(url)
    except ValueError:
        resp = httpx.get(url, headers={**_HEADERS, "Accept": "text/html"}, timeout=20, follow_redirects=True)
        resp.raise_for_status()
        if _SUCCESSFACTORS_RE.search(resp.text):
            origin = f"{resp.url.scheme}://{resp.url.host}"
            return _fetch_successfactors(company=name, origin=origin)
        return _parse_page_links(name, str(resp.url), resp.text)
    return _FETCHERS[ats](company=name, **params)


def _posting(company: str, source: str, url: str, title: str, location: str, posted_at) -> dict:
    title = title.strip()
    return {
        "url": url,
        "title": title[:200],
        "company": company[:200],
        # Company name is left out: every posting on the board shares it, and a
        # name like "Scale AI" would otherwise trip the AI/ML keyword filter.
        "description": f"{title}\n{location}",
        "source": source,
        "posted_at": posted_at,
    }


def _parse_iso(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Greenhouse
# ---------------------------------------------------------------------------

def _fetch_greenhouse(company: str, board: str) -> list[dict]:
    resp = httpx.get(f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs", headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return [
        _posting(
            company, "greenhouse", job["absolute_url"], job.get("title", ""),
            (job.get("location") or {}).get("name", ""),
            _parse_iso(job.get("first_published") or job.get("updated_at")),
        )
        for job in resp.json().get("jobs", [])
        if job.get("absolute_url") and job.get("title")
    ]


# ---------------------------------------------------------------------------
# Lever
# ---------------------------------------------------------------------------

def _fetch_lever(company: str, board: str, api_host: str = "api.lever.co") -> list[dict]:
    resp = httpx.get(f"https://{api_host}/v0/postings/{board}", params={"mode": "json"}, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    postings = []
    for job in resp.json():
        if not job.get("hostedUrl") or not job.get("text"):
            continue
        categories = job.get("categories") or {}
        locations = categories.get("allLocations") or [categories.get("location", "")]
        location = "; ".join(filter(None, locations + [job.get("workplaceType", "")]))
        created = job.get("createdAt")
        posted_at = datetime.fromtimestamp(created / 1000, tz=timezone.utc) if created else None
        postings.append(_posting(company, "lever", job["hostedUrl"], job["text"], location, posted_at))
    return postings


# ---------------------------------------------------------------------------
# Ashby
# ---------------------------------------------------------------------------

def _fetch_ashby(company: str, board: str) -> list[dict]:
    resp = httpx.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}", headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    postings = []
    for job in resp.json().get("jobs", []):
        if not job.get("isListed", True) or not job.get("jobUrl") or not job.get("title"):
            continue
        locations = [job.get("location", "")] + [s.get("location", "") for s in job.get("secondaryLocations") or []]
        if job.get("isRemote"):
            locations.append("Remote")
        location = "; ".join(filter(None, locations))
        postings.append(_posting(company, "ashby", job["jobUrl"], job["title"], location, _parse_iso(job.get("publishedAt"))))
    return postings


# ---------------------------------------------------------------------------
# Workday
# ---------------------------------------------------------------------------

def _fetch_workday(company: str, host: str, tenant: str, site: str) -> list[dict]:
    api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    seen = {}
    for term in WORKDAY_SEARCH_TERMS:
        for page in range(WORKDAY_MAX_PAGES):
            resp = httpx.post(
                api_url,
                json={"appliedFacets": {}, "limit": WORKDAY_PAGE_SIZE, "offset": page * WORKDAY_PAGE_SIZE, "searchText": term},
                headers=_HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            jobs = data.get("jobPostings") or []
            for job in jobs:
                if not job.get("externalPath") or not job.get("title"):
                    continue
                url = f"https://{host}/{site}{job['externalPath']}"
                posted_at = _parse_workday_posted_on(job.get("postedOn", ""))
                seen[url] = _posting(company, "workday", url, job["title"], job.get("locationsText", ""), posted_at)
            if (page + 1) * WORKDAY_PAGE_SIZE >= data.get("total", 0) or not jobs:
                break
    return list(seen.values())


def _parse_workday_posted_on(text: str):
    """postedOn is relative text: "Posted Today", "Posted Yesterday",
    "Posted 3 Days Ago", or "Posted 30+ Days Ago"."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    text = text.lower()
    if "today" in text:
        return today
    if "yesterday" in text:
        return today - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s+days?\s+ago", text)
    return today - timedelta(days=int(m.group(1))) if m else None


# ---------------------------------------------------------------------------
# SuccessFactors (career site on the company's own domain)
# ---------------------------------------------------------------------------

def _fetch_successfactors(company: str, origin: str) -> list[dict]:
    seen = {}
    for term in SUCCESSFACTORS_SEARCH_TERMS:
        for page in range(SUCCESSFACTORS_MAX_PAGES):
            resp = httpx.get(
                f"{origin}/search/",
                params={
                    "q": term,
                    "sortColumn": "referencedate",
                    "sortDirection": "desc",
                    "startrow": page * SUCCESSFACTORS_PAGE_SIZE,
                },
                headers={**_HEADERS, "Accept": "text/html"},
                timeout=20,
            )
            resp.raise_for_status()
            rows = _parse_successfactors_html(company, origin, resp.text)
            for p in rows:
                seen[p["url"]] = p
            if len(rows) < SUCCESSFACTORS_PAGE_SIZE:
                break
    return list(seen.values())


def _parse_successfactors_html(company: str, origin: str, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    postings = []
    for row in soup.select("tr.data-row"):
        link = row.select_one("a.jobTitle-link")
        if not link or not link.get("href"):
            continue
        location_el = row.select_one("td.colLocation span.jobLocation") or row.select_one("span.jobLocation")
        date_el = row.select_one("td.colDate span.jobDate") or row.select_one("span.jobDate")
        posted_at = None
        if date_el:
            try:
                posted_at = datetime.strptime(date_el.get_text(strip=True), "%b %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        postings.append(_posting(
            company, "successfactors", urljoin(origin, link["href"]), link.get_text(strip=True),
            location_el.get_text(" ", strip=True) if location_el else "", posted_at,
        ))
    return postings


# ---------------------------------------------------------------------------
# Hand-made careers page (fallback)
# ---------------------------------------------------------------------------

def _parse_page_links(company: str, page_url: str, html: str) -> list[dict]:
    """Treat each link to an ATS as one posting.

    These pages are usually a list of blurbs each ending in a generic "Apply"
    link, so the posting title comes from the blurb's heading, suffixed with
    the page heading (e.g. "Firefox Graphics team — Internships 2027 @ Mozilla
    Firefox") so the intern filter can see what kind of role it is. The page
    <title> goes in the description for the location filter.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    page_heading = h1.get_text(" ", strip=True) if h1 else ""
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""

    seen = {}
    for link in soup.find_all("a", href=True):
        url = urljoin(page_url, link["href"])
        if url in seen or not _ATS_LINK_RE.search(urlparse(url).netloc.lower()):
            continue
        block = link.find_parent(["p", "li", "tr", "article", "section", "div"]) or link
        heading_el = block.find(["h2", "h3", "h4", "strong", "b"])
        heading = heading_el.get_text(" ", strip=True) if heading_el else link.get_text(" ", strip=True)
        if not heading:
            continue
        title = f"{heading} — {page_heading}" if page_heading and page_heading not in heading else heading
        posting = _posting(company, "page", url, title, page_title, None)
        posting["description"] = f"{title}\n{block.get_text(' ', strip=True)}\n{page_title}"
        seen[url] = posting
    return list(seen.values())


_FETCHERS = {
    "greenhouse": _fetch_greenhouse,
    "lever": _fetch_lever,
    "ashby": _fetch_ashby,
    "workday": _fetch_workday,
}

# Posting.source values written by this module
COMPANY_SOURCES = list(_FETCHERS) + ["successfactors", "page"]
