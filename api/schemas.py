"""Request/response contracts for ad serving and impression confirmation."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class PageContext(BaseModel):
    type: str = Field(min_length=1, max_length=80)
    entity_type: str | None = Field(default=None, max_length=80)
    entity_id: str | None = Field(default=None, max_length=160)
    language: str = Field(default="es", min_length=2, max_length=12)


class FormatRequest(BaseModel):
    type: str = Field(default="text", min_length=1, max_length=30)
    width: int | None = Field(default=None, ge=1, le=5000)
    height: int | None = Field(default=None, ge=1, le=5000)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "FormatRequest":
        if (self.width is None) != (self.height is None):
            raise ValueError("width y height deben indicarse juntos para elegir un formato estándar")
        return self


class ServeAdRequest(BaseModel):
    application: str = Field(default="osap", min_length=1, max_length=80)
    page: PageContext
    placement: str = Field(min_length=1, max_length=80)
    format: FormatRequest = Field(default_factory=FormatRequest)
    device: str = Field(default="desktop", max_length=30)


class AdArea(BaseModel):
    width: int = Field(gt=0, le=2000, description="Ancho disponible en píxeles CSS")
    height: int = Field(gt=0, le=1200, description="Alto disponible en píxeles CSS")


class ComposeAdRequest(BaseModel):
    application: str = Field(default="osap", min_length=1, max_length=80)
    page: PageContext
    placement: str = Field(min_length=1, max_length=80)
    device: Literal["desktop", "mobile", "tablet"] = "desktop"
    mode: Literal["auto_area", "fixed_format"] = "auto_area"
    area: AdArea | None = None
    format_code: str | None = Field(default=None, min_length=2, max_length=50)
    max_ads: int = Field(default=3, ge=1, le=3)
    gap: int = Field(default=12, ge=0, le=32)
    orientation: Literal["auto", "row", "column"] = "auto"

    @model_validator(mode="after")
    def validate_mode(self) -> "ComposeAdRequest":
        if self.mode == "auto_area" and self.area is None:
            raise ValueError("auto_area requiere area.width y area.height")
        if self.mode == "fixed_format" and not self.format_code:
            raise ValueError("fixed_format requiere format_code")
        return self


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
    ad_format_code: str | None = None
    ad_format_name: str | None = None
    ad_width: int | None = None
    ad_height: int | None = None


class ImpressionRequest(BaseModel):
    impression_id: str = Field(min_length=32, max_length=64)
