from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from car_deal_bot.config_loader import load_app_config
from car_deal_bot.run import run_once

logger = logging.getLogger(__name__)


def run_scheduler() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    app = load_app_config()
    sched = app.schedule

    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_once,
        CronTrigger(
            hour=sched.hour,
            minute=sched.minute,
            timezone=sched.timezone,
        ),
        id="morning_deals",
        replace_existing=True,
    )
    logger.info(
        "Scheduler started: daily at %02d:%02d (%s). Ctrl+C to stop.",
        sched.hour,
        sched.minute,
        sched.timezone,
    )
    scheduler.start()
