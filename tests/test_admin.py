# -*- coding: utf-8 -*-
from typing import cast

from fastapi.testclient import TestClient

from src import main
from src.config import Podcast


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


def test_passkey_registration_requires_auth_and_origin(monkeypatch, tmp_path):
    import yaml
    from src import config

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"podcasts": [], "server": {}, "youtube": {}}))
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)
    assert client.post("/api/admin/passkeys/register/options").status_code == 401
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "adminadmin")
    assert (
        client.post(
            "/api/admin/passkeys/register/options",
            auth=("admin", "adminadmin"),
            headers={"Origin": "https://example.com", "Host": "example.com"},
        ).status_code
        == 403
    )
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    assert (
        client.put(
            "/api/admin/settings/passkey-origin",
            auth=("admin", "secret"),
            json={"origin": "http://example.com"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/admin/settings/passkey-origin",
            auth=("admin", "secret"),
            json={"origin": "https://example.com/path"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/admin/settings/passkey-origin",
            auth=("admin", "secret"),
            json={"origin": "https://example.com"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/admin/passkeys/register/options",
            auth=("admin", "secret"),
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    response = client.post(
        "/api/admin/passkeys/register/options",
        auth=("admin", "secret"),
        headers={"Origin": "https://example.com", "Host": "example.com"},
    )
    assert response.status_code == 200
    assert response.json()["rp"]["id"] == "example.com"
    assert response.json()["authenticatorSelection"]["residentKey"] == "required"
    assert (
        client.get("/api/admin/settings", auth=("admin", "secret")).json()["admin"][
            "passkey_origin"
        ]
        == "https://example.com"
    )
    assert yaml.safe_load(path.read_text())["podcasts"] == []
    assert client.put(
        "/api/admin/settings/passkey-origin",
        auth=("admin", "secret"),
        json={"origin": ""},
    ).json() == {"passkey_origin": "", "passkey_count": 0}


def test_passkey_registration_persists_credential_and_origin_change_revokes_it(
    monkeypatch, tmp_path
):
    import yaml
    from types import SimpleNamespace
    from src import config, passkeys

    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "podcasts": [{"name": "existing"}],
                "admin": {"passkey_origin": "https://example.com"},
            }
        )
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        passkeys,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(
            credential_id=b"cred-id",
            credential_public_key=b"public-key",
            sign_count=0,
        ),
    )
    client = TestClient(main.app, base_url="https://example.com")
    headers = {"Origin": "https://example.com"}
    options = client.post(
        "/api/admin/passkeys/register/options",
        auth=("admin", "secret"),
        headers=headers,
    ).json()
    assert (
        client.post(
            "/api/admin/passkeys/register/verify",
            auth=("admin", "secret"),
            headers=headers,
            json={
                "challenge": options["challenge"],
                "credential": {"id": "Y3JlZC1pZA"},
            },
        ).json()["passkey_count"]
        == 1
    )
    saved = yaml.safe_load(path.read_text())
    assert saved["podcasts"] == [{"name": "existing"}]
    assert saved["admin"]["passkeys"][0]["id"] == "Y3JlZC1pZA"
    assert "passkey_secret" in saved["admin"]
    assert path.stat().st_mode & 0o077 == 0
    assert (
        client.post(
            "/api/admin/passkeys/register/verify",
            auth=("admin", "secret"),
            headers=headers,
            json={
                "challenge": options["challenge"],
                "credential": {"id": "Y3JlZC1pZA"},
            },
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/admin/settings/passkey-origin",
            auth=("admin", "secret"),
            headers=headers,
            json={"origin": "https://new.example.com"},
        ).json()["passkey_count"]
        == 0
    )
    assert "passkeys" not in yaml.safe_load(path.read_text())["admin"]


def test_passkey_login_is_single_use_and_session_is_origin_bound(monkeypatch, tmp_path):
    import yaml
    from types import SimpleNamespace
    from src import config, passkeys

    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "podcasts": [],
                "admin": {
                    "passkey_origin": "https://example.com",
                    "passkey_secret": "ab" * 32,
                    "passkeys": [
                        {"id": "Y3JlZC1pZA", "public_key": "aGVsbG8", "sign_count": 0}
                    ],
                },
            }
        )
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        passkeys,
        "verify_authentication_response",
        lambda **kw: SimpleNamespace(
            credential_id=b"cred-id", new_sign_count=1, user_verified=True
        ),
    )
    client = TestClient(main.app, base_url="https://example.com")
    headers = {"Host": "example.com", "Origin": "https://example.com"}
    assert (
        client.get(
            "/admin", headers={"Host": "example.com"}, follow_redirects=False
        ).headers["location"]
        == "/admin/login"
    )
    assert client.get("/api/admin/settings", headers=headers).status_code == 401
    assert (
        client.get("/admin/basic", headers=headers, follow_redirects=False).headers[
            "www-authenticate"
        ]
        == "Basic"
    )
    assert (
        client.get(
            "/admin/basic",
            headers=headers,
            auth=("admin", "secret"),
            follow_redirects=False,
        ).status_code
        == 303
    )
    options = client.post("/api/admin/passkeys/login/options", headers=headers).json()
    assert options["rpId"] == "example.com"
    response = client.post(
        "/api/admin/passkeys/login/verify",
        headers=headers,
        json={"challenge": options["challenge"], "credential": {"id": "Y3JlZC1pZA"}},
    )
    assert response.status_code == 200
    assert (
        "Secure" in response.headers["set-cookie"]
        and "HttpOnly" in response.headers["set-cookie"]
    )
    assert client.get("/api/admin/settings", headers=headers).status_code == 200
    assert (
        client.post(
            "/api/admin/passkeys/login/verify",
            headers=headers,
            json={
                "challenge": options["challenge"],
                "credential": {"id": "Y3JlZC1pZA"},
            },
        ).status_code
        == 400
    )
    assert (
        client.put(
            "/api/admin/settings",
            headers={**headers, "Origin": "https://evil.example"},
            json={},
        ).status_code
        == 403
    )
    assert (
        client.get("/api/admin/settings", headers={"Host": "evil.example"}).status_code
        == 401
    )
    assert (
        client.put(
            "/api/admin/settings/passkey-origin",
            auth=("admin", "secret"),
            headers=headers,
            json={"origin": "https://new.example.com"},
        ).status_code
        == 200
    )
    assert client.get("/api/admin/settings", headers=headers).status_code == 401


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


