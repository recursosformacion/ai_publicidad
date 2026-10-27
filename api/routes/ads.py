"""Ad selection and simple area-aware HTML composition endpoints."""

import html
import itertools
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.schemas import AdArea, AdPayload, ComposeAdRequest, FormatRequest, ServeAdRequest
from application.security import require_service_token, validate_destination
from domain.models import (
    AdDelivery,
    AdEvent,
    AdFormat,
    Brand,
    Campaign,
    Creative,
    TargetingRule,
    brand_competitors,
)
from infrastructure.config import get_settings
from infrastructure.database import get_db

router = APIRouter(prefix="/ads", tags=["ads"])


def _campaign_is_current(campaign: Campaign, now: datetime) -> bool:
    if campaign.status != "active":
        return False
    starts = campaign.starts_at
    ends = campaign.ends_at
    if starts and starts.replace(tzinfo=timezone.utc) > now:
        return False
    if ends and ends.replace(tzinfo=timezone.utc) < now:
        return False
    return True


def _matches_targeting(db: Session, creative_id: int, request: ServeAdRequest) -> bool:
    rules = db.scalars(select(TargetingRule).where(TargetingRule.creative_id == creative_id)).all()
    context = {
        "application": request.application,
        "page_type": request.page.type,
        "placement": request.placement,
        "language": request.page.language,
        "entity_type": request.page.entity_type or "",
        "entity_id": request.page.entity_id or "",
    }
    # Inclusion rules for the same field are alternatives (OR); exclusion
    # rules always win. Treating every include as a separate AND made it
    # impossible to target a creative to more than one page type or language.
    rules_by_type: dict[str, list[TargetingRule]] = {}
    for rule in rules:
        rules_by_type.setdefault(rule.rule_type, []).append(rule)

    for rule_type, typed_rules in rules_by_type.items():
        actual = context.get(rule_type, "")
        excluded = [
            rule for rule in typed_rules
            if rule.effect == "exclude"
            and (actual == rule.rule_value or rule.rule_value == "*")
        ]
        if excluded:
            return False

        included = [rule for rule in typed_rules if rule.effect == "include"]
        if included and not any(
            actual == rule.rule_value or rule.rule_value == "*"
            for rule in included
        ):
            return False
    return True



@dataclass(frozen=True)
class _AdOption:
    creative: Creative
    campaign: Campaign
    ad_format: AdFormat
    last_delivered_at: datetime | None = None

    @property
    def width(self) -> int:
        return self.ad_format.width

    @property
    def height(self) -> int:
        return self.ad_format.height


@dataclass(frozen=True)
class _Layout:
    orientation: str
    items: tuple[_AdOption, ...]
    score: float
    width: int
    height: int


def _compose_context(request: ComposeAdRequest) -> ServeAdRequest:
    return ServeAdRequest(
        application=request.application,
        page=request.page,
        placement=request.placement,
        format=FormatRequest(type="responsive"),
        device=request.device,
    )


def _campaigns_in_cooldown(
    db: Session,
    campaigns: list[Campaign],
    request: ComposeAdRequest | ServeAdRequest,
    now: datetime,
) -> set[int]:
    """Suppress repeats for the same application/page/entity/placement context only."""
    intervals = {
        campaign.id: campaign.minimum_interval_seconds
        for campaign in campaigns
        if campaign.minimum_interval_seconds > 0
    }
    if not intervals:
        return set()

    max_interval = max(intervals.values())
    query = (
        select(AdDelivery.campaign_id, func.max(AdDelivery.delivered_at))
        .where(
            AdDelivery.campaign_id.in_(list(intervals)),
            AdDelivery.application == request.application,
            AdDelivery.page_type == request.page.type,
            AdDelivery.placement == request.placement,
            AdDelivery.delivered_at >= now - timedelta(seconds=max_interval),
        )
        .group_by(AdDelivery.campaign_id)
    )
    if request.page.entity_type is None:
        query = query.where(AdDelivery.entity_type.is_(None))
    else:
        query = query.where(AdDelivery.entity_type == request.page.entity_type)
    if request.page.entity_id is None:
        query = query.where(AdDelivery.entity_id.is_(None))
    else:
        query = query.where(AdDelivery.entity_id == request.page.entity_id)

    suppressed: set[int] = set()
    for campaign_id, delivered_at in db.execute(query).all():
        if delivered_at is None:
            continue
        if delivered_at.tzinfo is None:
            delivered_at = delivered_at.replace(tzinfo=timezone.utc)
        if delivered_at + timedelta(seconds=intervals.get(campaign_id, 0)) > now:
            suppressed.add(campaign_id)
    return suppressed


