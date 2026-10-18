# -*- coding: utf-8 -*-
from __future__ import annotations
import logging

from src.config import get_config
from src.downloader import run_downloader
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


_scheduler: AsyncIOScheduler | None = None


def _sync_scheduler(scheduler: AsyncIOScheduler) -> None:
    podcasts = get_config()["podcasts"]
    configured_names = {podcast["name"] for podcast in podcasts}

    for job in scheduler.get_jobs():
        if job.id not in configured_names:
            scheduler.remove_job(job.id)

    for podcast in podcasts:
        log.info(f"Creating job for {podcast['name']}")
        scheduler.add_job(
            run_downloader,
            CronTrigger.from_crontab(podcast["update_period_cron"]),
            args=[podcast],
            id=podcast["name"],
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )


def start_cron_jobs():
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    scheduler = AsyncIOScheduler()
    _sync_scheduler(scheduler)
    scheduler.start()
    _scheduler = scheduler
    return scheduler


def sync_cron_jobs():
    if not _scheduler or not _scheduler.running:
        return start_cron_jobs()
    _sync_scheduler(_scheduler)
    return _scheduler


def stop_cron_jobs() -> None:
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        _scheduler = None
