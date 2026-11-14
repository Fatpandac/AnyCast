# -*- coding: utf-8 -*-
import asyncio
from typing import cast

import pytest
from fastapi.testclient import TestClient

from src import config, downloader, main, updates
from src.config import Podcast
from test_updates import checkout as git_checkout, commit

checkout = git_checkout


@pytest.fixture
def service(checkout, monkeypatch):
    root, remote, _ = checkout
    target = commit(remote, "new update")
    service = updates.UpdateService(root)
    monkeypatch.setattr(service, "managed", lambda: True)
    monkeypatch.setattr(main, "update_service", service)
    monkeypatch.setattr(downloader, "_updates_paused", False)
    monkeypatch.setattr(downloader, "_active_downloads", 0)
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    config_path = root / ".git" / "test-config.yaml"
    config_path.write_text("podcasts: []\n")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(config_path))
    return service, target


def test_update_api_requires_admin_origin_and_confirmed_sha(service):
    service, target = service
    client = TestClient(main.app)
    auth = ("admin", "secret")
    assert client.get("/api/admin/updates").status_code == 401
    assert client.post("/api/admin/updates/check").status_code == 401
    assert (
        client.post("/api/admin/updates/install", json={"target": target}).status_code
        == 401
    )
    assert (
        client.post(
            "/api/admin/updates/check",
            auth=auth,
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    status = client.post("/api/admin/updates/check", auth=auth)
    assert status.status_code == 200
    assert status.json()["latest_sha"] == target
    assert status.json()["can_update"] is True
    assert (
        client.post(
            "/api/admin/updates/install", auth=auth, json={"target": "invalid"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/admin/updates/install", auth=auth, json={"target": "a" * 40}
        ).status_code
        == 409
    )
    assert not downloader.downloads_paused()
    response = client.post(
        "/api/admin/updates/install", auth=auth, json={"target": target}
    )
    assert response.status_code == 202
    assert downloader.downloads_paused()
    assert (
        client.post(
            "/api/admin/updates/install", auth=auth, json={"target": target}
        ).status_code
        == 409
    )
    for path, method in [
        ("/api/admin/settings", "put"),
        ("/api/admin/passkeys/login/options", "post"),
    ]:
        assert getattr(client, method)(path, auth=auth, json={}).status_code in (
            422,
            503,
        )
    assert client.get("/api/admin/updates", auth=auth).json()["phase"] == "preparing"
    assert (
        client.post(
            "/api/admin/updates/install",
            auth=auth,
            json={"target": target},
            headers={"Origin": "https://evil.test"},
        ).status_code
        == 403
    )
    assert "token" not in response.json()


def test_download_busy_guard_is_atomic_and_rejects_install(service, monkeypatch):
    service, target = service
    service.check()
    monkeypatch.setattr(downloader, "_active_downloads", 1)
    client = TestClient(main.app)
    auth = ("admin", "secret")
    assert client.get("/api/admin/updates", auth=auth).json()["can_update"] is False
    response = client.post(
        "/api/admin/updates/install", auth=auth, json={"target": target}
    )
    assert response.status_code == 409
    assert "下载" in response.json()["detail"]
    assert not service.requested
    assert not downloader.downloads_paused()


def test_gate_tracks_scans_and_prevents_new_downloads(monkeypatch):
    started = asyncio.Event()
    finish = asyncio.Event()
    monkeypatch.setattr(downloader, "_updates_paused", False)
    monkeypatch.setattr(downloader, "_active_downloads", 0)

    async def scan(_podcast):
        started.set()
        await finish.wait()

    monkeypatch.setattr(downloader, "__run", scan)
    podcast = cast(Podcast, {"name": "gate-test"})

    async def verify():
        task = asyncio.create_task(downloader.run_downloader(podcast))
        await started.wait()
        assert downloader.active_downloads() == 1
        assert not downloader.pause_for_update()
        finish.set()
        await task
        assert downloader.pause_for_update()
        started.clear()
        await downloader.run_downloader(podcast)
        assert not started.is_set()
        assert downloader.active_downloads() == 0
        downloader.resume_after_update()

    asyncio.run(verify())


def test_internal_health_requires_private_parent_token(service, monkeypatch):
    service, _ = service
    monkeypatch.setattr(service, "token", "private-token")
    monkeypatch.setattr(main, "_service_ready", True)
    client = TestClient(main.app)
    assert client.get("/_internal/update-health").status_code == 404
    assert (
        client.get(
            "/_internal/update-health", headers={"X-AnyCast-Supervisor": "wrong"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/_internal/update-health", headers={b"X-AnyCast-Supervisor": bytes([255])}
        ).status_code
        == 404
    )
    response = client.get(
        "/_internal/update-health", headers={"X-AnyCast-Supervisor": "private-token"}
    )
    assert response.json() == {"sha": service.running_sha, "ready": True}


def test_configuration_writes_are_blocked_inside_the_handler(service):
    client = TestClient(main.app)
    downloader.pause_for_update()
    response = client.put(
        "/api/admin/settings",
        auth=("admin", "secret"),
        json={
            "server": {"host": "127.0.0.1", "port": 8001},
            "youtube": {"cookies_file": "", "cookies_from_browser": ""},
        },
    )
    assert response.status_code == 503


def test_verification_startup_holds_jobs_until_parent_accepts(
    service, monkeypatch, tmp_path
):
    import threading

    instance, _ = service
    started = threading.Event()
    checked = threading.Event()
    monkeypatch.setenv("ANYCAST_UPDATE_VERIFY", "1")
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "start_cron_jobs", started.set)
    monkeypatch.setattr(main, "stop_cron_jobs", lambda: None)
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")
    monkeypatch.setattr(instance, "check", lambda: checked.set() or {})
    updates.write_json(instance.repo.state_dir / "state.json", {"phase": "restarting"})
    with TestClient(main.app):
        assert downloader.downloads_paused()
        assert not started.is_set()
        assert not checked.wait(timeout=0.1)
        ready = updates.read_json(instance.repo.state_dir / "ready.json")
        assert ready["sha"] == instance.running_sha
        updates.write_json(instance.repo.state_dir / "state.json", {"phase": "success"})
        assert started.wait(timeout=2)
        assert checked.wait(timeout=2)
        assert not downloader.downloads_paused()


def test_failed_readiness_file_write_cleans_up_lifespan(service, monkeypatch, tmp_path):
    import logging

    instance, _ = service
    stopped = []
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "start_cron_jobs", lambda: None)
    monkeypatch.setattr(main, "stop_cron_jobs", lambda: stopped.append(True))
    monkeypatch.setattr(main, "RUNTIME_LOG_PATH", tmp_path / "runtime.log")
    monkeypatch.setattr(instance, "check", lambda: {})

    def fail(*args, **kwargs):
        raise updates.UpdateError("private state write failed")

    monkeypatch.setattr(main, "write_json", fail)
    handlers = list(logging.getLogger().handlers)

    async def verify():
        with pytest.raises(updates.UpdateError):
            async with main.lifespan(main.app):
                pytest.fail("startup must fail")

    asyncio.run(verify())
    assert not main._service_ready
    assert logging.getLogger().handlers == handlers
    assert stopped == [True]


def test_queue_during_check_fails_without_waiting_or_leaving_gate_closed(service):
    instance, target = service
    instance.lock.acquire()
    try:
        client = TestClient(main.app)
        response = client.post(
            "/api/admin/updates/install",
            auth=("admin", "secret"),
            json={"target": target},
        )
        assert response.status_code == 409
        assert "正在检查" in response.json()["detail"]
        assert not downloader.downloads_paused()
    finally:
        instance.lock.release()


def test_maintenance_resumes_after_rejection_without_starting_jobs_twice(
    service, monkeypatch
):
    instance, target = service
    instance.check()
    instance.queue(target)
    request = updates.read_json(instance.repo.state_dir / "request.json")
    downloader.pause_for_update()
    updates.write_json(
        instance.repo.state_dir / "state.json",
        {
            "operation_id": request["operation_id"],
            "phase": "failed",
            "message": "main changed",
        },
    )
    assert main.resume_update_gate() is True
    assert not downloader.downloads_paused()
