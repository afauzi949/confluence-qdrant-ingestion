from __future__ import annotations

import argparse
import logging
import sys
from zoneinfo import ZoneInfo

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import ConfigError, Settings
from .pipeline import Pipeline

log = logging.getLogger("ingest")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ingest", description="Confluence -> Qdrant sync")
    ap.add_argument("--once", action="store_true", help="run one sync now and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="only list trashed/modified page ids (implies --once)")
    ap.add_argument("--env-file", default=None)
    args = ap.parse_args(argv)

    try:
        settings = Settings.from_env(args.env_file)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keeps URLs/queries out of logs
    pipeline = Pipeline(settings)

    if args.once or args.dry_run:
        return 0 if pipeline.run(dry_run=args.dry_run).ok else 1

    def job() -> None:
        pipeline.run()

    sched = BlockingScheduler(timezone=ZoneInfo(settings.schedule_timezone))
    sched.add_job(
        job,
        CronTrigger(hour=settings.schedule_hour, minute=settings.schedule_minute,
                    timezone=ZoneInfo(settings.schedule_timezone)),
        id="confluence-sync", max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    if settings.run_on_start:
        job()
    log.info("scheduler started: daily at %02d:%02d %s",
             settings.schedule_hour, settings.schedule_minute, settings.schedule_timezone)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
