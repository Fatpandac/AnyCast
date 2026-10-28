# -*- coding: utf-8 -*-
import asyncio
import logging

from fastapi.testclient import TestClient

from src import config, downloader, main


def test_runtime_log_prefers_existing_anycast_log(monkeypatch, tmp_path):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    log_path = tmp_path / "anycast.log"
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", log_path)
    monkeypatch.setattr(main, "ERROR_LOG_PATH", tmp_path / "errors.log")
    log_path.write_text(
        "oldest line\n" + "x" * 70000 + "\n"
        "INFO:src.downloader:weekly: 需要下载 0 条\n"
        "ERROR: [youtube:tab] No route to host\n"
    )
    client = TestClient(main.app)
    assert client.get("/api/admin/logs").status_code == 401
    response = client.get("/api/admin/logs", auth=("admin", "secret"))
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("oldest line\n")
    assert len(response.content) > 65536
    assert "需要下载 0 条" in response.text
    assert "No route to host" in response.text


def test_admin_can_read_persisted_errors_only_after_login(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("podcasts: []\n")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "missing.log")
    monkeypatch.setattr(
        main, "ERROR_LOG_PATH", tmp_path / "anycast-errors.log", raising=False
    )
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "start_cron_jobs", lambda: None)
    monkeypatch.setattr(main, "stop_cron_jobs", lambda: None)
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")

    with TestClient(main.app) as client:
        assert (
            client.get("/api/admin/logs", auth=("admin", "secret")).text
            == "暂无运行日志。"
        )
        logging.getLogger("yt_dlp").error("YouTube proxy unreachable")
        logging.getLogger("apscheduler.executors.default").error("scheduled job failed")
        assert client.get("/api/admin/logs").status_code == 401
        response = client.get("/api/admin/logs", auth=("admin", "secret"))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "YouTube proxy unreachable" in response.text
        assert "scheduled job failed" in response.text
        assert "ERROR" in response.text

    assert "YouTube proxy unreachable" in (tmp_path / "anycast-errors.log").read_text()


def test_youtube_playlist_error_is_captured_even_when_extraction_returns_empty(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "ERROR_LOG_PATH", tmp_path / "errors.log")

    class FakeYoutubeDL:
        def __init__(self, options):
            self.options = options

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download):
            assert download is False
            self.options["logger"].error("No route to host")
            return {}

    monkeypatch.setattr(downloader, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(downloader, "_youtube_base_options", lambda: {})
    monkeypatch.setattr(downloader, "get_cached_episode_meta", lambda _ids: {})
    monkeypatch.setattr(downloader, "save_episode_meta", lambda _rows: None)
    handler = main.start_error_log()
    try:
        episodes = asyncio.run(
            downloader._collect_youtube_episodes(
                {
                    "name": "weekly",
                    "url": "https://www.youtube.com/playlist?list=PL123",
                    "update_period_cron": "0 * * * *",
                    "keep_latest": 10,
                    "sort_by": "date",
                    "sort_order": "desc",
                    "page_size": 20,
                    "yt_dlp_options": {},
                }
            )
        )
        assert episodes == []
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()
    assert "No route to host" in (tmp_path / "errors.log").read_text()
