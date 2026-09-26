"""Tests for app/ingestion/company_boards.py.

httpx.get/httpx.post are monkeypatched so these never make real network calls.
"""
import pytest

from app.ingestion import company_boards, fetcher


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception("HTTP error")


# ---------------------------------------------------------------------------
# parse_board_url
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url, expected", [
    ("https://job-boards.greenhouse.io/ada18", ("greenhouse", {"board": "ada18"})),
    ("https://boards.greenhouse.io/faire/jobs/123", ("greenhouse", {"board": "faire"})),
    ("https://boards.greenhouse.io/embed/job_board?for=stripe", ("greenhouse", {"board": "stripe"})),
    ("https://jobs.lever.co/spotify", ("lever", {"board": "spotify", "api_host": "api.lever.co"})),
    ("https://jobs.eu.lever.co/objectway", ("lever", {"board": "objectway", "api_host": "api.eu.lever.co"})),
    ("https://jobs.ashbyhq.com/cohere/", ("ashby", {"board": "cohere"})),
    (
        "https://rbc.wd3.myworkdayjobs.com/en-US/RBCGLOBAL1",
        ("workday", {"host": "rbc.wd3.myworkdayjobs.com", "tenant": "rbc", "site": "RBCGLOBAL1"}),
    ),
    (
        "https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1",
        ("workday", {"host": "rbc.wd3.myworkdayjobs.com", "tenant": "rbc", "site": "RBCGLOBAL1"}),
    ),
])
def test_parse_board_url(url, expected):
    assert company_boards.parse_board_url(url) == expected


def test_parse_board_url_rejects_unsupported_site():
    with pytest.raises(ValueError):
        company_boards.parse_board_url("https://www.shopify.com/careers")


# ---------------------------------------------------------------------------
# Per-ATS fetchers
# ---------------------------------------------------------------------------

def test_fetch_greenhouse(monkeypatch):
    payload = {"jobs": [{
        "absolute_url": "https://job-boards.greenhouse.io/ada18/jobs/1",
        "title": "Software Engineering Intern",
        "location": {"name": "Toronto, ON"},
        "first_published": "2026-09-01T10:00:00-04:00",
    }]}
    monkeypatch.setattr(company_boards.httpx, "get", lambda url, **kw: _FakeResponse(payload))

    postings = company_boards.fetch_company_board("Ada", "https://job-boards.greenhouse.io/ada18")

    assert len(postings) == 1
    p = postings[0]
    assert p["url"] == "https://job-boards.greenhouse.io/ada18/jobs/1"
    assert p["company"] == "Ada"
    assert p["source"] == "greenhouse"
    assert p["description"] == "Software Engineering Intern\nToronto, ON"
    assert p["posted_at"].hour == 14  # converted to UTC


def test_fetch_lever(monkeypatch):
    payload = [{
        "hostedUrl": "https://jobs.lever.co/acme/abc",
        "text": "ML Intern",
        "categories": {"location": "Vancouver", "allLocations": ["Vancouver", "Toronto"]},
        "workplaceType": "hybrid",
        "createdAt": 1782214185805,
    }]
    monkeypatch.setattr(company_boards.httpx, "get", lambda url, **kw: _FakeResponse(payload))

    [p] = company_boards.fetch_company_board("Acme", "https://jobs.lever.co/acme")

    assert p["source"] == "lever"
    assert p["description"] == "ML Intern\nVancouver; Toronto; hybrid"
    assert p["posted_at"] is not None


def test_fetch_ashby_skips_unlisted_and_marks_remote(monkeypatch):
    payload = {"jobs": [
        {
            "title": "AI Research Intern",
            "jobUrl": "https://jobs.ashbyhq.com/cohere/1",
            "location": "San Francisco",
            "secondaryLocations": [{"location": "New York"}],
            "isRemote": True,
            "isListed": True,
            "publishedAt": "2026-09-15T18:21:37.401+00:00",
        },
        {"title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/cohere/2", "isListed": False},
    ]}
    monkeypatch.setattr(company_boards.httpx, "get", lambda url, **kw: _FakeResponse(payload))

    postings = company_boards.fetch_company_board("Cohere", "https://jobs.ashbyhq.com/cohere")

    assert [p["url"] for p in postings] == ["https://jobs.ashbyhq.com/cohere/1"]
    assert postings[0]["description"] == "AI Research Intern\nSan Francisco; New York; Remote"


