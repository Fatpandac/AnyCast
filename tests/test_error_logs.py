# -*- coding: utf-8 -*-
import asyncio
import logging
import stat

from fastapi.testclient import TestClient

from src import config, downloader, main


def test_runtime_log_is_paged_from_own_file_without_reading_anycast_log(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")
    (tmp_path / "anycast.log").write_text("old redirected log\n")
    monkeypatch.setattr(logging.getLogger(), "level", logging.getLogger().level)
    handler = main.start_runtime_log()
    try:
        for index in range(150):
            logging.getLogger("src.downloader").info("episode %03d", index)
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()

    client = TestClient(main.app)
    assert stat.S_IMODE((tmp_path / "runtime.log").stat().st_mode) == 0o600
    assert client.get("/api/admin/logs").status_code == 401
    response = client.get("/api/admin/logs", auth=("admin", "secret"))
    assert response.headers["cache-control"] == "no-store"
    first = response.json()
    assert len(first["lines"]) == 100
    assert "episode 050" in first["lines"][0]
    assert "episode 149" in first["lines"][-1]
    assert "old redirected log" not in str(first)
    assert first["before"]
    assert first["after"]
    assert (
        client.get(
            "/api/admin/logs",
            params={"after": first["after"]},
            auth=("admin", "secret"),
        ).json()["lines"]
        == []
    )
    with (tmp_path / "runtime.log").open("a") as log:
        log.write("episode 150\n")
    fresh = client.get(
        "/api/admin/logs", params={"after": first["after"]}, auth=("admin", "secret")
    ).json()
    assert fresh["lines"] == ["episode 150"]
    assert fresh["after"] != first["after"]
    assert (
        client.get(
            "/api/admin/logs",
            params={"after": fresh["after"]},
            auth=("admin", "secret"),
        ).json()["lines"]
        == []
    )

    older = client.get(
        "/api/admin/logs", params={"before": first["before"]}, auth=("admin", "secret")
    ).json()
    assert len(older["lines"]) == 50
    assert "episode 000" in older["lines"][0]
    assert "episode 049" in older["lines"][-1]
    assert older["before"] is None
    with (tmp_path / "runtime.log").open("a") as log:
        log.writelines(f"episode {index}\n" for index in range(151, 271))
    batch = client.get(
        "/api/admin/logs", params={"after": fresh["after"]}, auth=("admin", "secret")
    ).json()
    assert batch["lines"] == [f"episode {index}" for index in range(151, 251)]
    tail = client.get(
        "/api/admin/logs", params={"after": batch["after"]}, auth=("admin", "secret")
    ).json()
    assert tail["lines"] == [f"episode {index}" for index in range(251, 271)]


def test_paging_survives_new_lines_and_file_rotation(monkeypatch, tmp_path):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")
    monkeypatch.setattr(logging.getLogger(), "level", logging.getLogger().level)
    handler = main.start_runtime_log()
    handler.maxBytes = 1200
    try:
        for index in range(120):
            logging.getLogger("src.downloader").info("episode %03d", index)
        assert stat.S_IMODE((tmp_path / "runtime.log.1").stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "runtime.log").stat().st_mode) == 0o600
        client = TestClient(main.app)
        first = client.get("/api/admin/logs", auth=("admin", "secret")).json()
        assert len(first["lines"]) == 100
        logging.getLogger("src.downloader").info("episode 120")
        newer = client.get(
            "/api/admin/logs",
            params={"after": first["after"]},
            auth=("admin", "secret"),
        ).json()
        assert [line.rsplit(" ", 1)[-1] for line in newer["lines"]] == ["120"]
        older = client.get(
            "/api/admin/logs",
            params={"before": first["before"]},
            auth=("admin", "secret"),
        ).json()
        assert [line.rsplit(" ", 1)[-1] for line in older["lines"]] == [
            f"{i:03d}" for i in range(20)
        ]
        assert older["before"] is None
        handler.doRollover()
        logging.getLogger("src.downloader").info("episode 121")
        rolled = client.get(
            "/api/admin/logs",
            params={"after": newer["after"]},
            auth=("admin", "secret"),
        ).json()
        assert [line.rsplit(" ", 1)[-1] for line in rolled["lines"]] == ["121"]
        assert rolled["after"] != newer["after"]
        assert (
            client.get(
                "/api/admin/logs",
                params={"before": "nonsense"},
                auth=("admin", "secret"),
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/admin/logs",
                params={"before": first["before"], "after": first["after"]},
                auth=("admin", "secret"),
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/api/admin/logs",
                params={"after": "nonsense"},
                auth=("admin", "secret"),
            ).status_code
            == 422
        )
    finally:
        logging.getLogger().removeHandler(handler)
        handler.close()


def test_admin_can_read_persisted_errors_only_after_login(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("podcasts: []\n")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "start_cron_jobs", lambda: None)
    monkeypatch.setattr(main, "stop_cron_jobs", lambda: None)
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")

    with TestClient(main.app) as client:
        assert client.get("/api/admin/logs", auth=("admin", "secret")).json() == {
            "lines": [],
            "before": None,
            "after": None,
        }
        logging.getLogger("yt_dlp").error("YouTube proxy unreachable")
        logging.getLogger("apscheduler.executors.default").error("scheduled job failed")
        assert client.get("/api/admin/logs").status_code == 401
        response = client.get("/api/admin/logs", auth=("admin", "secret"))
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert "YouTube proxy unreachable" in "".join(response.json()["lines"])
        assert "scheduled job failed" in "".join(response.json()["lines"])
        assert "ERROR" in "".join(response.json()["lines"])

    assert "YouTube proxy unreachable" in (tmp_path / "runtime.log").read_text()


def test_youtube_playlist_error_is_captured_even_when_extraction_returns_empty(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")

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
    monkeypatch.setattr(logging.getLogger(), "level", logging.getLogger().level)
    handler = main.start_runtime_log()
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
    assert "No route to host" in (tmp_path / "runtime.log").read_text()
