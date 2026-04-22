from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import db_session
from app.utils.response_format import Result

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=Result, summary="Service health check")
async def health_check(db: AsyncSession = Depends(db_session)) -> Result:
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return Result(
        data={
            "database": "up" if db_ok else "down",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        },
        status=200 if db_ok else 503,
        message="Service is healthy." if db_ok else "Service is degraded.",
    )