def _latest_creative_deliveries(
    db: Session,
    creative_ids: set[int],
    request: ComposeAdRequest | ServeAdRequest,
    now: datetime,
) -> dict[int, datetime]:
    """Return the last display time per creative for the same slot context."""
    if not creative_ids:
        return {}
    query = (
        select(AdDelivery.creative_id, func.max(AdDelivery.delivered_at))
        .where(
            AdDelivery.creative_id.in_(creative_ids),
            AdDelivery.application == request.application,
            AdDelivery.page_type == request.page.type,
            AdDelivery.placement == request.placement,
            AdDelivery.delivered_at >= now - timedelta(days=30),
        )
        .group_by(AdDelivery.creative_id)
    )
    if request.page.entity_type is None:
        query = query.where(AdDelivery.entity_type.is_(None))
    else:
        query = query.where(AdDelivery.entity_type == request.page.entity_type)
    if request.page.entity_id is None:
        query = query.where(AdDelivery.entity_id.is_(None))
    else:
        query = query.where(AdDelivery.entity_id == request.page.entity_id)
    return {
        int(creative_id): delivered_at
        for creative_id, delivered_at in db.execute(query).all()
        if delivered_at is not None
    }


def _last_shown_sort_value(delivered_at: datetime | None) -> float:
    """Older or unseen creatives sort first among equal commercial priorities."""
    if delivered_at is None:
        return float("-inf")
    if delivered_at.tzinfo is None:
        delivered_at = delivered_at.replace(tzinfo=timezone.utc)
    return delivered_at.timestamp()


def _active_brand_ids(db: Session, campaign_ids: set[int], rows: list[tuple[Creative, Campaign]]) -> set[int]:
    brand_ids = {campaign.brand_id for _, campaign in rows if campaign.id in campaign_ids and campaign.brand_id}
    if not brand_ids:
        return set()
    return set(
        db.scalars(
            select(Brand.id).where(Brand.id.in_(brand_ids), Brand.is_active.is_(True))
        ).all()
    )


def _brand_conflicts(db: Session) -> set[frozenset[int]]:
    return {
        frozenset((int(left), int(right)))
        for left, right in db.execute(
            select(brand_competitors.c.brand_left_id, brand_competitors.c.brand_right_id)
        ).all()
    }


def _compose_options(
    db: Session,
    request: ComposeAdRequest,
    area: AdArea,
    now: datetime,
    fixed_format: AdFormat | None = None,
) -> list[_AdOption]:
    rows = db.execute(
        select(Creative, Campaign)
        .join(Campaign, Campaign.id == Creative.campaign_id)
        .where(Creative.status == "approved")
        .order_by(Campaign.priority.desc(), Creative.id.asc())
    ).all()
    if request.creative_id is not None:
        rows = [(creative, campaign) for creative, campaign in rows if creative.id == request.creative_id]
    context_request = _compose_context(request)
    temporally_suppressed = _campaigns_in_cooldown(
        db, [campaign for _, campaign in rows], request, now
    )
    active_brands = _active_brand_ids(
        db, {campaign.id for _, campaign in rows}, rows
    )
    last_seen = _latest_creative_deliveries(
        db, {creative.id for creative, _ in rows}, request, now
    )
    options: list[_AdOption] = []

    for creative, campaign in rows:
        if not _campaign_is_current(campaign, now):
            continue
        if campaign.id in temporally_suppressed:
            continue
        if campaign.brand_id is not None and campaign.brand_id not in active_brands:
            continue
        if creative.language not in {request.page.language, "mul", "es"}:
            continue
        if not _matches_targeting(db, creative.id, context_request):
            continue
        try:
            validate_destination(creative.destination_url)
        except ValueError:
            continue
        if creative.image_url:
            try:
                validate_destination(creative.image_url)
            except ValueError:
                continue

        assigned_formats = [item for item in creative.ad_formats if item.is_active]
        if fixed_format is not None:
            if fixed_format.device not in {"both", request.device}:
                continue
            if assigned_formats and fixed_format.id not in {item.id for item in assigned_formats}:
                continue
            options.append(
                _AdOption(creative, campaign, fixed_format, last_seen.get(creative.id))
            )
            continue

        if assigned_formats:
            candidate_formats = assigned_formats
        else:
            candidate_formats = list(
                db.scalars(
                    select(AdFormat).where(
                        AdFormat.is_active.is_(True),
                        AdFormat.device.in_(("both", request.device)),
                    ).order_by(AdFormat.width.desc(), AdFormat.height.desc())
                ).all()
            )

        for ad_format in candidate_formats:
            if ad_format.device not in {"both", request.device}:
                continue
            if ad_format.width > area.width or ad_format.height > area.height:
                continue
            options.append(
                _AdOption(creative, campaign, ad_format, last_seen.get(creative.id))
            )

    # Commercially eligible campaigns are selected first. Own ads are a fallback pool,
    # not a way to displace an eligible commercial campaign or mix unrelated objectives.
    commercial_options = [option for option in options if not option.campaign.is_house_ad]
    selected_pool = commercial_options or [option for option in options if option.campaign.is_house_ad]
    selected_pool.sort(
        key=lambda option: (
            -option.campaign.priority,
            _last_shown_sort_value(option.last_delivered_at),
            option.creative.id,
            -(option.ad_format.width * option.ad_format.height),
        )
    )
    return selected_pool