def test_same_podcast_downloads_do_not_overlap(monkeypatch):
    import asyncio
    from src import downloader

    active = 0
    peak = 0

    async def fake_run(podcast):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr(downloader, "__run", fake_run)

    async def check():
        await asyncio.gather(
            downloader.run_downloader(cast(Podcast, _podcast())),
            downloader.run_downloader(cast(Podcast, _podcast())),
        )

    asyncio.run(check())
    assert peak == 1


def test_admin_can_start_one_podcast_update(monkeypatch):
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(main, "_get_podcasts_from_file", lambda: [_podcast()])
    scheduled = []

    class FakeTask:
        def add_done_callback(self, callback):
            self.callback = callback

        def cancelled(self):
            return False

        def result(self):
            return None

    def schedule(coro):
        scheduled.append(coro)
        coro.close()
        return FakeTask()

    monkeypatch.setattr(main.asyncio, "create_task", schedule)
    client = TestClient(main.app)
    url = "/api/admin/podcasts/weekly/update"
    assert client.post(url).status_code == 401
    assert (
        client.post(
            url, auth=("admin", "secret"), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    response = client.post(url, auth=("admin", "secret"))
    assert response.status_code == 202
    assert len(scheduled) == 1
    assert client.post(url, auth=("admin", "secret")).status_code == 409
    # Complete the task before testing not-found to avoid state leaking to other tests.
    scheduled_task = cast(FakeTask, main._manual_updates["weekly"])
    scheduled_task.callback(scheduled_task)
    assert (
        client.post(
            "/api/admin/podcasts/missing/update", auth=("admin", "secret")
        ).status_code
        == 404
    )


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


def test_admin_cookie_file_can_be_edited_with_default_password(monkeypatch, tmp_path):
    import yaml
    from src import config

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"podcasts": [], "youtube": {"cookies_file": str(cookie)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.delenv("ANYCAST_ADMIN_PASSWORD", raising=False)
    client = TestClient(main.app)
    url = "/api/admin/settings/cookies"
    response = client.get(url, auth=("admin", "adminadmin"))
    assert response.status_code == 200
    assert (
        client.put(
            url,
            auth=("admin", "adminadmin"),
            json={
                "path": str(cookie),
                "content": "# Netscape HTTP Cookie File\n# new\n",
                "revision": response.json()["revision"],
            },
        ).status_code
        == 200
    )
    assert cookie.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\n# new\n"


def test_admin_cookie_file_can_be_read_and_edited_without_exposing_other_files(
    monkeypatch, tmp_path
):
    import hashlib
    import yaml
    from src import config

    cookie = tmp_path / "cookies.txt"
    cookie.write_text(
        "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tSID\told\n",
        encoding="utf-8",
    )
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"server": {}, "podcasts": [], "youtube": {"cookies_file": str(cookie)}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)
    url = "/api/admin/settings/cookies"
    assert client.get(url).status_code == 401
    assert (
        client.get(
            url, auth=("admin", "secret"), headers={"Origin": "https://evil.example"}
        ).status_code
        == 403
    )
    response = client.get(url, auth=("admin", "secret"))
    assert response.status_code == 200
    assert response.json() == {
        "path": str(cookie),
        "content": cookie.read_text(encoding="utf-8"),
        "revision": hashlib.sha256(cookie.read_bytes()).hexdigest(),
    }
    assert response.headers["cache-control"] == "no-store"

    content = "# Netscape HTTP Cookie File\n.example.com\tTRUE\t/\tFALSE\t0\tSID\tnew\n"
    revision = response.json()["revision"]
    assert (
        client.put(
            url,
            auth=("admin", "secret"),
            json={
                "path": str(tmp_path / "other.txt"),
                "content": content,
                "revision": revision,
            },
        ).status_code
        == 409
    )
    assert (
        client.put(
            url,
            auth=("admin", "secret"),
            headers={"Origin": "https://evil.example"},
            json={"path": str(cookie), "content": content, "revision": revision},
        ).status_code
        == 403
    )
    assert "old" in cookie.read_text(encoding="utf-8")
    response = client.put(
        url,
        auth=("admin", "secret"),
        json={"path": str(cookie), "content": content, "revision": revision},
    )
    assert response.status_code == 200
    assert response.json()["revision"] == hashlib.sha256(content.encode()).hexdigest()
    assert (
        client.put(
            url,
            auth=("admin", "secret"),
            json={
                "path": str(cookie),
                "content": content.replace("new", "another"),
                "revision": revision,
            },
        ).status_code
        == 409
    )
    assert cookie.read_text(encoding="utf-8") == content
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["youtube"][
        "cookies_file"
    ] == str(cookie)


def test_admin_cookie_file_rejects_missing_and_invalid_content(monkeypatch, tmp_path):
    import yaml
    from src import config

    cookie = tmp_path / "cookies.txt"
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump(
            {"server": {}, "podcasts": [], "youtube": {"cookies_file": str(cookie)}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)
    url = "/api/admin/settings/cookies"
    assert client.get(url, auth=("admin", "secret")).status_code == 404
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    revision = client.get(url, auth=("admin", "secret")).json()["revision"]
    for content in ("", "plain text", "# Netscape HTTP Cookie File\n" + "x" * 1048576):
        assert (
            client.put(
                url,
                auth=("admin", "secret"),
                json={"path": str(cookie), "content": content, "revision": revision},
            ).status_code
            == 422
        )
    assert cookie.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\n"
    link = tmp_path / "link.txt"
    link.symlink_to(cookie)
    path.write_text(
        yaml.safe_dump(
            {"server": {}, "podcasts": [], "youtube": {"cookies_file": str(link)}}
        ),
        encoding="utf-8",
    )
    assert (
        client.put(
            url,
            auth=("admin", "secret"),
            json={
                "path": str(link),
                "content": "# Netscape HTTP Cookie File\n# changed\n",
                "revision": revision,
            },
        ).status_code
        == 409
    )
    assert cookie.read_text(encoding="utf-8") == "# Netscape HTTP Cookie File\n"


def test_admin_password_change_takes_effect_and_keeps_other_config(
    monkeypatch, tmp_path
):
    import yaml
    from src import config

    path = tmp_path / "config.yaml"
    original = {
        "server": {"port": 8001},
        "youtube": {"custom": True},
        "podcasts": [_podcast()],
    }
    path.write_text(yaml.safe_dump(original), encoding="utf-8")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "old-password")
    client = TestClient(main.app)
    url = "/api/admin/settings/password"
    payload = {
        "current_password": "old-password",
        "new_password": "a-longer-new-password",
    }

    assert client.put(url, json=payload).status_code == 401
    assert (
        client.put(
            url,
            auth=("admin", "old-password"),
            headers={"Origin": "https://evil.example"},
            json=payload,
        ).status_code
        == 403
    )
    assert (
        client.put(
            url,
            auth=("admin", "old-password"),
            json={**payload, "current_password": "wrong"},
        ).status_code
        == 403
    )
    assert (
        client.put(
            url,
            auth=("admin", "old-password"),
            json={**payload, "new_password": "short"},
        ).status_code
        == 422
    )
    assert "admin" not in yaml.safe_load(path.read_text(encoding="utf-8"))

    assert (
        client.put(url, auth=("admin", "old-password"), json=payload).status_code == 200
    )
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {key: saved[key] for key in original} == original
    assert "old-password" not in path.read_text(encoding="utf-8")
    assert "a-longer-new-password" not in path.read_text(encoding="utf-8")
    assert saved["admin"]["password_hash"]
    assert (
        client.get("/api/admin/settings", auth=("admin", "old-password")).status_code
        == 401
    )
    assert (
        client.get(
            "/api/admin/settings", auth=("admin", "a-longer-new-password")
        ).status_code
        == 200
    )
    assert (
        client.put(
            url, auth=("admin", "a-longer-new-password"), json=payload
        ).status_code
        == 403
    )
    assert (
        client.put(
            url,
            auth=("admin", "a-longer-new-password"),
            json={
                "current_password": "a-longer-new-password",
                "new_password": "another-long-password",
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/admin/settings", auth=("admin", "a-longer-new-password")
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/admin/settings", auth=("admin", "another-long-password")
        ).status_code
        == 200
    )


def test_admin_password_change_does_not_overwrite_concurrent_change(
    monkeypatch, tmp_path
):
    import yaml
    from src import admin, config

    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump({"podcasts": []}), encoding="utf-8")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "original-password")
    verify = main.verify_admin_password

    def concurrent_update(password):
        valid = verify(password)
        config.update_admin_password_hash(
            None, admin.hash_admin_password("other-secure-password")
        )
        return valid

    monkeypatch.setattr(main, "verify_admin_password", concurrent_update)
    response = TestClient(main.app).put(
        "/api/admin/settings/password",
        auth=("admin", "original-password"),
        json={
            "current_password": "original-password",
            "new_password": "my-secure-new-password",
        },
    )
    assert response.status_code == 409
    assert (
        TestClient(main.app)
        .get("/api/admin/settings", auth=("admin", "other-secure-password"))
        .status_code
        == 200
    )
    assert (
        TestClient(main.app)
        .get("/api/admin/settings", auth=("admin", "my-secure-new-password"))
        .status_code
        == 401
    )


def test_admin_default_password_can_be_replaced(monkeypatch, tmp_path):
    import yaml
    from src import config

    cookie = tmp_path / "cookies.txt"
    cookie.write_text("# Netscape HTTP Cookie File\n", encoding="utf-8")
    path = tmp_path / "config.yaml"
    path.write_text(
        yaml.safe_dump({"podcasts": [], "youtube": {"cookies_file": str(cookie)}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.delenv("ANYCAST_ADMIN_PASSWORD", raising=False)
    client = TestClient(main.app)

    assert (
        client.put(
            "/api/admin/settings/password",
            auth=("admin", "adminadmin"),
            json={"current_password": "adminadmin", "new_password": "adminadmin"},
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/admin/settings/password",
            auth=("admin", "adminadmin"),
            json={
                "current_password": "adminadmin",
                "new_password": "new-secure-password",
            },
        ).status_code
        == 200
    )
    assert (
        client.get(
            "/api/admin/settings/cookies", auth=("admin", "new-secure-password")
        ).status_code
        == 200
    )
    assert (
        client.get("/api/admin/podcasts", auth=("admin", "new-secure-password")).json()[
            "uses_default_password"
        ]
        is False
    )
    assert client.get("/admin", auth=("admin", "adminadmin")).status_code == 401


def test_admin_settings_require_auth_and_validate_input(monkeypatch, tmp_path):
    from src import config

    path = tmp_path / "config.yaml"
    path.write_text(
        "server:\n  host: 0.0.0.0\n  port: 8001\npodcasts: []\n", encoding="utf-8"
    )
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)

    assert client.get("/api/admin/settings").status_code == 401
    assert client.get("/api/admin/settings", auth=("admin", "secret")).json() == {
        "server": {"host": "0.0.0.0", "port": 8001},
        "youtube": {"cookies_file": "", "cookies_from_browser": ""},
        "admin": {"passkey_origin": "", "passkey_count": 0},
    }
    invalid = client.put(
        "/api/admin/settings",
        auth=("admin", "secret"),
        json={
            "server": {"host": "", "port": 70000},
            "youtube": {"cookies_file": "", "cookies_from_browser": ""},
        },
    )
    assert invalid.status_code == 422
    assert "port: 8001" in path.read_text(encoding="utf-8")


def test_admin_settings_save_without_overwriting_other_config(monkeypatch, tmp_path):
    import yaml
    from src import config

    path = tmp_path / "config.yaml"
    original = {
        "server": {"host": "127.0.0.1", "port": 8000, "custom": True},
        "youtube": {"cookies_file": "/old/cookies.txt", "custom": True},
        "podcasts": [_podcast()],
    }
    path.write_text(yaml.safe_dump(original), encoding="utf-8")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    client = TestClient(main.app)
    payload = {
        "server": {"host": "0.0.0.0", "port": 9000},
        "youtube": {"cookies_file": "", "cookies_from_browser": "firefox"},
    }

    response = client.put("/api/admin/settings", auth=("admin", "secret"), json=payload)

    assert response.status_code == 200
    assert response.json() == {
        **payload,
        "admin": {"passkey_origin": "", "passkey_count": 0},
    }
    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert saved["podcasts"] == original["podcasts"]
    assert saved["server"] == {**original["server"], **payload["server"]}
    assert saved["youtube"] == {"cookies_from_browser": "firefox", "custom": True}
    assert (
        client.put(
            "/api/admin/settings",
            auth=("admin", "secret"),
            json={
                **payload,
                "youtube": {
                    "cookies_file": "/tmp/cookies",
                    "cookies_from_browser": "firefox",
                },
            },
        ).status_code
        == 422
    )
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == saved


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
