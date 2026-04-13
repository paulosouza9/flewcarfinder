from __future__ import annotations

import logging

from car_deal_bot.config_loader import AppConfig, load_app_config
from car_deal_bot.memory import filter_new, load_seen_keys, remember
from car_deal_bot.models import VehicleListing
from car_deal_bot.notify import notify
from car_deal_bot.ranker import rank_listings
from car_deal_bot.sources.autoscout import AutoscoutSource
from car_deal_bot.sources.mobile_de import MobileDeSource

logger = logging.getLogger(__name__)


def collect_listings(app: AppConfig, seen_keys: set[str]) -> list[VehicleListing]:
    params = app.search
    target = app.ranking.top_n
    all_rows: list[VehicleListing] = []

    if app.sources.mobile_de.enabled:
        all_rows.extend(MobileDeSource().fetch(params, app))

    if app.sources.autoscout.enabled:
        # Ask the source to keep fetching pages until we likely have
        # enough new (unseen) results to fill top_n after ranking.
        # We ask for more than top_n because ranking + deal-score filter
        # will discard some.
        all_rows.extend(
            AutoscoutSource().fetch_until(
                params,
                app,
                needed=target * 3,
                seen_keys=seen_keys,
            )
        )

    return all_rows


def run_once() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = load_app_config()
    seen_keys = load_seen_keys()
    raw = collect_listings(app, seen_keys)
    ranked = rank_listings(raw, app)
    new_deals = filter_new(ranked)
    logger.info(
        "Collected %s listings, %s ranked, %s new.",
        len(raw), len(ranked), len(new_deals),
    )
    if new_deals:
        notify(new_deals, app)
        remember(new_deals)
    else:
        logger.info("No new deals to send today.")
