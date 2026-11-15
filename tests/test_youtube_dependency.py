# -*- coding: utf-8 -*-
import tomllib
from importlib.metadata import version
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


ROOT = Path(__file__).resolve().parents[1]


def test_youtube_dependency_requires_the_verified_compatible_release():
    required = Version("2026.10.26")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert Version("3.10") not in SpecifierSet(project["project"]["requires-python"])
    requirements = [Requirement(value) for value in project["project"]["dependencies"]]
    youtube = next(item for item in requirements if item.name == "yt-dlp")
    assert any(
        spec.operator in (">=", "==") and Version(spec.version) >= required
        for spec in youtube.specifier
    )
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    locked = next(item for item in lock["package"] if item["name"] == "yt-dlp")
    assert Version(locked["version"]) >= required
    assert Version(version("yt-dlp")) >= required
