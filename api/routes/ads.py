"""Ad selection and simple area-aware HTML composition endpoints."""

import html
import itertools
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.schemas import AdArea, AdPayload, ComposeAdRequest, FormatRequest, ServeAdRequest
from application.security import require_service_token, validate_destination
from domain.models import AdDelivery, AdEvent, AdFormat, Campaign, Creative, TargetingRule
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
    context_request = _compose_context(request)
    options: list[_AdOption] = []

    for creative, campaign in rows:
        if not _campaign_is_current(campaign, now):
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
            # Unassigned responsive creatives are flexible and may use the requested format.
            options.append(_AdOption(creative, campaign, fixed_format))
            continue

        if assigned_formats:
            candidate_formats = assigned_formats
        else:
            # Unassigned responsive/text creatives are flexible, but still use a catalogued
            # size so both the layout and the delivery history have exact dimensions.
            candidate_formats = list(
                db.scalars(
                    select(AdFormat).where(
                        AdFormat.is_active.is_(True),
                        AdFormat.device.in_(("both", request.device)),
                    )
                ).all()
            )

        for ad_format in candidate_formats:
            if ad_format.device not in {"both", request.device}:
                continue
            if ad_format.width > area.width or ad_format.height > area.height:
                continue
            options.append(_AdOption(creative, campaign, ad_format))

    # Bound the runtime search. No generated layout is stored; candidates are rebuilt for
    # each request. At most 18 options means fewer than 1,000 three-item combinations.
    options.sort(
        key=lambda option: (
            option.campaign.is_house_ad,  # commercial before house ads
            -option.campaign.priority,
            option.creative.id,
            option.ad_format.width * option.ad_format.height,
        )
    )
    return options[:18]


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


def _layout_score(items: tuple[_AdOption, ...], area: AdArea, orientation: str, gap: int) -> float:
    width, height = _layout_dimensions(items, orientation, gap)
    used_area = sum(item.width * item.height for item in items)
    area_utilization = used_area / (area.width * area.height)
    # A modest bonus encourages useful combinations, but never beats a dramatically
    # better fit. Geometry is a hard constraint; commercial/house status is a tie-breaker.
    count_bonus = 0.065 * (len(items) - 1)
    types = {item.campaign.is_house_ad for item in items}
    commercial_bonus = 0.025 if types == {False} else 0.0
    mixed_penalty = 0.02 if len(types) > 1 else 0.0
    priority_bonus = sum(max(-100, min(100, item.campaign.priority)) for item in items)
    priority_bonus = priority_bonus / max(1, len(items)) * 0.00005
    orientation_bonus = 0.0001 if (
        (area.width >= area.height and orientation == "row")
        or (area.height > area.width and orientation == "column")
    ) else 0.0
    return area_utilization * 0.78 + count_bonus + commercial_bonus - mixed_penalty + priority_bonus + orientation_bonus


def _choose_layout(
    options: list[_AdOption],
    area: AdArea,
    max_ads: int,
    gap: int,
    requested_orientation: str,
) -> _Layout | None:
    if not options:
        return None
    orientations = (
        ("row", "column")
        if requested_orientation == "auto"
        else (requested_orientation,)
    )
    best: _Layout | None = None

    for count in range(1, min(max_ads, len(options), 3) + 1):
        for items in itertools.combinations(options, count):
            if len({item.creative.id for item in items}) != count:
                continue
            # Keep each combination deterministically ordered by candidate preference.
            for orientation in orientations:
                width, height = _layout_dimensions(items, orientation, gap)
                if width > area.width or height > area.height:
                    continue
                layout = _Layout(
                    orientation=orientation if count > 1 else "single",
                    items=items,
                    score=_layout_score(items, area, orientation, gap),
                    width=width,
                    height=height,
                )
                if best is None or layout.score > best.score:
                    best = layout
    return best


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
    db.commit()

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
        max_ads = request.max_ads

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
        layout = _choose_layout(options, area, max_ads, request.gap, request.orientation)

    if layout is None:
        return HTMLResponse(_render_layout_html(None, area, request, db, now))

    # Persist only individual deliveries/events. No composition record is created.
    markup = _render_layout_html(layout, area, request, db, now)
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