def _layout_dimensions(items: tuple[_AdOption, ...], orientation: str, gap: int) -> tuple[int, int]:
    if orientation == "row":
        return (
            sum(item.width for item in items) + gap * (len(items) - 1),
            max(item.height for item in items),
        )
    return (
        max(item.width for item in items),
        sum(item.height for item in items) + gap * (len(items) - 1),
    )


def _brands_are_compatible(items: tuple[_AdOption, ...], competitor_pairs: set[frozenset[int]]) -> bool:
    brand_ids = [item.campaign.brand_id for item in items if item.campaign.brand_id is not None]
    # Even non-competing creatives from the same registered brand are not duplicated
    # in one block; explicit competitor pairs additionally prohibit adjacent competitors.
    if len(set(brand_ids)) != len(brand_ids):
        return False
    for left, right in itertools.combinations(brand_ids, 2):
        if frozenset((left, right)) in competitor_pairs:
            return False
    campaign_ids = [item.campaign.id for item in items]
    return len(set(campaign_ids)) == len(campaign_ids)


def _choose_layout(
    options: list[_AdOption],
    area: AdArea,
    max_ads: int,
    gap: int,
    requested_orientation: str,
    competitor_pairs: set[frozenset[int]],
) -> _Layout | None:
    if not options:
        return None

    # Strictly homogeneous composition: try the largest available standard size first.
    sizes = sorted(
        {(item.width, item.height) for item in options},
        key=lambda size: (size[0] * size[1], min(size), max(size)),
        reverse=True,
    )
    for width, height in sizes:
        size_options: list[_AdOption] = []
        seen_creatives: set[int] = set()
        for option in options:
            if (option.width, option.height) != (width, height):
                continue
            if option.creative.id in seen_creatives:
                continue
            size_options.append(option)
            seen_creatives.add(option.creative.id)
            # Bound combinatorial work while preserving the highest-priority candidates.
            if len(size_options) >= 18:
                break
        if not size_options:
            continue

        possible_orientations = (
            ("row", "column")
            if requested_orientation == "auto"
            else (requested_orientation,)
        )
        capacities: list[tuple[str, int]] = []
        for orientation in possible_orientations:
            if orientation == "row":
                capacity = (area.width + gap) // (width + gap) if height <= area.height else 0
            else:
                capacity = (area.height + gap) // (height + gap) if width <= area.width else 0
            if capacity > 0:
                capacities.append((orientation, min(max_ads, capacity, len(size_options))))
        if not capacities:
            continue

        largest_count = max(capacity for _, capacity in capacities)
        # A larger slot wins before any smaller slot is considered. Within that slot,
        # use as many distinct, commercially ranked and brand-compatible ads as fit.
        for count in range(largest_count, 0, -1):
            best: _Layout | None = None
            best_key: tuple[int, tuple[int, ...]] | None = None
            for items in itertools.combinations(size_options, count):
                if not _brands_are_compatible(items, competitor_pairs):
                    continue
                for orientation, capacity in capacities:
                    if count > capacity:
                        continue
                    layout_width, layout_height = _layout_dimensions(items, orientation, gap)
                    if layout_width > area.width or layout_height > area.height:
                        continue
                    priorities = tuple(sorted(
                        (item.campaign.priority for item in items), reverse=True
                    ))
                    key = (sum(priorities), priorities)
                    if best is None or key > best_key:
                        best = _Layout(
                            orientation=orientation if count > 1 else "single",
                            items=items,
                            score=float(sum(priorities)),
                            width=layout_width,
                            height=layout_height,
                        )
                        best_key = key
            if best is not None:
                # When two orientations fit the same number of cards, prefer the natural
                # direction of the available area rather than mixing sizes.
                if len(best.items) > 1 and requested_orientation == "auto":
                    preferred = "row" if area.width >= area.height else "column"
                    if _layout_dimensions(best.items, preferred, gap)[0] <= area.width and _layout_dimensions(best.items, preferred, gap)[1] <= area.height:
                        best = _Layout(
                            preferred, best.items, best.score,
                            *_layout_dimensions(best.items, preferred, gap),
                        )
                return best
    return None


