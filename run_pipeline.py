"""
Job watch notifier — LinkedIn and company career sites.

Commands:
  python run_pipeline.py --watch                      Poll LinkedIn + company career sites, notify on new matches
  python run_pipeline.py --watch-linkedin             Poll LinkedIn only
  python run_pipeline.py --watch-companies            Poll company career sites only (COMPANY_BOARDS in config)
  python run_pipeline.py --watch-linkedin --keywords "Software Engineer Intern" --location Canada --interval 300
  python run_pipeline.py --watch --once               Single check-and-notify pass (for cron/launchd)
"""
import sys
import time
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.rule import Rule

from app.config import settings
from app.db.database import init_db, SessionLocal, Posting
from app.pipeline import run_pipeline
from app.ingestion.company_boards import COMPANY_SOURCES
from app.notify.notifier import notify

console = Console()

# Postings whose site-reported posted_at is older than this are recorded without
# notifying. A company's search results aren't strictly newest-first, so an old
# posting can surface for the first time long after it went up; anything
# genuinely new is picked up within one poll interval.
NEW_POSTING_MAX_AGE = timedelta(days=3)


def _is_stale(posting: Posting, now: datetime) -> bool:
    if posting.posted_at is None:
        return False
    posted_at = posting.posted_at if posting.posted_at.tzinfo else posting.posted_at.replace(tzinfo=timezone.utc)
    return now - posted_at > NEW_POSTING_MAX_AGE


def cmd_watch(linkedin: bool, companies: bool, keywords: str, location: str, interval: int, once: bool):
    init_db()

    # (label, run_pipeline kwargs) for each thing polled every pass
    targets = []
    sources = []
    if linkedin:
        label = f'"{keywords}"' + (f" in {location}" if location else " (anywhere)")
        targets.append((f"LinkedIn {label}", {"source": "linkedin", "keywords": keywords, "location": location}))
        sources.append("linkedin")
    if companies:
        for name, url in settings.company_boards.items():
            targets.append((name, {"source": "company", "name": name, "url": url}))
        sources.extend(COMPANY_SOURCES)

    console.print(Rule("[bold cyan]Watching " + ", ".join(label for label, _ in targets) + "[/]"))
    if once:
        console.print("[dim]Single pass.[/]")
    else:
        console.print(f"[dim]Polling every {interval}s. Press Ctrl+C to stop.[/]")
    console.print()

    while True:
        db = SessionLocal()
        try:
            # Poll each target independently so one broken board doesn't block the rest
            for label, kwargs in targets:
                try:
                    # First poll of a company: everything already on its site predates
                    # the watch, so record it without notifying — only later additions alert.
                    company_query = db.query(Posting).filter(
                        Posting.company == kwargs.get("name"), Posting.source.in_(COMPANY_SOURCES),
                    )
                    first_poll = kwargs["source"] == "company" and company_query.first() is None

                    result = run_pipeline(db=db, **kwargs)
                    if "error" in result:
                        console.print(f"[red]Error ({label}):[/] {result['error']}")
                    elif first_poll:
                        now = datetime.now(timezone.utc)
                        existing = company_query.filter(Posting.notified_at.is_(None)).all()
                        for p in existing:
                            p.notified_at = now
                        db.commit()
                        console.print(f"[dim]{label}: first check — recorded {len(existing)} existing postings without notifying.[/]")
                except Exception as e:
                    db.rollback()
                    console.print(f"[red]Watch error ({label}):[/] {e}")

            to_notify = (
                db.query(Posting)
                .filter(
                    Posting.source.in_(sources),
                    Posting.status == "new",
                    Posting.notified_at.is_(None),
                )
                .all()
            )
            now = datetime.now(timezone.utc)
            stale = [p for p in to_notify if _is_stale(p, now)]
            for p in stale:
                p.notified_at = now  # suppressed, not notified — see NEW_POSTING_MAX_AGE
            if stale:
                console.print(f"[dim]Skipped {len(stale)} matching postings older than {NEW_POSTING_MAX_AGE.days} days.[/]")
            to_notify = [p for p in to_notify if p not in stale]

            for p in to_notify:
                console.print(f"[bold bright_green]NEW[/]  {p.company or 'Unknown'} — {p.title}")
                console.print(f"      {p.url}")
                notify(
                    title="New LinkedIn posting" if p.source == "linkedin" else "New careers-site posting",
                    subtitle=p.company or "",
                    message=p.title or "",
                    url=p.url,
                )
                p.notified_at = now
            db.commit()
            if not to_notify:
                console.print("[dim]No new matches this pass.[/]")
        except Exception as e:
            console.print(f"[red]Watch error:[/] {e}")
        finally:
            db.close()

        if once:
            break
        time.sleep(interval)


if __name__ == "__main__":
    args = sys.argv[1:]

    modes = {
        "--watch": (True, True),
        "--watch-linkedin": (True, False),
        "--watch-companies": (False, True),
    }
    mode = next((a for a in args if a in modes), None)

    if mode:
        keywords = settings.linkedin_keywords
        location = settings.linkedin_location
        interval = 300
        once = "--once" in args
        for i, a in enumerate(args):
            if a == "--keywords" and i + 1 < len(args):
                keywords = args[i + 1]
            elif a == "--location" and i + 1 < len(args):
                location = args[i + 1]
            elif a == "--interval" and i + 1 < len(args):
                interval = int(args[i + 1])
        linkedin, companies = modes[mode]
        cmd_watch(linkedin=linkedin, companies=companies, keywords=keywords, location=location, interval=interval, once=once)

    else:
        console.print(__doc__)
