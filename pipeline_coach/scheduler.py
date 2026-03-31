from pathlib import Path

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline_coach.config import load_app_config
from pipeline_coach.observability.logger import setup_logging
from pipeline_coach.run_once import run_pipeline_once

logger = structlog.get_logger()


def start_scheduler(config_dir: Path = Path("config")) -> None:
    setup_logging()
    app_config = load_app_config()
    scheduler = BlockingScheduler()
    scheduler.add_job(
        run_pipeline_once,
        CronTrigger(hour=app_config.run_at_hour, minute=0),
        kwargs={"config_dir": config_dir, "app_config": app_config},
        id="pipeline_coach_daily",
        name="Pipeline Coach Daily Run",
    )
    logger.info("scheduler_started", run_at_hour=app_config.run_at_hour)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("scheduler_stopped")
