from __future__ import annotations

import logging
import statistics
from datetime import date

from car_deal_bot.config_loader import AppConfig
from car_deal_bot.models import VehicleListing

logger = logging.getLogger(__name__)

CURRENT_YEAR = date.today().year


_DAMAGE_KEYWORDS = [
    "motorschaden", "unfallwagen", "unfallfrei nicht", "bastlerfahrzeug",
    "defekt", "nicht fahrbereit", "engine damage", "for parts",
    "getriebeschaden", "totalschaden",
]


def dedupe(listings: list[VehicleListing]) -> list[VehicleListing]:
    seen: set[tuple[str, str]] = set()
    out: list[VehicleListing] = []
    for v in listings:
        key = (v.source, v.external_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _exclude_damaged(listings: list[VehicleListing]) -> list[VehicleListing]:
    """Remove listings whose title contains damage keywords."""
    out: list[VehicleListing] = []
    for v in listings:
        title_lower = v.title.lower()
        if any(kw in title_lower for kw in _DAMAGE_KEYWORDS):
            continue
        out.append(v)
    return out


# ---------------------------------------------------------------------------
# Deal scoring
# ---------------------------------------------------------------------------
# A "deal score" measures how far below the expected price a listing is,
# given its year and mileage compared to the other listings in the batch.
#
# Steps:
#   1.  For each listing with price, year, mileage — compute a normalised
#       "value factor" = (car_age / median_age) + (mileage / median_mileage).
#       Older + higher-mileage cars should be cheaper.
#   2.  Fit a simple expected_price = base * value_factor regression.
#   3.  deal_score = (expected_price - actual_price) / expected_price * 100
#       → positive = below expected (good deal), negative = above.
#
# The score is attached to each listing so notification can display it.
# ---------------------------------------------------------------------------

def _compute_deal_scores(listings: list[VehicleListing]) -> None:
    """Mutates listing.deal_score in-place."""
    scorable = [
        v for v in listings
        if v.price_eur is not None and v.price_eur > 0
        and v.year is not None and v.year > 0
        and v.mileage_km is not None and v.mileage_km > 0
    ]

    if len(scorable) < 3:
        # Not enough data for meaningful regression; score by price/km only
        for v in listings:
            if v.price_per_km is not None:
                median_ppk = statistics.median(
                    [x.price_per_km for x in listings if x.price_per_km is not None]
                )
                if median_ppk > 0:
                    v.deal_score = round((1.0 - v.price_per_km / median_ppk) * 100, 1)
        return

    ages = [CURRENT_YEAR - v.year for v in scorable]
    mileages = [v.mileage_km for v in scorable]
    prices = [v.price_eur for v in scorable]

    med_age = statistics.median(ages) or 1
    med_km = statistics.median(mileages) or 1

    # value_factor: higher → older/more-km → should be cheaper
    def value_factor(age: int | float, km: int | float) -> float:
        return 0.5 * (age / med_age) + 0.5 * (km / med_km)

    factors = [value_factor(a, k) for a, k in zip(ages, mileages)]

    # Simple linear fit: expected_price ≈ base_price / (1 + factor)
    # Estimate base_price from data so that total error is minimised.
    base_estimates = [p * (1 + f) for p, f in zip(prices, factors)]
    base_price = statistics.median(base_estimates)

    for v in listings:
        if v.price_eur is None or v.price_eur <= 0:
            continue
        age = CURRENT_YEAR - v.year if v.year else med_age
        km = v.mileage_km if v.mileage_km else med_km
        expected = base_price / (1 + value_factor(age, km))
        v.deal_score = round((expected - v.price_eur) / expected * 100, 1)


def rank_listings(listings: list[VehicleListing], app: AppConfig) -> list[VehicleListing]:
    items = dedupe(listings)
    items = _exclude_damaged(items)
    _compute_deal_scores(items)

    strategy = app.ranking.strategy

    if strategy == "lowest_price_per_km":
        items.sort(key=lambda x: (
            x.price_per_km is None,
            x.price_per_km if x.price_per_km is not None else float("inf"),
        ))
    elif strategy == "newest_first":
        items.sort(key=lambda x: (
            x.year is None,
            -(x.year or 0),
        ))
    elif strategy == "best_deal":
        items.sort(key=lambda x: (
            x.deal_score is None,
            -(x.deal_score if x.deal_score is not None else float("-inf")),
        ))
    else:
        items.sort(key=lambda x: (
            x.price_eur is None,
            x.price_eur if x.price_eur is not None else float("inf"),
        ))

    # Apply deal threshold: only keep listings at or above the minimum score
    min_score = app.ranking.min_deal_score
    if min_score is not None:
        before = len(items)
        items = [v for v in items if v.deal_score is not None and v.deal_score >= min_score]
        if len(items) < before:
            logger.info(
                "Deal filter: %s/%s listings passed (min_deal_score=%s).",
                len(items), before, min_score,
            )

    return items[: app.ranking.top_n]
