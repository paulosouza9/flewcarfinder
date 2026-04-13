from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path

from car_deal_bot.models import VehicleListing
from car_deal_bot.settings import _PROJECT_ROOT

logger = logging.getLogger(__name__)

_MEMORY_FILE = _PROJECT_ROOT / "seen_deals.json"
_MAX_AGE_DAYS = 30  # auto-prune entries older than this


def _load() -> dict[str, str]:
    """Return {listing_key: date_seen_iso} mapping."""
    if not _MEMORY_FILE.is_file():
        return {}
    try:
        data = json.loads(_MEMORY_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read %s: %s", _MEMORY_FILE, exc)
    return {}


def _save(seen: dict[str, str]) -> None:
    try:
        _MEMORY_FILE.write_text(
            json.dumps(seen, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.error("Could not write %s: %s", _MEMORY_FILE, exc)


def _key(v: VehicleListing) -> str:
    return f"{v.source}::{v.external_id}"


def _prune(seen: dict[str, str]) -> dict[str, str]:
    cutoff = (date.today() - timedelta(days=_MAX_AGE_DAYS)).isoformat()
    return {k: v for k, v in seen.items() if v >= cutoff}


def load_seen_keys() -> set[str]:
    """Return the set of all previously-seen listing keys."""
    return set(_load().keys())


def is_new(v: VehicleListing, seen_keys: set[str]) -> bool:
    return _key(v) not in seen_keys


def filter_new(listings: list[VehicleListing]) -> list[VehicleListing]:
    """Return only listings we haven't sent before."""
    seen_keys = load_seen_keys()
    new = [v for v in listings if is_new(v, seen_keys)]
    logger.info(
        "Memory: %s seen before, %s new out of %s.",
        len(listings) - len(new), len(new), len(listings),
    )
    return new


def remember(listings: list[VehicleListing]) -> None:
    """Mark listings as sent so they won't appear next time."""
    seen = _load()
    today = date.today().isoformat()
    for v in listings:
        seen[_key(v)] = today
    seen = _prune(seen)
    _save(seen)
    logger.debug("Memory: %s total entries after save.", len(seen))
