from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session

app = FastAPI(title="GuestDesk", version="0.1.0")


@app.get("/health")
def health(session: Session = Depends(get_session)):
    try:
        session.execute(text("SELECT 1"))
        database_ok = True
    except Exception:
        database_ok = False

    return JSONResponse(
        status_code=200 if database_ok else 503,
        content={
            "status": "ok" if database_ok else "degraded",
            "environment": settings.app_env,
            "database": "ok" if database_ok else "unreachable",
        },
    )