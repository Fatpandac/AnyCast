# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from src import main


def _podcast(name: str = "weekly") -> dict:
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


def test_admin_spa_is_protected_and_served(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)

    unauthorized = client.get("/admin")
    response = client.get("/admin", auth=("admin", "secret"))

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Basic"
    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert 'type="module"' in response.text


def test_admin_nested_route_serves_spa(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)

    response = client.get("/admin/podcasts/weekly", auth=("admin", "secret"))

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text


def test_admin_api_uses_default_password_and_returns_warning(monkeypatch):
    monkeypatch.delenv("ANYCAST_ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(main, "_get_podcasts_from_file", lambda: [])
    client = TestClient(main.app)

    response = client.get("/api/admin/podcasts", auth=("admin", "adminadmin"))

    assert response.status_code == 200
    assert response.json() == {"podcasts": [], "uses_default_password": True}


def test_admin_api_lists_podcasts_and_episode_counts(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "_get_podcasts_from_file", lambda: [_podcast()])
    monkeypatch.setattr(main, "count_episodes_by_podcast", lambda name: 7)
    client = TestClient(main.app)

    response = client.get("/api/admin/podcasts", auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json()["podcasts"] == [{**_podcast(), "episode_count": 7}]
    assert response.json()["uses_default_password"] is False


def test_admin_api_returns_downloaded_episode_details(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "_get_podcasts_from_file", lambda: [_podcast()])
    episodes = [
        {
            "episode_id": "ep-1",
            "title": "Episode <One>",
            "description": "完整内容简介",
            "source_url": "https://www.youtube.com/watch?v=ep-1",
            "file_name": "episode one.m4a",
            "published_at": "2026-10-17T12:00:00+00:00",
            "created_at": "2026-10-18 13:20:00",
            "cover_image_url": "https://img.example/cover.jpg",
        }
    ]
    monkeypatch.setattr(main, "get_episodes", lambda name, **kwargs: episodes)
    client = TestClient(main.app)

    response = client.get("/api/admin/podcasts/weekly", auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json() == {"podcast": _podcast(), "episodes": episodes}


def test_admin_api_returns_404_for_unknown_name(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "_get_podcasts_from_file", lambda: [])
    client = TestClient(main.app)

    response = client.get("/api/admin/podcasts/missing", auth=("admin", "secret"))

    assert response.status_code == 404


def test_admin_api_adds_podcast_and_syncs_jobs(monkeypatch):
    saved = []
    sync_calls = []
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "add_podcast", saved.append)
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "sync_cron_jobs", lambda: sync_calls.append(True))
    client = TestClient(main.app)

    response = client.post(
        "/api/admin/podcasts",
        auth=("admin", "secret"),
        json={
            "name": "weekly",
            "url": "https://www.youtube.com/playlist?list=PL123",
            "update_period_cron": "0 * * * *",
            "keep_latest": 10,
            "sort_by": "date",
            "sort_order": "desc",
            "page_size": 20,
        },
    )

    assert response.status_code == 201
    assert response.json() == {"podcast": _podcast()}
    assert saved == [_podcast()]
    assert sync_calls == [True]


def test_admin_api_updates_podcast_and_syncs_jobs(monkeypatch):
    updated = {**_podcast(), "url": "https://example.com/updated"}
    saved = []
    sync_calls = []
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        main,
        "update_podcast",
        lambda name, podcast: saved.append((name, podcast)),
    )
    monkeypatch.setattr(main, "init_database", lambda: None)
    monkeypatch.setattr(main, "sync_cron_jobs", lambda: sync_calls.append(True))
    client = TestClient(main.app)

    response = client.put(
        "/api/admin/podcasts/weekly",
        auth=("admin", "secret"),
        json={key: value for key, value in updated.items() if key != "yt_dlp_options"},
    )

    assert response.status_code == 200
    assert response.json() == {"podcast": updated}
    assert saved == [("weekly", updated)]
    assert sync_calls == [True]


def test_admin_api_rejects_renaming_podcast(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)

    response = client.put(
        "/api/admin/podcasts/weekly",
        auth=("admin", "secret"),
        json={**_podcast("renamed"), "yt_dlp_options": {}},
    )

    assert response.status_code == 400


def test_admin_api_rejects_unsafe_podcast_name(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)

    response = client.post(
        "/api/admin/podcasts",
        auth=("admin", "secret"),
        json={
            "name": "../outside",
            "url": "https://www.youtube.com/playlist?list=PL123",
            "update_period_cron": "0 * * * *",
            "sort_by": "date",
            "sort_order": "desc",
            "page_size": 20,
        },
    )

    assert response.status_code == 422


def test_admin_api_removes_podcast_without_deleting_downloads(monkeypatch):
    removed = []
    sync_calls = []
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "remove_podcast", removed.append)
    monkeypatch.setattr(main, "sync_cron_jobs", lambda: sync_calls.append(True))
    client = TestClient(main.app)

    response = client.delete("/api/admin/podcasts/weekly", auth=("admin", "secret"))

    assert response.status_code == 200
    assert response.json() == {"status": "removed"}
    assert removed == ["weekly"]
    assert sync_calls == [True]
