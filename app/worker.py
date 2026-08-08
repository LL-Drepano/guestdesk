import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
logger = logging.getLogger("worker")

POLL_INTERVAL_SECONDS = 3


def claim_one_job(session: Session) -> Job | None:
    """Atomically claim one pending job, marking it 'processing'.

    FOR UPDATE SKIP LOCKED is what makes this safe under concurrency:
    the row is locked so no other worker can take it, and other workers
    skip it rather than waiting.
    """
    job = session.execute(
        select(Job)
        .where(Job.status == "pending")
        .order_by(Job.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()

    if job is None:
        return None

    job.status = "processing"
    session.commit()
    return job


def process_job(session: Session, job: Job) -> None:
    """Do the work for one job."""
    message = job.message
    logger.info(
        f"Claimed job {job.id}  (message {message.id} from {message.sender})"
    )

    # Placeholder for the real work. Stage 2 replaces this with the LLM
    # call. The sleep simulates that slow work so concurrency is visible.
    time.sleep(2)

    job.status = "done"
    session.commit()
    logger.info(f"Finished job {job.id}")


def run_worker() -> None:
    logger.info("Worker started — polling for pending jobs...")
    while True:
        session = SessionLocal()
        try:
            job = claim_one_job(session)
            if job is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            process_job(session, job)
        except Exception:
            logger.exception("Error while processing a job")
            session.rollback()
        finally:
            session.close()


if __name__ == "__main__":
    run_worker()