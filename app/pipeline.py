"""
Pipeline: ingestion → filter → store.
"""
from sqlalchemy.orm import Session

from app.ingestion.fetcher import fetch_and_store
from app.filtering.filter import is_relevant
from app.db.database import Posting


def run_pipeline(source: str, db: Session, **kwargs) -> dict:
    # Step 1: Ingest
    ingest_result = fetch_and_store(source=source, db=db, **kwargs)
    if "error" in ingest_result:
        return ingest_result

    # Step 2: Filter — mark non-matching postings as rejected
    unfiltered = (
        db.query(Posting)
        .filter(Posting.status == "new")
        .all()
    )

    rejected = 0
    for posting in unfiltered:
        # Only LinkedIn's search is pre-scoped to a location; career sites list jobs worldwide
        strict_location = posting.source != "linkedin"
        if not is_relevant(posting.title or "", posting.description or "", strict_location=strict_location):
            posting.status = "rejected"
            rejected += 1

    db.commit()

    new_count = ingest_result.get("new", 0)
    return {
        "source": source,
        "ingested": ingest_result.get("fetched", 0),
        "new": new_count,
        "rejected": rejected,
        "ready_to_review": new_count - rejected,
    }
