"""Tests for cmd_watch in run_pipeline.py — which postings actually notify.

Fetching and notifying are monkeypatched; the DB is the in-memory test session.
"""
from datetime import datetime, timedelta, timezone

import pytest

import run_pipeline
from app.db.database import Posting
from app.ingestion import fetcher


def _job(n, posted_at=None, title="Software Engineering Intern"):
    return {
        "url": f"https://jobs.ashbyhq.com/acme/{n}",
        "title": title,
        "company": "Acme",
        "description": f"{title}\nToronto, ON",
        "source": "ashby",
        "posted_at": posted_at,
    }


@pytest.fixture()
def watch(monkeypatch, db_session):
    """Returns (run_once, board, notified): run_once() does one --watch-companies
    pass over a single "Acme" board whose contents are the `board` list."""
    board = []
    notified = []
    monkeypatch.setattr(run_pipeline.settings, "company_boards", {"Acme": "https://jobs.ashbyhq.com/acme"})
    monkeypatch.setitem(fetcher.SOURCES, "company", lambda name, url: [dict(j) for j in board])
    monkeypatch.setattr(run_pipeline, "notify", lambda **kw: notified.append(kw["message"]))
    monkeypatch.setattr(run_pipeline, "init_db", lambda: None)
    monkeypatch.setattr(run_pipeline, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(db_session, "close", lambda: None)

    def run_once():
        run_pipeline.cmd_watch(linkedin=False, companies=True, keywords="", location="", interval=0, once=True)

    return run_once, board, notified


def test_first_poll_records_existing_postings_without_notifying(watch, db_session):
    run_once, board, notified = watch
    board.extend([_job(1), _job(2)])

    run_once()

    assert notified == []
    assert db_session.query(Posting).filter(Posting.notified_at.is_(None)).count() == 0


def test_postings_added_after_first_poll_notify_once(watch):
    run_once, board, notified = watch
    board.append(_job(1))
    run_once()

    board.append(_job(2, title="ML Intern"))
    run_once()
    run_once()

    assert notified == ["ML Intern"]


def test_first_poll_retries_if_fetch_fails(watch, monkeypatch):
    run_once, board, notified = watch
    board.append(_job(1))

    def broken(name, url):
        raise RuntimeError("site down")

    monkeypatch.setitem(fetcher.SOURCES, "company", broken)
    run_once()
    monkeypatch.setitem(fetcher.SOURCES, "company", lambda name, url: [dict(j) for j in board])
    run_once()  # this is still the first successful poll, so still silent

    assert notified == []


def test_old_postings_surfacing_later_do_not_notify(watch):
    run_once, board, notified = watch
    board.append(_job(1))
    run_once()

    now = datetime.now(timezone.utc)
    board.append(_job(2, posted_at=now - timedelta(days=30), title="Old Intern Software"))
    board.append(_job(3, posted_at=now - timedelta(hours=2), title="Earlier Today Intern Software"))
    board.append(_job(4, posted_at=now - timedelta(minutes=20), title="Fresh Intern Software"))
    run_once()

    assert notified == ["Fresh Intern Software"]


def test_date_only_sources_allow_postings_dated_today(watch):
    run_once, board, notified = watch
    board.append(_job(1))
    run_once()

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    board.append({**_job(2, posted_at=today, title="Today Intern Software"), "source": "workday"})
    board.append({**_job(3, posted_at=today - timedelta(days=3), title="Old Intern Software"), "source": "workday"})
    run_once()

    assert notified == ["Today Intern Software"]


@pytest.mark.parametrize("text, days_ago", [
    ("Posted Today", 0),
    ("Posted Yesterday", 1),
    ("Posted 3 Days Ago", 3),
    ("Posted 30+ Days Ago", 30),
])
def test_parse_workday_posted_on(text, days_ago):
    from app.ingestion.company_boards import _parse_workday_posted_on

    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert _parse_workday_posted_on(text) == today - timedelta(days=days_ago)


def test_parse_workday_posted_on_unknown_text():
    from app.ingestion.company_boards import _parse_workday_posted_on

    assert _parse_workday_posted_on("") is None
