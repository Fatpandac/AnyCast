# -*- coding: utf-8 -*-
import tomllib
from pathlib import Path

from src.main import app


ROOT = Path(__file__).resolve().parents[1]


def test_project_metadata_uses_anycast_name():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    previous_name = "bili" + "cast"

    assert pyproject["project"]["name"] == "anycast"
    assert "anycast" in pyproject["project"]["scripts"]
    assert previous_name not in pyproject["project"]["scripts"]


def test_readme_title_uses_anycast_name():
    title = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0]

    assert title == "# AnyCast"


def test_api_title_uses_anycast_name():
    assert app.title == "AnyCast"
