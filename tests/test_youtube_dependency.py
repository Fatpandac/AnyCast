# -*- coding: utf-8 -*-
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_is_not_managed_by_project_dependencies():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert not any(
        value.startswith(("yt-dlp", "yt_dlp"))
        for value in project["project"]["dependencies"]
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    assert not {"yt-dlp", "yt-dlp-ejs"} & {item["name"] for item in lock["package"]}
    for name in ("requirements.lock", "requirements-dev.lock"):
        assert "yt-dlp==" not in (ROOT / name).read_text(encoding="utf-8")
