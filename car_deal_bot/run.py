from __future__ import annotations

import logging

from car_deal_bot.config_loader import AppConfig, load_app_config
from car_deal_bot.memory import filter_new, load_seen_keys, remember
from car_deal_bot.models import SearchParams, VehicleListing
from car_deal_bot.notify import notify
from car_deal_bot.ranker import dedupe, rank_listings
from car_deal_bot.sources.autoscout import AutoscoutSource
from car_deal_bot.sources.mobile_de import MobileDeSource

logger = logging.getLogger(__name__)


def _collect_for_params(
    params: SearchParams, app: AppConfig, seen_keys: set[str]
) -> list[VehicleListing]:
    """Fetch raw listings from all enabled sources for a single search."""
    target = app.ranking.top_n
    rows: list[VehicleListing] = []

    if app.sources.mobile_de.enabled:
        rows.extend(MobileDeSource().fetch(params, app))

    if app.sources.autoscout.enabled:
        # Fetch more than top_n because ranking + deal-score filter will discard some.
        rows.extend(
            AutoscoutSource().fetch_until(
                params,
                app,
                needed=target * 3,
                seen_keys=seen_keys,
            )
        )

    return rows


def run_once() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = load_app_config()
    seen_keys = load_seen_keys()

    # Collect and rank each search independently so that deal scores are
    # computed within the same car type (mixing e.g. BMW and Porsche prices
    # in one pool would distort the expected-price regression).
    all_ranked: list[VehicleListing] = []
    total_raw = 0
    for i, params in enumerate(app.searches, start=1):
        label = f"{params.make or ''} {params.model or ''}".strip() or f"search {i}"
        raw = _collect_for_params(params, app, seen_keys)
        total_raw += len(raw)
        logger.info("[%s] Collected %s raw listings.", label, len(raw))
        ranked = rank_listings(raw, app)
        logger.info("[%s] %s listings after ranking.", label, len(ranked))
        all_ranked.extend(ranked)

    # Dedupe across searches (same car could appear in multiple searches).
    merged = dedupe(all_ranked)

    new_deals = filter_new(merged)
    logger.info(
        "Total: %s raw, %s after per-search ranking (%s top-%s each), %s new.",
        total_raw, len(merged), len(app.searches), app.ranking.top_n, len(new_deals),
    )

    if new_deals:
        notify(new_deals, app)
        remember(new_deals)
    else:
        logger.info("No new deals to send today.")
