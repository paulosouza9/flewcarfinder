from __future__ import annotations

import json
import logging
import re
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from car_deal_bot.config_loader import AppConfig
from car_deal_bot.models import SearchParams, VehicleListing
from car_deal_bot.sources.base import ListingSource

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

_BASE = "https://www.autoscout24.com"


def _slug(s: str) -> str:
    return s.lower().replace(" ", "-").replace("/", "-")


def _build_url(params: SearchParams, country_code: str, page: int) -> str:
    make_slug = params.autoscout_make_slug or (_slug(params.make) if params.make else None)
    model_slug = params.autoscout_model_slug or (_slug(params.model) if params.model else None)

    path_parts = ["lst"]
    if make_slug:
        path_parts.append(make_slug)
    if model_slug:
        path_parts.append(model_slug)

    q: dict[str, Any] = {
        "atype": "C",
        "desc": "1",
        "sort": "age",
        "ustate": "N,U",
        "cy": country_code,
    }
    if params.price_min_eur is not None:
        q["pricefrom"] = int(params.price_min_eur)
    if params.price_max_eur is not None:
        q["priceto"] = int(params.price_max_eur)
    if params.year_min is not None:
        q["fregfrom"] = params.year_min
    if params.year_max is not None:
        q["fregto"] = params.year_max
    if params.mileage_max_km is not None:
        q["kmto"] = params.mileage_max_km
    if page > 1:
        q["page"] = page

    path = "/".join(path_parts)
    return f"{_BASE}/{path}?{urlencode(q)}"


# ---------------------------------------------------------------------------
# __NEXT_DATA__ extraction (updated for current autoscout24 structure)
# ---------------------------------------------------------------------------

def _extract_page_data(html: str) -> tuple[list[dict[str, Any]], int]:
    """Return (listings, total_pages) from the __NEXT_DATA__ JSON."""
    soup = BeautifulSoup(html, "html.parser")
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag:
        return [], 0
    try:
        nd = json.loads(tag.string or "")
    except (json.JSONDecodeError, TypeError):
        return [], 0

    page_props = nd.get("props", {}).get("pageProps", {})
    listings = page_props.get("listings", [])
    total_pages = page_props.get("numberOfPages", 1)

    if not isinstance(listings, list):
        listings = []
    return listings, int(total_pages) if total_pages else 1


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _parse_price_str(s: Any) -> float | None:
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    digits = re.sub(r"[^\d]", "", str(s))
    return float(digits) if digits else None


def _parse_reg_year(s: Any) -> int | None:
    if s is None:
        return None
    m = re.search(r"(19|20)\d{2}", str(s))
    return int(m.group()) if m else None


def _parse_listing(raw: dict[str, Any]) -> VehicleListing | None:
    ext_id = str(raw.get("id") or "")
    if not ext_id:
        return None

    # --- URL ---
    url = raw.get("url") or ""
    if isinstance(url, str) and url.startswith("/"):
        url = _BASE + url
    if not url:
        url = f"{_BASE}/offers/-/{ext_id}"

    # --- Price ---
    # Primary: tracking.price is a clean numeric string
    tracking = raw.get("tracking") if isinstance(raw.get("tracking"), dict) else {}
    price_eur = _safe_float(tracking.get("price"))
    # Fallback: price.priceFormatted
    if price_eur is None:
        price_obj = raw.get("price")
        if isinstance(price_obj, dict):
            price_eur = _parse_price_str(price_obj.get("priceFormatted"))

    # --- Vehicle ---
    vehicle = raw.get("vehicle") if isinstance(raw.get("vehicle"), dict) else {}
    make = vehicle.get("make")
    model_group = vehicle.get("modelGroup") or vehicle.get("model")
    model_version = vehicle.get("modelVersionInput") or ""

    # --- Mileage ---
    mileage_km = _safe_int(tracking.get("mileage"))
    if mileage_km is None:
        mileage_km = _safe_int(re.sub(r"[^\d]", "", vehicle.get("mileageInKm") or "") or None)

    # --- Year ---
    year = _parse_reg_year(tracking.get("firstRegistration"))
    if year is None:
        for detail in raw.get("vehicleDetails", []):
            if isinstance(detail, dict) and detail.get("ariaLabel") == "First registration":
                year = _parse_reg_year(detail.get("data"))
                break

    # --- Title ---
    make_str = make or ""
    title = f"{make_str} {model_version}".strip() if model_version else f"{make_str} {model_group or ''}".strip()
    if not title:
        title = f"Ad {ext_id}"

    # --- Location ---
    loc_obj = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    location = loc_obj.get("city") if loc_obj else None

    return VehicleListing(
        source="autoscout24",
        external_id=ext_id,
        title=str(title),
        price_eur=price_eur,
        mileage_km=mileage_km,
        year=year,
        make=str(make) if make else None,
        model=str(model_group) if model_group else None,
        url=str(url),
        location=str(location) if location else None,
    )


_MAX_PAGES_HARD_LIMIT = 20  # never go beyond this regardless of config


class AutoscoutSource(ListingSource):
    name = "autoscout24"

    def fetch(self, params: SearchParams, app: AppConfig) -> list[VehicleListing]:
        return self.fetch_until(params, app)

    def fetch_until(
        self,
        params: SearchParams,
        app: AppConfig,
        *,
        needed: int | None = None,
        seen_keys: set[str] | None = None,
    ) -> list[VehicleListing]:
        """Fetch pages until we have at least `needed` new (unseen) listings,
        or we run out of pages. If `needed` is None, fetch up to max_pages."""
        from car_deal_bot.memory import is_new as _is_new

        cfg = app.sources.autoscout
        hard_limit = min(cfg.max_pages, _MAX_PAGES_HARD_LIMIT) if needed is None else _MAX_PAGES_HARD_LIMIT
        listings: list[VehicleListing] = []
        new_count = 0
        total_pages = 1

        with httpx.Client(headers=_HEADERS, timeout=60.0, follow_redirects=True) as client:
            page = 0
            while True:
                page += 1
                if page > hard_limit or page > total_pages:
                    break

                url = _build_url(params, cfg.country_code, page)
                logger.debug("autoscout24 fetching page %s: %s", page, url)

                try:
                    r = client.get(url)
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    logger.error("autoscout24 HTTP %s on page %s", exc.response.status_code, page)
                    break
                except httpx.RequestError as exc:
                    logger.error("autoscout24 request failed on page %s: %s", page, exc)
                    break

                raw_listings, pages = _extract_page_data(r.text)
                if page == 1:
                    total_pages = pages

                if not raw_listings:
                    logger.debug("autoscout24: no listings on page %s.", page)
                    break

                page_count = 0
                for raw in raw_listings:
                    if not isinstance(raw, dict):
                        continue
                    parsed = _parse_listing(raw)
                    if parsed:
                        listings.append(parsed)
                        page_count += 1
                        if seen_keys is not None and _is_new(parsed, seen_keys):
                            new_count += 1

                logger.info(
                    "autoscout24 page %s/%s: %s listings (total new so far: %s).",
                    page, total_pages, page_count,
                    new_count if seen_keys is not None else "?",
                )

                if needed is not None and seen_keys is not None and new_count >= needed:
                    logger.info("autoscout24: found enough new listings, stopping.")
                    break

                if page >= total_pages:
                    break
                time.sleep(1.5)

        return listings
