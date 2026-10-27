"""CRUD endpoints for commercial advertisers and advertising orders/contracts."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.admin_schemas import AdOrderInput, AdOrderRead, AdvertiserInput, AdvertiserRead
from domain.models import AdOrder, Advertiser, Campaign
from infrastructure.database import get_db

router = APIRouter(prefix="/admin", tags=["commercial administration"])


def _missing(kind: str, record_id: int) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{kind} {record_id} no existe")


def _save(db: Session, message: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=message) from exc


@router.get("/advertisers", response_model=list[AdvertiserRead])
def list_advertisers(include_archived: bool = Query(default=False), offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)) -> list[Advertiser]:
    query = select(Advertiser)
    if not include_archived:
        query = query.where(Advertiser.status != "archived")
    return list(db.scalars(query.order_by(Advertiser.name).offset(offset).limit(limit)).all())


@router.post("/advertisers", response_model=AdvertiserRead, status_code=status.HTTP_201_CREATED)
def create_advertiser(payload: AdvertiserInput, db: Session = Depends(get_db)) -> Advertiser:
    advertiser = Advertiser(**payload.model_dump())
    db.add(advertiser)
    _save(db, "Ya existe un anunciante con ese nombre.")
    db.refresh(advertiser)
    return advertiser


@router.get("/advertisers/{advertiser_id}", response_model=AdvertiserRead)
def get_advertiser(advertiser_id: int, db: Session = Depends(get_db)) -> Advertiser:
    advertiser = db.get(Advertiser, advertiser_id)
    if advertiser is None:
        raise _missing("Anunciante", advertiser_id)
    return advertiser


@router.put("/advertisers/{advertiser_id}", response_model=AdvertiserRead)
def replace_advertiser(advertiser_id: int, payload: AdvertiserInput, db: Session = Depends(get_db)) -> Advertiser:
    advertiser = db.get(Advertiser, advertiser_id)
    if advertiser is None:
        raise _missing("Anunciante", advertiser_id)
    for key, value in payload.model_dump().items():
        setattr(advertiser, key, value)
    _save(db, "Ya existe otro anunciante con ese nombre.")
    db.refresh(advertiser)
    return advertiser


@router.delete("/advertisers/{advertiser_id}")
def delete_advertiser(advertiser_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    advertiser = db.get(Advertiser, advertiser_id)
    if advertiser is None:
        raise _missing("Anunciante", advertiser_id)
    count = int(db.scalar(select(func.count()).select_from(AdOrder).where(AdOrder.advertiser_id == advertiser_id)) or 0)
    if count:
        advertiser.status = "archived"
        db.commit()
        return {"deleted": False, "archived": True, "message": "El anunciante se archiva para conservar sus pedidos y el histórico."}
    db.delete(advertiser)
    db.commit()
    return {"deleted": True}


@router.get("/orders", response_model=list[AdOrderRead])
def list_orders(advertiser_id: int | None = Query(default=None, gt=0), include_archived: bool = Query(default=False), offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200), db: Session = Depends(get_db)) -> list[AdOrder]:
    query = select(AdOrder)
    if advertiser_id is not None:
        query = query.where(AdOrder.advertiser_id == advertiser_id)
    if not include_archived:
        query = query.where(AdOrder.status != "archived")
    return list(db.scalars(query.order_by(AdOrder.id.desc()).offset(offset).limit(limit)).all())


@router.post("/orders", response_model=AdOrderRead, status_code=status.HTTP_201_CREATED)
def create_order(payload: AdOrderInput, db: Session = Depends(get_db)) -> AdOrder:
    if db.get(Advertiser, payload.advertiser_id) is None:
        raise HTTPException(status_code=404, detail=f"Anunciante {payload.advertiser_id} no existe")
    order = AdOrder(**payload.model_dump())
    db.add(order)
    _save(db, "Ya existe otro pedido con esa referencia.")
    db.refresh(order)
    return order


@router.get("/orders/{order_id}", response_model=AdOrderRead)
def get_order(order_id: int, db: Session = Depends(get_db)) -> AdOrder:
    order = db.get(AdOrder, order_id)
    if order is None:
        raise _missing("Pedido/contrato", order_id)
    return order


@router.put("/orders/{order_id}", response_model=AdOrderRead)
def replace_order(order_id: int, payload: AdOrderInput, db: Session = Depends(get_db)) -> AdOrder:
    order = db.get(AdOrder, order_id)
    if order is None:
        raise _missing("Pedido/contrato", order_id)
    if db.get(Advertiser, payload.advertiser_id) is None:
        raise HTTPException(status_code=404, detail=f"Anunciante {payload.advertiser_id} no existe")
    for key, value in payload.model_dump().items():
        setattr(order, key, value)
    _save(db, "Ya existe otro pedido con esa referencia.")
    db.refresh(order)
    return order


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    order = db.get(AdOrder, order_id)
    if order is None:
        raise _missing("Pedido/contrato", order_id)
    count = int(db.scalar(select(func.count()).select_from(Campaign).where(Campaign.order_id == order_id)) or 0)
    if count:
        order.status = "archived"
        db.commit()
        return {"deleted": False, "archived": True, "message": "El pedido se archiva porque hay campañas vinculadas; se conserva su trazabilidad."}
    db.delete(order)
    db.commit()
    return {"deleted": True}
