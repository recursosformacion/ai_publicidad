"""Persistence models for the first functional advertising prototype."""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    BigInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


creative_ad_formats = Table(
    "creative_ad_formats",
    Base.metadata,
    Column(
        "creative_id",
        Integer,
        ForeignKey("creatives.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "ad_format_id",
        Integer,
        ForeignKey("ad_formats.id", ondelete="RESTRICT"),
        primary_key=True,
    ),
)


class AdFormat(Base):
    """Catalog entry for a standardized ad slot size and its placement guidance."""

    __tablename__ = "ad_formats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    device: Mapped[str] = mapped_column(String(20), default="both", nullable=False)
    category: Mapped[str] = mapped_column(String(30), default="banner", nullable=False)
    placement_notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    creatives: Mapped[list["Creative"]] = relationship(
        secondary=creative_ad_formats,
        back_populates="ad_formats",
    )


brand_competitors = Table(
    "brand_competitors",
    Base.metadata,
    Column(
        "brand_left_id",
        Integer,
        ForeignKey("brands.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "brand_right_id",
        Integer,
        ForeignKey("brands.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    CheckConstraint(
        "brand_left_id < brand_right_id",
        name="ck_brand_competitors_canonical_pair",
    ),
)


class Brand(Base):
    """Registered advertiser brand; competitor links prevent conflicting ads in one block."""

    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True, index=True)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Advertiser(Base):
    """Commercial client that owns advertising orders."""
    __tablename__ = "advertisers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    legal_name: Mapped[str | None] = mapped_column(String(240))
    contact_name: Mapped[str | None] = mapped_column(String(160))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(60))
    website_url: Mapped[str | None] = mapped_column(String(2048))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AdOrder(Base):
    """Commercial order/contract with budget, billing model and delivery limits."""
    __tablename__ = "ad_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    advertiser_id: Mapped[int] = mapped_column(ForeignKey("advertisers.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency: Mapped[str] = mapped_column(String(3), default="EUR", nullable=False)
    billing_model: Mapped[str] = mapped_column(String(10), default="fixed", nullable=False)
    fixed_fee_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_budget_cents: Mapped[int | None] = mapped_column(Integer)
    daily_budget_cents: Mapped[int | None] = mapped_column(Integer)
    cpm_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cpc_cents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    impression_limit_total: Mapped[int | None] = mapped_column(Integer)
    impression_limit_daily: Mapped[int | None] = mapped_column(Integer)
    click_limit_total: Mapped[int | None] = mapped_column(Integer)
    click_limit_daily: Mapped[int | None] = mapped_column(Integer)
    pacing_mode: Mapped[str] = mapped_column(String(10), default="none", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_house_ad: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    brand_id: Mapped[int | None] = mapped_column(ForeignKey("brands.id", ondelete="SET NULL"))
    minimum_interval_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("ad_orders.id", ondelete="SET NULL"))
    max_impressions_total: Mapped[int | None] = mapped_column(Integer)
    max_impressions_daily: Mapped[int | None] = mapped_column(Integer)
    max_clicks_total: Mapped[int | None] = mapped_column(Integer)
    max_clicks_daily: Mapped[int | None] = mapped_column(Integer)
    max_impressions_per_visitor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    visitor_interval_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class Creative(Base):
    __tablename__ = "creatives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    alt_text: Mapped[str | None] = mapped_column(String(300))
    format: Mapped[str] = mapped_column(String(30), default="text", nullable=False)
    language: Mapped[str] = mapped_column(String(12), default="es", nullable=False)
    destination_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="approved", nullable=False)
    ad_formats: Mapped[list[AdFormat]] = relationship(
        secondary=creative_ad_formats,
        back_populates="creatives",
        order_by="AdFormat.width, AdFormat.height",
    )

    @property
    def ad_format_ids(self) -> list[int]:
        return [ad_format.id for ad_format in self.ad_formats]


class TargetingRule(Base):
    __tablename__ = "targeting_rules"
    __table_args__ = (UniqueConstraint("creative_id", "rule_type", "rule_value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    creative_id: Mapped[int] = mapped_column(ForeignKey("creatives.id"), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(30), nullable=False)
    rule_value: Mapped[str] = mapped_column(String(200), nullable=False)
    effect: Mapped[str] = mapped_column(String(10), default="include", nullable=False)


class AdDelivery(Base):
    __tablename__ = "ad_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    creative_id: Mapped[int] = mapped_column(ForeignKey("creatives.id"), nullable=False)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), nullable=False)
    application: Mapped[str] = mapped_column(String(80), nullable=False)
    page_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(160))
    placement: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(12), nullable=False)
    ad_format_id: Mapped[int | None] = mapped_column(
        ForeignKey("ad_formats.id", name="fk_ad_deliveries_ad_format_id", ondelete="RESTRICT")
    )
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    visitor_key_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    impression_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    impression_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdEvent(Base):
    __tablename__ = "ad_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    delivery_id: Mapped[int] = mapped_column(ForeignKey("ad_deliveries.id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    deduplication_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    charge_microcents: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
