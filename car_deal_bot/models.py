from __future__ import annotations

from pydantic import BaseModel, Field


class VehicleListing(BaseModel):
    source: str = Field(description="e.g. mobile.de, autoscout24")
    external_id: str
    title: str
    price_eur: float | None = None
    currency: str = "EUR"
    mileage_km: int | None = None
    year: int | None = None
    make: str | None = None
    model: str | None = None
    url: str
    location: str | None = None
    deal_score: float | None = None  # set by ranker; positive = below expected price

    @property
    def price_per_km(self) -> float | None:
        if self.price_eur is None or not self.mileage_km or self.mileage_km <= 0:
            return None
        return self.price_eur / self.mileage_km


class SearchParams(BaseModel):
    country: str = "DE"
    price_min_eur: float | None = None
    price_max_eur: float | None = None
    year_min: int | None = None
    year_max: int | None = None
    mileage_max_km: int | None = None
    make: str | None = None
    model: str | None = None
    autoscout_make_slug: str | None = None
    autoscout_model_slug: str | None = None
    mobilede_make_id: str | None = None
    mobilede_model_id: str | None = None
