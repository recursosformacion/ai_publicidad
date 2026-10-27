"""Public click-through endpoint. The final URL always comes from stored creative data."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from application.security import validate_destination
from application.commercial import charge_microcents_for_event
from domain.models import AdDelivery, AdEvent, Campaign, Creative
from infrastructure.database import get_db

router = APIRouter(tags=["clicks"])


@router.get("/r/{token}")
def click_through(token: str, db: Session = Depends(get_db)) -> RedirectResponse:
    delivery = db.scalar(select(AdDelivery).where(AdDelivery.token == token))
    if delivery is None:
        raise HTTPException(status_code=404, detail="Unknown ad click token")
    creative = db.get(Creative, delivery.creative_id)
    if creative is None:
        raise HTTPException(status_code=410, detail="Ad creative no longer exists")
    try:
        destination = validate_destination(creative.destination_url)
    except ValueError as exc:
        raise HTTPException(status_code=410, detail="Ad destination is invalid") from exc

    campaign = db.get(Campaign, delivery.campaign_id)
    charge = charge_microcents_for_event(db, campaign, "click") if campaign else 0
    db.add(AdEvent(delivery_id=delivery.id, event_type="click", charge_microcents=charge))
    db.commit()
    return RedirectResponse(url=destination, status_code=302)
