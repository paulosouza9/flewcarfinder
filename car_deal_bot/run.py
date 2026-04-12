from __future__ import annotations

import logging

from car_deal_bot.config_loader import AppConfig, load_app_config
from car_deal_bot.models import VehicleListing
from car_deal_bot.notify import notify
from car_deal_bot.ranker import rank_listings
from car_deal_bot.sources.autoscout import AutoscoutSource
from car_deal_bot.sources.mobile_de import MobileDeSource

logger = logging.getLogger(__name__)


def collect_listings(app: AppConfig) -> list[VehicleListing]:
    params = app.search
    all_rows = []

    if app.sources.mobile_de.enabled:
        all_rows.extend(MobileDeSource().fetch(params, app))
    if app.sources.autoscout.enabled:
        all_rows.extend(AutoscoutSource().fetch(params, app))

    return all_rows


def run_once() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = load_app_config()
    raw = collect_listings(app)
    ranked = rank_listings(raw, app)
    logger.info("Collected %s listings, showing top %s.", len(raw), len(ranked))
    notify(ranked, app)
