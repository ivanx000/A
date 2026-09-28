"""Tests for the LinkedIn fetch functions in app/ingestion/fetcher.py.

httpx.get is monkeypatched so these never make real network calls.
"""
from app.ingestion import fetcher


LINKEDIN_CARD_HTML = """
<div class="base-card" data-entity-urn="urn:li:jobPosting:123456">
  <h3 class="base-search-card__title">Software Engineering Intern</h3>
  <h4 class="base-search-card__subtitle">Acme Corp</h4>
  <span class="job-search-card__location">Toronto, ON</span>
  <time datetime="2026-08-01T12:00:00"></time>
</div>
"""


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")


def test_fetch_linkedin_parses_job_cards(monkeypatch):
    monkeypatch.setattr(
        fetcher.httpx,
        "get",
        lambda url, params=None, headers=None, timeout=None, follow_redirects=None: _FakeResponse(LINKEDIN_CARD_HTML),
    )

    postings = fetcher._fetch_linkedin(keywords="Software Engineer Intern", location="Canada")

    assert len(postings) == 1
    p = postings[0]
    assert p["url"] == "https://www.linkedin.com/jobs/view/123456/"
    assert p["title"] == "Software Engineering Intern"
    assert p["company"] == "Acme Corp"
    assert p["source"] == "linkedin"
    assert p["posted_at"] is not None


def test_fetch_linkedin_returns_empty_on_blank_response(monkeypatch):
    monkeypatch.setattr(
        fetcher.httpx,
        "get",
        lambda url, params=None, headers=None, timeout=None, follow_redirects=None: _FakeResponse("   "),
    )
    assert fetcher._fetch_linkedin() == []


def test_fetch_linkedin_pages_until_short_page(monkeypatch):
    def card(job_id):
        return LINKEDIN_CARD_HTML.replace("123456", str(job_id))

    pages = {
        0: "".join(card(i) for i in range(10)),
        10: "".join(card(i) for i in range(9, 12)),  # overlaps previous page by one
    }
    starts = []

    def fake_get(url, params=None, headers=None, timeout=None, follow_redirects=None):
        starts.append(params["start"])
        return _FakeResponse(pages[params["start"]])

    monkeypatch.setattr(fetcher.httpx, "get", fake_get)

    postings = fetcher._fetch_linkedin()

    assert starts == [0, 10]
    assert len(postings) == 12


def test_parse_linkedin_posted_at_uses_relative_text():
    from datetime import datetime, timedelta, timezone

    html = LINKEDIN_CARD_HTML.replace(
        '<time datetime="2026-08-01T12:00:00"></time>',
        '<time datetime="2026-08-01">\n  37 minutes ago\n  </time>',
    )
    posted_at = fetcher._parse_linkedin_html(html)[0]["posted_at"]

    expected = datetime.now(timezone.utc) - timedelta(minutes=37)
    assert abs(posted_at - expected) < timedelta(seconds=5)


def test_parse_linkedin_html_skips_cards_missing_job_id_or_title():
    html = """
    <div class="base-card">
      <h3 class="base-search-card__title">No job id, should be skipped</h3>
    </div>
    """
    assert fetcher._parse_linkedin_html(html) == []


# ---------------------------------------------------------------------------
# fetch_and_store / SOURCES registry
# ---------------------------------------------------------------------------

def test_fetch_and_store_unknown_source(db_session):
    result = fetcher.fetch_and_store("bogus_source", db_session)
    assert "error" in result


def test_fetch_and_store_dispatches_to_linkedin(monkeypatch, db_session):
    monkeypatch.setitem(
        fetcher.SOURCES,
        "linkedin",
        lambda: [
            {
                "url": "https://www.linkedin.com/jobs/view/1/",
                "title": "Intern",
                "company": "Acme",
                "description": "desc",
                "source": "linkedin",
                "posted_at": None,
            }
        ],
    )

    result = fetcher.fetch_and_store("linkedin", db_session)
    assert result["fetched"] == 1
    assert result["new"] == 1
    assert result["skipped"] == 0