def test_fetch_workday_dedupes_across_search_terms(monkeypatch):
    payload = {"total": 1, "jobPostings": [{
        "title": "Software Developer Co-op",
        "externalPath": "/job/Toronto/Software-Developer-Co-op_R-1",
        "locationsText": "TORONTO, Ontario, Canada",
    }]}
    calls = []

    def fake_post(url, json=None, **kw):
        calls.append((url, json["searchText"]))
        return _FakeResponse(payload)

    monkeypatch.setattr(company_boards.httpx, "post", fake_post)

    postings = company_boards.fetch_company_board("RBC", "https://rbc.wd3.myworkdayjobs.com/en-US/RBCGLOBAL1")

    assert len(postings) == 1  # same job returned for every search term
    assert postings[0]["url"] == "https://rbc.wd3.myworkdayjobs.com/RBCGLOBAL1/job/Toronto/Software-Developer-Co-op_R-1"
    assert postings[0]["source"] == "workday"
    assert calls[0][0] == "https://rbc.wd3.myworkdayjobs.com/wday/cxs/rbc/RBCGLOBAL1/jobs"
    assert [term for _, term in calls] == company_boards.WORKDAY_SEARCH_TERMS  # one page each


# ---------------------------------------------------------------------------
# Non-ATS URLs (fetched, then detected by page content)
# ---------------------------------------------------------------------------

class _FakeHtmlResponse:
    def __init__(self, text, url):
        self.text = text
        self.url = company_boards.httpx.URL(url)

    def raise_for_status(self):
        pass


SUCCESSFACTORS_HOME = '<link href="https://rmkcdn.successfactors.com/abc/site.css">'

SUCCESSFACTORS_SEARCH = """
<table><tr class="data-row">
  <td class="colTitle">
    <a class="jobTitle-link" href="/job/Toronto-Student-Intern%2C-Software-Engineer-ON/111/">Student Intern, Software Engineer</a>
  </td>
  <td class="colLocation"><span class="jobLocation">Toronto, ON, CA</span></td>
  <td class="colDate"><span class="jobDate">Sep 18, 2026</span></td>
</tr></table>
"""


def test_fetch_successfactors_site(monkeypatch):
    searched = []

    def fake_get(url, params=None, **kw):
        if url.endswith("/search/"):
            searched.append(params["q"])
            return _FakeHtmlResponse(SUCCESSFACTORS_SEARCH, url)
        return _FakeHtmlResponse(SUCCESSFACTORS_HOME, url)

    monkeypatch.setattr(company_boards.httpx, "get", fake_get)

    postings = company_boards.fetch_company_board("Celestica", "https://careers.celestica.com/")

    assert searched == company_boards.SUCCESSFACTORS_SEARCH_TERMS
    assert len(postings) == 1  # same job found by every search term
    p = postings[0]
    assert p["url"] == "https://careers.celestica.com/job/Toronto-Student-Intern%2C-Software-Engineer-ON/111/"
    assert p["title"] == "Student Intern, Software Engineer"
    assert p["source"] == "successfactors"
    assert p["description"] == "Student Intern, Software Engineer\nToronto, ON, CA"
    assert p["posted_at"].day == 18


HANDMADE_PAGE = """
<html><head><title>Join Mozilla Firefox Toronto Team</title></head><body>
<h1>Internships 2027 @ Mozilla Firefox</h1>
<p><strong>Firefox Graphics team</strong><br />Develop CSS layout features.<br />
  <a href="https://app.greenhouse.io/e/abc">Apply Here</a></p>
<p><strong>Firefox iOS team</strong><br />Build features in Swift.<br />
  <a href="https://app.greenhouse.io/e/def">Apply Here</a></p>
<p><a href="/about">About us</a></p>
</body></html>
"""


def test_fetch_handmade_page_uses_ats_links_and_headings(monkeypatch):
    monkeypatch.setattr(
        company_boards.httpx, "get", lambda url, **kw: _FakeHtmlResponse(HANDMADE_PAGE, url),
    )

    postings = company_boards.fetch_company_board("Mozilla Firefox", "https://soloist.ai/firefox2027internships")

    assert [p["url"] for p in postings] == ["https://app.greenhouse.io/e/abc", "https://app.greenhouse.io/e/def"]
    p = postings[0]
    assert p["title"] == "Firefox Graphics team — Internships 2027 @ Mozilla Firefox"
    assert p["source"] == "page"
    assert "Develop CSS layout features." in p["description"]
    assert "Toronto" in p["description"]


def test_handmade_page_postings_pass_filter(monkeypatch):
    from app.filtering.filter import is_relevant

    monkeypatch.setattr(
        company_boards.httpx, "get", lambda url, **kw: _FakeHtmlResponse(HANDMADE_PAGE, url),
    )
    postings = company_boards.fetch_company_board("Mozilla Firefox", "https://soloist.ai/firefox2027internships")

    assert all(is_relevant(p["title"], p["description"], strict_location=True) for p in postings)


def test_fetch_and_store_dispatches_to_company(monkeypatch, db_session):
    monkeypatch.setattr(company_boards.httpx, "get", lambda url, **kw: _FakeResponse({"jobs": [{
        "absolute_url": "https://job-boards.greenhouse.io/ada18/jobs/1",
        "title": "Software Engineering Intern",
        "location": {"name": "Toronto, ON"},
    }]}))

    result = fetcher.fetch_and_store("company", db_session, name="Ada", url="https://job-boards.greenhouse.io/ada18")

    assert result["new"] == 1
