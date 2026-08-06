import hashlib

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Job, Message
from app.schemas import IncomingMessage, IngestResult

router = APIRouter()


def compute_content_hash(message: IncomingMessage) -> str:
    """Fingerprint a message from its sender, subject, and body."""
    basis = f"{message.sender}|{message.subject or ''}|{message.body}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


@router.post("/ingest", response_model=IngestResult)
def ingest_message(
    payload: IncomingMessage,
    session: Session = Depends(get_session),
):
    content_hash = compute_content_hash(payload)

    message = Message(
        provider_message_id=payload.provider_message_id,
        content_hash=content_hash,
        sender=payload.sender,
        subject=payload.subject,
        body=payload.body,
    )
    job = Job(message=message, status="pending")

    session.add(message)
    session.add(job)

    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return JSONResponse(
            status_code=200,
            content={"detail": "duplicate message, already received"},
        )

    session.refresh(message)
    session.refresh(job)

    return IngestResult(
        message_id=message.id,
        job_id=job.id,
        status=job.status,
    )