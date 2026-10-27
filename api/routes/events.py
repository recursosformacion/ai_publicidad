"""Idempotent impression confirmation, including concurrent duplicate requests."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from api.schemas import ImpressionRequest
from application.security import require_service_token
from application.commercial import charge_microcents_for_event
from domain.models import AdDelivery, AdEvent, Campaign
from infrastructure.database import get_db

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/impression", dependencies=[Depends(require_service_token)])
def confirm_impression(request: ImpressionRequest, db: Session = Depends(get_db)) -> dict[str, object]:
    delivery = db.scalar(select(AdDelivery).where(AdDelivery.token == request.impression_id))
    if delivery is None:
        raise HTTPException(status_code=404, detail="Unknown impression identifier")

    # A conditional UPDATE makes the first confirmation the only request allowed
    # to insert the event, even if multiple requests arrive at the same time.
    now = datetime.now(timezone.utc)
    result = db.execute(
        update(AdDelivery)
        .where(AdDelivery.id == delivery.id, AdDelivery.impression_confirmed.is_(False))
        .values(impression_confirmed=True, impression_confirmed_at=now)
    )
    if result.rowcount == 1:
        campaign = db.get(Campaign, delivery.campaign_id)
        charge = charge_microcents_for_event(db, campaign, "impression") if campaign else 0
        db.add(
            AdEvent(
                delivery_id=delivery.id,
                event_type="impression",
                occurred_at=now,
                deduplication_key=f"impression:{delivery.id}",
                charge_microcents=charge,
            )
        )
    db.commit()
    return {"accepted": True, "counted": result.rowcount == 1}
