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

    @model_validator(mode="after")
    def validate_dates(self) -> "CampaignInput":
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at debe ser posterior a starts_at")
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
