# -*- coding: utf-8 -*-
from pathlib import Path

import yaml

from src import config, jobs


def _podcast(name: str = "weekly") -> config.Podcast:
    return {
        "name": name,
        "url": "https://www.youtube.com/playlist?list=PL123",
        "update_period_cron": "0 * * * *",
        "keep_latest": 10,
        "sort_by": "date",
        "sort_order": "desc",
        "page_size": 20,
        "yt_dlp_options": {},
    }


def test_sync_cron_jobs_matches_current_config(monkeypatch):
    class FakeJob:
        def __init__(self, job_id):
            self.id = job_id

    class FakeScheduler:
        running = True

        def __init__(self):
            self.jobs = {"old": FakeJob("old")}
            self.added = []
            self.removed = []

        def get_jobs(self):
            return list(self.jobs.values())

        def add_job(self, func, trigger, args, id, **kwargs):
            self.added.append((id, args[0]["name"]))
            self.jobs[id] = FakeJob(id)

        def remove_job(self, job_id):
            self.removed.append(job_id)
            self.jobs.pop(job_id)

    scheduler = FakeScheduler()
    monkeypatch.setattr(jobs, "_scheduler", scheduler)
    monkeypatch.setattr(jobs, "get_config", lambda: {"podcasts": [_podcast("new")]})

    jobs.sync_cron_jobs()

    assert scheduler.added == [("new", "new")]
    assert scheduler.removed == ["old"]


def test_add_and_remove_podcast_preserves_other_config(monkeypatch, tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "server": {"port": 9000},
                "youtube": {"cookies_file": "/tmp/cookies.txt"},
                "podcasts": [_podcast("existing")],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(config_path))

    config.add_podcast(_podcast("new-show"))
    config.remove_podcast("existing")

    saved = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert saved["server"] == {"port": 9000}
    assert saved["youtube"] == {"cookies_file": "/tmp/cookies.txt"}
    assert [podcast["name"] for podcast in saved["podcasts"]] == ["new-show"]
