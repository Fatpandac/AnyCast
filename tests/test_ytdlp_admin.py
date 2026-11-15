# -*- coding: utf-8 -*-
from fastapi.testclient import TestClient

from src import config, main, ytdlp


def test_ytdlp_status_requires_auth_and_is_not_cached(monkeypatch, tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("podcasts: []\n")
    monkeypatch.setattr(config, "__get_config_file", lambda: str(path))
    monkeypatch.setenv("ANYCAST_ADMIN_PASSWORD", "secret")
    monkeypatch.setattr(
        ytdlp, "_update_error", "ERROR: Use pip to update", raising=False
    )
    client = TestClient(main.app)

    assert client.get("/api/admin/ytdlp").status_code == 401
    response = client.get("/api/admin/ytdlp", auth=("admin", "secret"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"update_error": "ERROR: Use pip to update"}
    monkeypatch.setattr(ytdlp, "_update_error", None)
    assert client.get("/api/admin/ytdlp", auth=("admin", "secret")).json() == {
        "update_error": None
    }