def _render_layout_html(
    layout: _Layout | None,
    area: AdArea,
    request: ComposeAdRequest,
    db: Session,
    now: datetime,
) -> str:
    area_width = area.width
    area_height = area.height
    if layout is None:
        return (
            '<div class="ap-layout ap-layout-empty" data-layout-status="no-fill" '
            f'data-area-width="{area_width}" data-area-height="{area_height}" '
            f'style="position:relative;width:{area_width}px;height:{area_height}px;'
            'max-width:100%;overflow:hidden;box-sizing:border-box;'
            'display:grid;place-items:center;border:1px dashed #a7b5c4;'
            'font:14px/1.4 system-ui,sans-serif;color:#65758a">'
            "No hay anuncios compatibles con este espacio."
            "</div>"
        )

    settings = get_settings()
    tokens: list[str] = []
    deliveries: list[AdDelivery] = []
    for option in layout.items:
        token = secrets.token_urlsafe(32)
        delivery = AdDelivery(
            token=token,
            creative_id=option.creative.id,
            campaign_id=option.campaign.id,
            application=request.application,
            page_type=request.page.type,
            entity_type=request.page.entity_type,
            entity_id=request.page.entity_id,
            placement=request.placement,
            language=request.page.language,
            ad_format_id=option.ad_format.id,
            impression_confirmed=True,
            impression_confirmed_at=now,
        )
        db.add(delivery)
        db.flush()
        db.add(
            AdEvent(
                delivery_id=delivery.id,
                event_type="impression",
                occurred_at=now,
                deduplication_key=f"impression:{delivery.id}",
            )
        )
        deliveries.append(delivery)
        tokens.append(token)
    positions: list[tuple[int, int]] = []
    if layout.orientation == "row":
        x = 0
        for option in layout.items:
            y = max(0, (area_height - option.height) // 2)
            positions.append((x, y))
            x += option.width + request.gap
    elif layout.orientation == "column":
        y = 0
        for option in layout.items:
            x = max(0, (area_width - option.width) // 2)
            positions.append((x, y))
            y += option.height + request.gap
    else:
        option = layout.items[0]
        positions.append(((area_width - option.width) // 2, (area_height - option.height) // 2))

    count = len(layout.items)
    rendered: list[str] = []
    for index, (option, token, position) in enumerate(zip(layout.items, tokens, positions, strict=True)):
        creative = option.creative
        x, y = position
        click_url = f"{settings.public_base_url.rstrip('/')}/r/{token}"
        title = html.escape(creative.title, quote=True)
        body = html.escape(creative.body or "", quote=True)
        link = html.escape(click_url, quote=True)
        fmt_code = html.escape(option.ad_format.code, quote=True)
        kind = "house" if option.campaign.is_house_ad else "commercial"
        alt = html.escape(creative.alt_text or "", quote=True)
        image_html = ""
        if creative.image_url:
            image_url = html.escape(creative.image_url, quote=True)
            image_html = (
                f'<img class="ap-ad-image" src="{image_url}" alt="{alt}" '
                'style="display:block;max-width:100%;max-height:44%;object-fit:contain;margin:0 auto 6px">'
            )

        width, height = option.width, option.height
        rendered.append(
            f'<a class="ap-ad-card ap-ad-{kind}" href="{link}" target="_blank" '
            'rel="sponsored noopener noreferrer" '
            f'data-ad-id="{creative.id}" data-kind="{kind}" data-format="{fmt_code}" '
            f'data-x="{x}" data-y="{y}" data-width="{width}" data-height="{height}" '
            f'data-impression-id="{html.escape(token, quote=True)}" '
            f'style="position:absolute;left:{x}px;top:{y}px;width:{width}px;height:{height}px;'
            'box-sizing:border-box;overflow:hidden;display:flex;flex-direction:column;'
            'justify-content:center;align-items:center;text-align:center;gap:4px;'
            'padding:10px;border:1px solid #ced9e4;border-radius:8px;background:#fff;'
            'color:#1f3347;text-decoration:none;font:14px/1.35 system-ui,sans-serif">'
            '<span style="position:absolute;left:7px;top:4px;font-size:9px;letter-spacing:.04em;'
            'text-transform:uppercase;color:#6b7b8c">Publicidad</span>'
            f'{image_html}<strong style="display:block;max-width:100%;overflow-wrap:anywhere">{title}</strong>'
            f'<span style="display:block;max-width:100%;overflow-wrap:anywhere">{body}</span>'
            f'<span style="display:block;font-size:11px;color:#2367a8">{html.escape(creative.destination_url, quote=True)}</span>'
            "</a>"
        )
    return (
        '<div class="ap-layout" data-layout-status="ok" '
        f'data-layout="{html.escape(layout.orientation, quote=True)}" '
        f'data-ad-count="{count}" data-area-width="{area_width}" data-area-height="{area_height}" '
        f'data-layout-width="{layout.width}" data-layout-height="{layout.height}" '
        f'style="position:relative;width:{area_width}px;height:{area_height}px;max-width:100%;'
        'overflow:hidden;box-sizing:border-box;background:#f4f7fa;'
        'border:1px solid #d7e0e9">'
        + "".join(rendered)
        + "</div>"
    )


@router.post("/compose", response_class=HTMLResponse, dependencies=[Depends(require_service_token)])
def compose_ads(request: ComposeAdRequest, db: Session = Depends(get_db)) -> HTMLResponse:
    """Select one or more ads, calculate a bounded layout, render HTML and count views now."""
    now = datetime.now(timezone.utc)
    fixed_format: AdFormat | None = None
    area = request.area

    if request.mode == "fixed_format":
        fixed_format = db.scalar(
            select(AdFormat).where(
                AdFormat.code == request.format_code,
                AdFormat.is_active.is_(True),
            )
        )
        if fixed_format is None:
            raise HTTPException(status_code=404, detail="Unknown or inactive ad format")
        if fixed_format.device not in {"both", request.device}:
            return HTMLResponse(
                _render_layout_html(None, AdArea(width=fixed_format.width, height=fixed_format.height), request, db, now)
            )
        area = AdArea(width=fixed_format.width, height=fixed_format.height)
        max_ads = 1
    else:
        assert area is not None
        max_ads = 1 if request.creative_id is not None else request.max_ads

    assert area is not None
    options = _compose_options(db, request, area, now, fixed_format)
    if fixed_format is not None:
        exact_options = [option for option in options if option.ad_format.id == fixed_format.id]
        selected = next(
            (option for is_house in (False, True) for option in exact_options if option.campaign.is_house_ad == is_house),
            None,
        )
        layout = (
            _Layout("single", (selected,), 1.0, fixed_format.width, fixed_format.height)
            if selected is not None
            else None
        )
    else:
        layout = _choose_layout(
            options,
            area,
            max_ads,
            request.gap,
            request.orientation,
            _brand_conflicts(db),
        )

    if layout is None:
        return HTMLResponse(_render_layout_html(None, area, request, db, now))

    # Persist only individual deliveries/events. No composition record is created.
    markup = _render_layout_html(layout, area, request, db, now)
    # Commit the delivery/impression rows only after a complete HTML fragment exists.
    db.commit()
    return HTMLResponse(markup)


@router.post("/serve", response_model=AdPayload, dependencies=[Depends(require_service_token)])
def serve_ad(request: ServeAdRequest, db: Session = Depends(get_db)) -> AdPayload:
    now = datetime.now(timezone.utc)
    rows = db.execute(
        select(Creative, Campaign)
        .join(Campaign, Campaign.id == Creative.campaign_id)
        .where(Creative.status == "approved")
        .order_by(Campaign.priority.desc(), Creative.id.asc())
    ).all()
    last_seen = _latest_creative_deliveries(
        db, {creative.id for creative, _ in rows}, request, now
    )
    rows = sorted(
        rows,
        key=lambda pair: (
            pair[1].is_house_ad,
            -pair[1].priority,
            _last_shown_sort_value(last_seen.get(pair[0].id)),
            pair[0].id,
        ),
    )
    temporally_suppressed = _campaigns_in_cooldown(
        db, [campaign for _, campaign in rows], request, now
    )
    active_brands = _active_brand_ids(
        db, {campaign.id for _, campaign in rows}, rows
    )

    selected: tuple[Creative, Campaign, AdFormat | None] | None = None
    size_requested = request.format.width is not None and request.format.height is not None
    requested_catalog_format: AdFormat | None = None
    if size_requested:
        requested_catalog_format = db.scalar(
            select(AdFormat).where(
                AdFormat.is_active.is_(True),
                AdFormat.width == request.format.width,
                AdFormat.height == request.format.height,
                AdFormat.device.in_(("both", request.device)),
            )
        )

    # A creative can support more than one standard size (for example, the OSAP
    # background banner has desktop and mobile variants). Prefer an exact active
    # size match, and only use unassigned generic creatives as fallback.
    for house_pass in (False, True):
        size_passes = (True, False) if size_requested else (False,)
        for exact_size_pass in size_passes:
            for creative, campaign in rows:
                if campaign.is_house_ad != house_pass or not _campaign_is_current(campaign, now):
                    continue
                if campaign.id in temporally_suppressed:
                    continue
                if campaign.brand_id is not None and campaign.brand_id not in active_brands:
                    continue
                if creative.format not in {request.format.type, "responsive"}:
                    continue
                if creative.language not in {request.page.language, "mul", "es"}:
                    continue

                assigned_formats = list(creative.ad_formats)
                matched_format: AdFormat | None = None
                if size_requested:
                    if exact_size_pass:
                        matched_format = next(
                            (
                                ad_format
                                for ad_format in assigned_formats
                                if ad_format.is_active
                                and ad_format.width == request.format.width
                                and ad_format.height == request.format.height
                                and ad_format.device in {"both", request.device}
                            ),
                            None,
                        )
                        if matched_format is None:
                            continue
                    elif assigned_formats:
                        # Do not deliver a fixed-size creative into the wrong slot.
                        continue
                    else:
                        # A generic house ad can still fill a known requested slot;
                        # record that slot in history even though the creative is reusable.
                        matched_format = requested_catalog_format
                elif assigned_formats:
                    # Old integrations that send no dimensions can keep using
                    # unassigned generic creatives until they start declaring a slot size.
                    continue

                if not _matches_targeting(db, creative.id, request):
                    continue
                try:
                    validate_destination(creative.destination_url)
                except ValueError:
                    continue
                selected = (creative, campaign, matched_format)
                break
            if selected:
                break
        if selected:
            break

    if selected is None:
        raise HTTPException(status_code=503, detail="No compatible commercial or house ad configured")

    creative, campaign, matched_format = selected
    token = secrets.token_urlsafe(32)
    delivery = AdDelivery(
        token=token,
        creative_id=creative.id,
        campaign_id=campaign.id,
        application=request.application,
        page_type=request.page.type,
        entity_type=request.page.entity_type,
        entity_id=request.page.entity_id,
        placement=request.placement,
        language=request.page.language,
        ad_format_id=matched_format.id if matched_format is not None else None,
    )
    db.add(delivery)
    db.commit()
    db.refresh(delivery)

    settings = get_settings()
    return AdPayload(
        ad_id=creative.id,
        impression_id=token,
        kind="house" if campaign.is_house_ad else "commercial",
        format=creative.format,
        title=creative.title,
        body=creative.body,
        image_url=creative.image_url,
        alt_text=creative.alt_text,
        language=creative.language,
        click_url=f"{settings.public_base_url.rstrip('/')}/r/{token}",
        is_house_ad=campaign.is_house_ad,
        ad_format_code=matched_format.code if matched_format is not None else None,
        ad_format_name=matched_format.name if matched_format is not None else None,
        ad_width=matched_format.width if matched_format is not None else None,
        ad_height=matched_format.height if matched_format is not None else None,
    )
