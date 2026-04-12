from __future__ import annotations

import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

# curl_cffi impersonates Chrome's TLS fingerprint, bypassing Akamai bot detection.
# Install with: pip install curl_cffi
try:
    from curl_cffi import requests as _curl_requests  # type: ignore[import-untyped]
    _CURL_CFFI_AVAILABLE = True
except ImportError:
    _curl_requests = None  # type: ignore[assignment]
    _CURL_CFFI_AVAILABLE = False

from car_deal_bot.config_loader import AppConfig
from car_deal_bot.models import SearchParams, VehicleListing
from car_deal_bot.sources.base import ListingSource

logger = logging.getLogger(__name__)

# Realistic browser headers to avoid bot-detection
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

_BASE = "https://suchen.mobile.de"


def _slug_to_mobilede(s: str) -> str:
    """Best-effort conversion: 'BMW' stays 'BMW', '3 Series'→'3ER' is not deterministic.
    Users should set mobilede_make_id / mobilede_model_id in config.yaml for accuracy."""
    return s.upper().replace(" ", "-")


def _build_url(params: SearchParams, page: int) -> str:
    make_id = params.mobilede_make_id or (params.make or "")
    model_id = params.mobilede_model_id or ""

    q: dict[str, str] = {
        "isSearchRequest": "true",
        "scopeId": "C",           # C = cars
        "pageNumber": str(page),
        "sortOption.sortBy": "price",
        "sortOption.sortOrder": "ASCENDING",
    }
    if make_id:
        q["makeModelVariant1.makeId"] = make_id
    if model_id:
        q["makeModelVariant1.modelId"] = model_id
    if params.price_min_eur is not None:
        q["minPrice"] = str(int(params.price_min_eur))
    if params.price_max_eur is not None:
        q["maxPrice"] = str(int(params.price_max_eur))
    if params.year_min is not None:
        q["minFirstRegistrationDate"] = f"{params.year_min}-01-01"
    if params.year_max is not None:
        q["maxFirstRegistrationDate"] = f"{params.year_max}-12-31"
    if params.mileage_max_km is not None:
        q["maxMileage"] = str(params.mileage_max_km)
    return f"{_BASE}/fahrzeuge/search.html?{urlencode(q)}"


def _parse_price(text: str) -> float | None:
    """Extract a numeric EUR price from a price string like '24.900 €'."""
    import re
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        return float(digits)
    return None


def _parse_int(text: str) -> int | None:
    import re
    digits = re.sub(r"[^\d]", "", text)
    if digits:
        return int(digits)
    return None


def _parse_year(text: str) -> int | None:
    import re
    m = re.search(r"(19|20)\d{2}", text)
    if m:
        return int(m.group())
    return None


def _parse_listing(article: BeautifulSoup) -> VehicleListing | None:
    """Extract a VehicleListing from a single search-result article element.

    mobile.de renders each listing inside an <article> with data-mobile-id.
    CSS classes can change; this parser is intentionally flexible.

    Debug tip: if you get 0 results, run the bot with LOG_LEVEL=DEBUG set
    or call _dump_html() to inspect what the page actually returns.
    """
    # --- ID & URL ---
    listing_id = article.get("data-mobile-id") or article.get("id") or ""
    link_tag = article.find("a", href=True)
    if not link_tag:
        return None
    href: str = link_tag["href"]
    if href.startswith("/"):
        href = _BASE + href
    if not listing_id:
        # Fall back: extract ID from the URL path
        import re
        m = re.search(r"/(\d+)(?:\.html)?$", href)
        listing_id = m.group(1) if m else href

    # --- Title ---
    heading = article.find(["h2", "h3", "h4"])
    title = heading.get_text(strip=True) if heading else (
        link_tag.get_text(strip=True) or f"Ad {listing_id}"
    )

    # --- Price ---
    price_eur: float | None = None
    for cls in ("price-block__price", "preis", "price", "Price"):
        el = article.find(class_=lambda c: c and cls.lower() in c.lower())
        if el:
            price_eur = _parse_price(el.get_text())
            if price_eur is not None:
                break

    # --- Details: year, mileage, location ---
    year: int | None = None
    mileage_km: int | None = None
    location: str | None = None

    for el in article.find_all(["li", "span", "div"]):
        text = el.get_text(strip=True)
        if not text or len(text) > 80:
            continue
        if "km" in text.lower() and mileage_km is None:
            mileage_km = _parse_int(text)
        if ("EZ" in text or "Erstzulassung" in text.lower() or
                ("/" in text and len(text) < 10)) and year is None:
            year = _parse_year(text)
        if year is None and _parse_year(text) and len(text) < 12:
            year = _parse_year(text)

    # Location is often in a specific element
    for cls in ("seller-address", "location", "city", "ort"):
        el = article.find(class_=lambda c: c and cls.lower() in c.lower())
        if el:
            location = el.get_text(strip=True)
            break

    return VehicleListing(
        source="mobile.de",
        external_id=str(listing_id),
        title=title,
        price_eur=price_eur,
        mileage_km=mileage_km,
        year=year,
        url=href,
        location=location,
    )


