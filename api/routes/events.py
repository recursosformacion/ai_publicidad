"""Idempotent impression confirmation."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import ImpressionRequest
from application.security import require_service_token
from domain.models import AdDelivery, AdEvent
from infrastructure.database import get_db

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/impression", dependencies=[Depends(require_service_token)])
def confirm_impression(request: ImpressionRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    delivery = db.scalar(select(AdDelivery).where(AdDelivery.token == request.impression_id))
    if delivery is None:
        raise HTTPException(status_code=404, detail="Unknown impression identifier")

    if not delivery.impression_confirmed:
        now = datetime.now(timezone.utc)
        delivery.impression_confirmed = True
        delivery.impression_confirmed_at = now
        db.add(AdEvent(delivery_id=delivery.id, event_type="impression", deduplication_key=f"impression:{delivery.id}"))
        db.commit()

    return {"accepted": True, "counted": True}
