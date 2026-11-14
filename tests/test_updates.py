# -*- coding: utf-8 -*-
import json
import subprocess

import pytest

from src import updates


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


def commit(path, text):
    (path / "app.txt").write_text(text)
    git(path, "add", "app.txt")
    git(
        path,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.com",
        "commit",
        "-qm",
        text,
    )
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    remote = tmp_path / "remote"
    remote.mkdir()
    git(remote, "init", "-b", "main")
    old = commit(remote, "initial")
    root = tmp_path / "checkout"
    subprocess.run(
        ["git", "clone", str(remote), str(root)], check=True, capture_output=True
    )
    monkeypatch.setattr(updates, "SOURCE", str(remote))
    return root, remote, old


def test_checks_real_main_history_and_pins_running_version(checkout):
    root, remote, old = checkout
    repo = updates.Repository(root)
    assert repo.check(old)["relation"] == "current"
    new = commit(remote, "new version")
    result = repo.check(old)
    assert result["latest_sha"] == new
    assert result["latest_message"] == "new version"
    assert result["relation"] == "behind"
    assert result["update_available"] is True
    git(root, "merge", "--ff-only", new)
    assert repo.check(old)["reason"] == "运行版本与工作树不一致，请先重启服务"


@pytest.mark.parametrize("kind", ["tracked", "staged", "untracked"])
def test_local_changes_block_install(checkout, kind):
    root, remote, old = checkout
    commit(remote, "new version")
    (root / ("app.txt" if kind != "untracked" else "new.txt")).write_text("user edit")
    if kind == "staged":
        git(root, "add", "app.txt")
    result = updates.Repository(root).check(old)
    assert result["can_update"] is False
    assert "未提交" in result["reason"]
    assert (
        root / ("app.txt" if kind != "untracked" else "new.txt")
    ).read_text() == "user edit"


def test_ahead_diverged_and_wrong_branch_are_not_overwritten(checkout):
    root, remote, _ = checkout
    local = commit(root, "local version")
    repo = updates.Repository(root)
    assert repo.check(local)["relation"] == "ahead"
    commit(remote, "remote version")
    assert repo.check(local)["relation"] == "diverged"
    git(root, "checkout", "-b", "feature")
    assert "main" in repo.check(local)["reason"]


def test_failed_fetch_and_non_git_are_explicit(checkout, monkeypatch, tmp_path):
    root, _, old = checkout
    monkeypatch.setattr(updates, "SOURCE", str(tmp_path / "missing"))
    with pytest.raises(updates.UpdateError, match="git fetch"):
        updates.Repository(root).check(old)
    service = updates.UpdateService(tmp_path)
    status = service.check()
    assert status["can_update"] is False
    assert status["error"]


def test_private_atomic_json_and_corrupt_state(tmp_path):
    path = tmp_path / "private" / "state.json"
    updates.write_json(path, {"phase": "success"})
    assert updates.read_json(path) == {"phase": "success"}
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    path.write_text("[")
    with pytest.raises(updates.UpdateError, match="状态"):
        updates.read_json(path)


def test_queue_rejects_unmanaged_bad_targets_and_duplicate_requests(
    checkout, monkeypatch
):
    root, remote, old = checkout
    new = commit(remote, "new version")
    service = updates.UpdateService(root)
    service.check()
    with pytest.raises(updates.UpdateError, match="受管"):
        service.queue(new)
    monkeypatch.setattr(service, "managed", lambda: True)
    with pytest.raises(updates.UpdateError, match="目标"):
        service.queue("a" * 40)
    result = service.queue(new)
    request = updates.read_json(service.repo.state_dir / "request.json")
    assert request["target"] == new
    assert request["previous"] == old
    assert result["phase"] == "preparing"
    with pytest.raises(updates.UpdateError, match="更新中"):
        service.queue(new)
    assert (
        json.loads((service.repo.state_dir / "request.json").read_text())["target"]
        == new
    )


def test_check_failure_does_not_advertise_cached_upgrade(checkout, monkeypatch):
    root, remote, _ = checkout
    commit(remote, "new version")
    service = updates.UpdateService(root)
    monkeypatch.setattr(service, "managed", lambda: True)
    assert service.check()["can_update"] is True
    monkeypatch.setattr(updates, "CHECK_INTERVAL", 0)
    monkeypatch.setattr(updates, "SOURCE", str(root / "missing"))
    status = service.check()
    assert status["error"]
    assert status["can_update"] is False