def _get_html_curl_cffi(url: str, session: Any) -> str:
    """Fetch a URL with curl_cffi, impersonating Chrome."""
    resp = session.get(url, headers=_HEADERS, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


class MobileDeSource(ListingSource):
    name = "mobile.de"

    def fetch(self, params: SearchParams, app: AppConfig) -> list[VehicleListing]:
        if _CURL_CFFI_AVAILABLE:
            return self._fetch_curl_cffi(params, app)
        return self._fetch_httpx(params, app)

    def _fetch_curl_cffi(self, params: SearchParams, app: AppConfig) -> list[VehicleListing]:
        cfg = app.sources.mobile_de
        listings: list[VehicleListing] = []
        with _curl_requests.Session(impersonate="chrome120") as session:
            try:
                session.get(_BASE + "/", timeout=30)
                time.sleep(1.0)
            except Exception:
                pass
            for page in range(1, cfg.max_pages + 1):
                url = _build_url(params, page)
                logger.debug("mobile.de (curl_cffi) page %s: %s", page, url)
                try:
                    html = _get_html_curl_cffi(url, session)
                except Exception as exc:
                    logger.error("mobile.de request failed on page %s: %s", page, exc)
                    break
                listings, done = self._parse_page(html, listings, page)
                if done:
                    break
                time.sleep(1.5)
        return listings

    def _fetch_httpx(self, params: SearchParams, app: AppConfig) -> list[VehicleListing]:
        cfg = app.sources.mobile_de
        listings: list[VehicleListing] = []

        with httpx.Client(headers=_HEADERS, timeout=60.0, follow_redirects=True) as client:
            # Warm up session: visit homepage so mobile.de sets required session cookies.
            try:
                client.get(_BASE + "/")
                time.sleep(1.5)
            except Exception:
                pass

            for page in range(1, cfg.max_pages + 1):
                url = _build_url(params, page)
                logger.debug("mobile.de fetching page %s: %s", page, url)

                try:
                    r = client.get(url, headers={**_HEADERS, "Referer": _BASE + "/"})
                    r.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 403:
                        logger.warning(
                            "mobile.de returned 403 (bot protection). "
                            "Their anti-bot layer (Akamai) blocks plain HTTP clients. "
                            "Install 'curl_cffi' and set mobile_de.use_curl_cffi: true in config.yaml "
                            "to bypass this, or disable mobile.de and use AutoScout24 only."
                        )
                    else:
                        logger.error("mobile.de HTTP %s on page %s", exc.response.status_code, page)
                    break
                except httpx.RequestError as exc:
                    logger.error("mobile.de request failed on page %s: %s", page, exc)
                    break

                listings, done = self._parse_page(r.text, listings, page)
                if done:
                    break
                time.sleep(1.5)

        return listings

    def _parse_page(
        self, html: str, listings: list[VehicleListing], page: int
    ) -> tuple[list[VehicleListing], bool]:
        soup = BeautifulSoup(html, "html.parser")
        articles = soup.find_all("article")

        if not articles:
            logger.debug(
                "mobile.de: no <article> elements on page %s "
                "(page may have changed structure or returned a CAPTCHA).",
                page,
            )
            return listings, True

        before = len(listings)
        for article in articles:
            parsed = _parse_listing(article)
            if parsed:
                listings.append(parsed)

        logger.info("mobile.de page %s: %s listings found.", page, len(listings) - before)
        return listings, len(articles) < 20
