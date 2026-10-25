"""Request/response contracts for ad serving and impression confirmation."""

from pydantic import BaseModel, Field


class PageContext(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="es", min_length=2, max_length=12)


class FormatRequest(BaseModel):
    type: str = Field(default="text", min_length=1, max_length=30)
    width: int | None = Field(default=None, ge=1, le=5000)
    height: int | None = Field(default=None, ge=1, le=5000)


class ServeAdRequest(BaseModel):
    application: str = Field(default="osap", min_length=1, max_length=80)
    page: PageContext
    placement: str = Field(min_length=1, max_length=80)
    format: FormatRequest = Field(default_factory=FormatRequest)
    device: str = Field(default="desktop", max_length=30)


class AdPayload(BaseModel):
    ad_id: int
    impression_id: str
    kind: str
    format: str
    title: str
    body: str | None
    image_url: str | None
    alt_text: str | None
    language: str
    click_url: str
    is_house_ad: bool


class ImpressionRequest(BaseModel):
    impression_id: str = Field(min_length=32, max_length=64)
