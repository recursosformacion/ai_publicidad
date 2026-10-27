"""Validated input and output schemas for the administrative API."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from application.security import validate_destination


CampaignStatus = Literal["draft", "active", "paused", "completed", "cancelled", "archived"]
CreativeStatus = Literal["draft", "approved", "paused", "rejected", "archived"]
CreativeFormat = Literal["image", "text", "image_text", "responsive"]
RuleType = Literal["application", "page_type", "placement", "language", "entity_type", "entity_id"]
RuleEffect = Literal["include", "exclude"]
AdFormatDevice = Literal["desktop", "mobile", "both"]
AdFormatCategory = Literal["banner", "rectangle", "square", "skyscraper", "video", "other"]


class BrandInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    website_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool = True
    competitor_brand_ids: list[int] = Field(default_factory=list, max_length=100)

    @field_validator("website_url")
    @classmethod
    def validate_website_url(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_destination(value)
        except ValueError as exc:
            raise ValueError("website_url debe ser una URL HTTP(S) válida") from exc

    @field_validator("competitor_brand_ids")
    @classmethod
    def validate_competitors(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Los identificadores de marca deben ser positivos")
        if len(set(values)) != len(values):
            raise ValueError("No se puede repetir una marca competidora")
        return values


class BrandRead(BaseModel):
    id: int
    name: str
    website_url: str | None = None
    notes: str | None = None
    is_active: bool
    competitor_brand_ids: list[int] = Field(default_factory=list)


class AdvertiserInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    legal_name: str | None = Field(default=None, max_length=240)
    contact_name: str | None = Field(default=None, max_length=160)
    contact_email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=60)
    website_url: str | None = Field(default=None, max_length=2048)
    notes: str | None = Field(default=None, max_length=4000)
    status: Literal["active", "paused", "archived"] = "active"

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("El nombre del anunciante no puede estar vacío")
        return result

    @field_validator("website_url")
    @classmethod
    def validate_advertiser_website(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        try:
            return validate_destination(value)
        except ValueError as exc:
            raise ValueError("website_url debe ser una URL HTTP(S) válida") from exc

    @field_validator("contact_email")
    @classmethod
    def validate_contact_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        result = value.strip()
        if "@" not in result or result.startswith("@") or result.endswith("@"):
            raise ValueError("contact_email no parece una dirección de correo válida")
        return result


class AdvertiserRead(AdvertiserInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class AdOrderInput(BaseModel):
    advertiser_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=180)
    reference: str | None = Field(default=None, max_length=100)
    status: Literal["draft", "active", "paused", "completed", "cancelled", "archived"] = "draft"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    currency: str = Field(default="EUR", pattern=r"^[A-Z]{3}$")
    billing_model: Literal["cpm", "cpc", "fixed"] = "fixed"
    fixed_fee_cents: int = Field(default=0, ge=0, le=2_000_000_000)
    total_budget_cents: int | None = Field(default=None, ge=1, le=2_000_000_000)
    daily_budget_cents: int | None = Field(default=None, ge=1, le=2_000_000_000)
    cpm_cents: int = Field(default=0, ge=0, le=2_000_000_000)
    cpc_cents: int = Field(default=0, ge=0, le=2_000_000_000)
    impression_limit_total: int | None = Field(default=None, ge=1, le=2_000_000_000)
    impression_limit_daily: int | None = Field(default=None, ge=1, le=2_000_000_000)
    click_limit_total: int | None = Field(default=None, ge=1, le=2_000_000_000)
    click_limit_daily: int | None = Field(default=None, ge=1, le=2_000_000_000)
    pacing_mode: Literal["none", "even"] = "none"

    @model_validator(mode="after")
    def validate_order_terms(self) -> "AdOrderInput":
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
        if self.billing_model == "cpm" and self.cpm_cents <= 0:
            raise ValueError("Un pedido CPM requiere cpm_cents mayor que cero")
        if self.billing_model == "cpc" and self.cpc_cents <= 0:
            raise ValueError("Un pedido CPC requiere cpc_cents mayor que cero")
        if self.billing_model == "fixed" and (
            self.total_budget_cents is not None or self.daily_budget_cents is not None or self.pacing_mode != "none"
        ):
            raise ValueError("Presupuesto variable y pacing solo están disponibles para pedidos CPM/CPC")
        if self.daily_budget_cents is not None and self.total_budget_cents is not None and self.daily_budget_cents > self.total_budget_cents:
            raise ValueError("El presupuesto diario no puede superar el presupuesto total")
        if self.pacing_mode == "even" and (self.total_budget_cents is None or self.starts_at is None or self.ends_at is None):
            raise ValueError("El pacing uniforme requiere presupuesto total y fechas")
        return self


class AdOrderRead(AdOrderInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class AdFormatInput(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=2, max_length=120)
    width: int = Field(gt=0, le=5000)
    height: int = Field(gt=0, le=5000)
    device: AdFormatDevice = "both"
    category: AdFormatCategory = "banner"
    placement_notes: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class AdFormatRead(AdFormatInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CampaignInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    status: CampaignStatus = "draft"
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    priority: int = Field(default=0, ge=-100000, le=100000)
    is_house_ad: bool = False
    brand_id: int | None = Field(default=None, gt=0)
    minimum_interval_seconds: int = Field(default=0, ge=0, le=2592000)
    order_id: int | None = Field(default=None, gt=0)
    max_impressions_total: int | None = Field(default=None, ge=1, le=2_000_000_000)
    max_impressions_daily: int | None = Field(default=None, ge=1, le=2_000_000_000)
    max_clicks_total: int | None = Field(default=None, ge=1, le=2_000_000_000)
    max_clicks_daily: int | None = Field(default=None, ge=1, le=2_000_000_000)
    max_impressions_per_visitor: int = Field(default=0, ge=0, le=2_000_000_000)
    visitor_interval_seconds: int = Field(default=0, ge=0, le=2592000)

    @model_validator(mode="after")
    def validate_dates(self) -> "CampaignInput":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
        if self.is_house_ad and self.order_id is not None:
            raise ValueError("Una campaña propia de OSAP no puede asociarse a un pedido comercial")
        return self


class CampaignRead(CampaignInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class CreativeInput(BaseModel):
    campaign_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    body: str | None = None
    image_url: str | None = None
    alt_text: str | None = Field(default=None, max_length=300)
    format: CreativeFormat = "text"
    language: str = Field(default="es", min_length=2, max_length=12)
    destination_url: str = Field(min_length=1, max_length=2048)
    status: CreativeStatus = "draft"
    ad_format_ids: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("ad_format_ids")
    @classmethod
    def validate_ad_format_ids(cls, values: list[int]) -> list[int]:
        if any(value <= 0 for value in values):
            raise ValueError("Los identificadores de formato deben ser positivos")
        if len(set(values)) != len(values):
            raise ValueError("No se puede asignar dos veces el mismo formato a un anuncio")
        return values

    @field_validator("destination_url")
    @classmethod
    def validate_destination_url(cls, value: str) -> str:
        try:
            return validate_destination(value)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_image_fields(self) -> "CreativeInput":
        if self.format in {"image", "image_text"} and not self.image_url:
            raise ValueError("Los formatos image e image_text requieren image_url")
        if self.image_url and not self.alt_text:
            raise ValueError("Las creatividades con imagen requieren alt_text")
        if self.image_url:
            try:
                validate_destination(self.image_url)
            except ValueError as exc:
                raise ValueError("image_url debe ser una URL HTTP(S) válida") from exc
        return self


class CreativeRead(CreativeInput):
    model_config = ConfigDict(from_attributes=True)
    id: int




class TargetingRuleInput(BaseModel):
    creative_id: int = Field(gt=0)
    rule_type: RuleType
    rule_value: str = Field(min_length=1, max_length=200)
    effect: RuleEffect = "include"


class TargetingRuleRead(TargetingRuleInput):
    model_config = ConfigDict(from_attributes=True)
    id: int


class AdDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    token: str
    creative_id: int
    campaign_id: int
    ad_format_id: int | None = None
    application: str
    page_type: str
    entity_type: str | None
    entity_id: str | None
    placement: str
    language: str
    delivered_at: datetime
    impression_confirmed: bool
    impression_confirmed_at: datetime | None


class AdEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    delivery_id: int
    event_type: str
    occurred_at: datetime
    deduplication_key: str | None
    charge_microcents: int = 0
