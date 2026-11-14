# -*- coding: utf-8 -*-
import sqlite3
from pathlib import Path

import pytest

from src import supervisor, updates
from test_updates import checkout as git_checkout, commit, git

checkout = git_checkout


class Harness(supervisor.Supervisor):
    def __init__(self, root):
        super().__init__(root, cwd=root)
        self.events = []
        self.fail_sync = 0
        self.fail_health = 0
        self.fail_stop = False

    def start(self, verify=False):
        self.events.append("start")

    def stop(self, force=False):
        self.events.append("stop")
        if self.fail_stop:
            raise updates.UpdateError("退出超时")

    def sync(self):
        self.events.append("sync")
        if self.fail_sync:
            self.fail_sync -= 1
            raise updates.UpdateError("依赖安装失败")

    def wait_ready(self, sha):
        self.events.append(f"ready:{sha}")
        if self.fail_health:
            self.fail_health -= 1
            raise updates.UpdateError("启动就绪超时")


def prepare(checkout):
    root, remote, old = checkout
    new = commit(remote, "update")
    (root / "config.yaml").write_text("private: secret\n")
    (root / ".git" / "info" / "exclude").write_text(
        "config.yaml\ndatabase.db\ndownloads/\n"
    )
    with sqlite3.connect(root / "database.db") as db:
        db.execute("create table episodes (name text)")
        db.execute("insert into episodes values ('keep')")
    (root / "downloads").mkdir()
    (root / "downloads" / "audio.mp3").write_bytes(b"audio")
    runner = Harness(root)
    runner.acquire()
    request = {
        "token": runner.token,
        "previous": old,
        "target": new,
        "operation_id": "a" * 32,
    }
    return runner, request


def test_upgrade_success_preserves_data_and_private_backups(checkout):
    runner, request = prepare(checkout)
    try:
        runner.upgrade(request)
        state = updates.read_json(runner.directory / "state.json")
        assert state["phase"] == "success"
        assert runner.repo.head() == request["target"]
        assert runner.events == ["stop", "sync", "start", f"ready:{request['target']}"]
        root = runner.repo.root
        assert (root / "config.yaml").read_text() == "private: secret\n"
        assert (root / "downloads" / "audio.mp3").read_bytes() == b"audio"
        backup = runner.directory / "backups" / request["operation_id"]
        assert (backup / "config.yaml").stat().st_mode & 0o777 == 0o600
        with sqlite3.connect(backup / "database.db") as db:
            assert db.execute("select name from episodes").fetchall() == [("keep",)]
        assert not git(root, "status", "--porcelain")
    finally:
        runner.release()


@pytest.mark.parametrize("failure", ["fail_sync", "fail_health"])
def test_upgrade_failure_restores_old_code_and_restarts(checkout, failure):
    runner, request = prepare(checkout)
    setattr(runner, failure, 1)
    try:
        runner.upgrade(request)
        state = updates.read_json(runner.directory / "state.json")
        assert state["phase"] == "failed"
        assert "已恢复旧版" in state["message"]
        assert runner.repo.head() == request["previous"]
        assert runner.events[-1] == f"ready:{request['previous']}"
    finally:
        runner.release()


def test_recovery_failure_is_reported_and_not_claimed_success(checkout):
    runner, request = prepare(checkout)
    runner.fail_sync = 2
    try:
        runner.upgrade(request)
        state = updates.read_json(runner.directory / "state.json")
        assert state["phase"] == "failed"
        assert "恢复失败" in state["message"]
    finally:
        runner.release()


def test_shutdown_timeout_never_changes_code(checkout):
    runner, request = prepare(checkout)
    runner.fail_stop = True
    try:
        runner.upgrade(request)
        assert runner.repo.head() == request["previous"]
        assert "sync" not in runner.events
    finally:
        runner.release()


@pytest.mark.parametrize(
    "change", ["wrong_token", "wrong_sha", "stale_main", "dirty", "replay"]
)
def test_parent_revalidates_requests_before_stopping(checkout, change):
    runner, request = prepare(checkout)
    root, remote, _ = checkout
    if change == "wrong_token":
        request["token"] = "other-session"
    elif change == "wrong_sha":
        request["target"] = "a" * 40
    elif change == "stale_main":
        commit(remote, "newer update")
    elif change == "dirty":
        (root / "app.txt").write_text("user edit")
    else:
        updates.write_json(
            runner.directory / "state.json", {**request, "phase": "failed"}
        )
    try:
        runner.upgrade(request)
        assert runner.events == []
        assert runner.repo.head() == request["previous"]
        assert updates.read_json(runner.directory / "state.json")["phase"] == "failed"
    finally:
        runner.release()


def test_rollback_will_not_destroy_concurrent_edits(checkout):
    runner, request = prepare(checkout)

    def failure(sha):
        (runner.repo.root / "app.txt").write_text("new user edit")
        raise updates.UpdateError("启动失败")

    runner.wait_ready = failure
    try:
        runner.upgrade(request)
        assert (runner.repo.root / "app.txt").read_text() == "new user edit"
        assert runner.repo.head() == request["target"]
        assert (
            "恢复失败" in updates.read_json(runner.directory / "state.json")["message"]
        )
    finally:
        runner.release()


def test_exclusive_owner_and_stale_requests_are_not_replayed(checkout):
    runner, request = prepare(checkout)
    updates.write_json(runner.directory / "request.json", request)
    try:
        with pytest.raises(updates.UpdateError, match="运行"):
            supervisor.Supervisor(runner.repo.root).acquire()
    finally:
        runner.release()
    other = Harness(runner.repo.root)
    other.acquire()
    try:
        assert not (other.directory / "request.json").exists()
        assert other.token != runner.token
        assert other.repo.head() == request["previous"]
    finally:
        other.release()


def test_interrupted_install_recovers_only_recorded_clean_target(checkout):
    runner, request = prepare(checkout)
    runner.repo.check(request["previous"])
    git(runner.repo.root, "update-ref", supervisor.PREVIOUS_REF, request["previous"])
    git(runner.repo.root, "merge", "--ff-only", request["target"])
    updates.write_json(
        runner.directory / "state.json", {**request, "phase": "installing"}
    )
    runner.release()
    other = Harness(runner.repo.root)
    other.acquire()
    try:
        other.recover_interrupted()
        assert other.repo.head() == request["previous"]
        assert other.running_sha == request["previous"]
        assert other.events == ["sync"]
        assert "中断" in updates.read_json(other.directory / "state.json")["message"]
    finally:
        other.release()


def test_command_timeout_kills_subprocess_and_reports_no_secret(tmp_path):
    with pytest.raises(updates.UpdateError, match="超时") as error:
        updates.command(
            ["python3", "-c", "import time;time.sleep(60)"], tmp_path, timeout=1
        )
    assert "time.sleep" not in str(error.value)


def test_timeout_also_stops_dependency_build_children(tmp_path):
    import sys
    import time

    marker = tmp_path / "orphan.txt"
    child_code = f"import time;from pathlib import Path;time.sleep(2);Path({str(marker)!r}).touch()"
    parent_code = f"import subprocess,time;subprocess.Popen([{sys.executable!r}, '-c', {child_code!r}]);time.sleep(60)"
    with pytest.raises(updates.UpdateError):
        updates.command([sys.executable, "-c", parent_code], tmp_path, timeout=1)
    time.sleep(1.5)
    assert not marker.exists()


def test_upgrade_never_overwrites_ignored_user_data(checkout):
    runner, request = prepare(checkout)
    remote = checkout[1]
    (remote / "config.yaml").write_text("remote: overwrite\n")
    git(remote, "add", "config.yaml")
    request["target"] = commit(remote, "track config")
    try:
        runner.upgrade(request)
        assert (runner.repo.root / "config.yaml").read_text() == "private: secret\n"
        assert runner.repo.head() == request["previous"]
        assert updates.read_json(runner.directory / "state.json")["phase"] == "failed"
    finally:
        runner.release()


def test_signal_requests_shutdown_and_interrupts_operation(checkout):
    runner = Harness(checkout[0])
    with pytest.raises(KeyboardInterrupt):
        runner.on_signal(15, None)
    assert runner.stopping


def test_health_rejects_redirects_wrong_sha_and_stale_tokens(checkout, monkeypatch):
    runner = supervisor.Supervisor(checkout[0])
    runner.directory.mkdir(mode=0o700)
    updates.write_json(
        runner.directory / "ready.json",
        {
            "token": "stale",
            "sha": runner.running_sha,
            "url": "http://127.0.0.1:8001/_internal/update-health",
        },
    )
    monkeypatch.setattr(supervisor, "READY_TIMEOUT", 0)
    with pytest.raises(updates.UpdateError, match="就绪"):
        runner.wait_ready(runner.running_sha)


@pytest.mark.parametrize("reply", ["correct", "wrong_sha", "redirect"])
def test_http_readiness_requires_expected_sha_without_redirects(
    checkout, monkeypatch, reply
):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    runner = supervisor.Supervisor(checkout[0])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.headers.get("X-AnyCast-Supervisor") == runner.token
            self.send_response(302 if reply == "redirect" else 200)
            self.send_header("Location", "http://127.0.0.1:1/must-not-follow")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "sha": runner.running_sha if reply == "correct" else "a" * 40,
                        "ready": True,
                    }
                ).encode()
            )

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    updates.write_json(
        runner.directory / "ready.json",
        {
            "token": runner.token,
            "sha": runner.running_sha,
            "url": f"http://127.0.0.1:{server.server_port}/_internal/update-health",
        },
    )
    monkeypatch.setattr(supervisor, "READY_TIMEOUT", 0.3)
    try:
        if reply == "correct":
            runner.wait_ready(runner.running_sha)
        else:
            with pytest.raises(updates.UpdateError, match="就绪"):
                runner.wait_ready(runner.running_sha)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_start_uses_fresh_python_and_preserves_cwd_and_private_session(
    checkout, monkeypatch
):
    import sys

    runner = supervisor.Supervisor(checkout[0], cwd=checkout[1])
    runner.directory.mkdir(mode=0o700)
    (runner.directory / "ready.json").write_text("stale")
    calls = []
    monkeypatch.setattr(supervisor, "command", lambda *args, **kwargs: sys.executable)
    monkeypatch.setattr(
        supervisor.subprocess,
        "Popen",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )
    runner.start(verify=True)
    args, kwargs = calls[0]
    assert args == [sys.executable, "-m", "src.main"]
    assert kwargs["cwd"] == checkout[1]
    assert kwargs["env"]["ANYCAST_SUPERVISOR_TOKEN"] == runner.token
    assert kwargs["env"]["ANYCAST_UPDATE_VERIFY"] == "1"
    assert kwargs["start_new_session"] is True
    assert not (runner.directory / "ready.json").exists()


def test_stop_terminates_and_reaps_a_real_child(checkout):
    import subprocess
    import sys

    runner = supervisor.Supervisor(checkout[0])
    runner.child = subprocess.Popen(
        [sys.executable, "-c", "import time;time.sleep(60)"], start_new_session=True
    )
    try:
        runner.stop()
        assert runner.child.poll() is not None
    finally:
        if runner.child.poll() is None:
            runner.child.kill()
            runner.child.wait()


def test_run_processes_one_request_and_releases_owner(checkout, monkeypatch):
    from types import SimpleNamespace

    runner, request = prepare(checkout)
    runner.release()
    launches = []

    def start(verify=False):
        launches.append(verify)
        polls = iter([None, None, 0])
        monkeypatch.setattr(
            runner, "child", SimpleNamespace(poll=lambda: next(polls, 0), returncode=0)
        )
        if not verify:
            updates.write_json(runner.directory / "request.json", request)

    monkeypatch.setattr(runner, "start", start)
    monkeypatch.setattr(supervisor.signal, "signal", lambda *args: None)
    assert runner.run() == 0
    assert launches == [False, True]
    assert runner.lock_fd is None
    assert not (runner.directory / "owner.json").exists()
    assert updates.read_json(runner.directory / "state.json")["phase"] == "success"


def test_cli_keeps_private_logs_even_when_package_configured_root_logging(
    checkout, monkeypatch
):
    runner = Harness(checkout[0])
    monkeypatch.setattr(supervisor, "Supervisor", lambda: runner)

    def run():
        supervisor.log.info("private updater audit event")
        return 0

    monkeypatch.setattr(runner, "run", run)
    with pytest.raises(SystemExit) as result:
        supervisor.main()
    assert result.value.code == 0
    logfile = runner.directory / "update.log"
    assert "private updater audit event" in logfile.read_text()
    assert logfile.stat().st_mode & 0o777 == 0o600


def test_cli_falls_back_to_read_only_update_mode_without_git(monkeypatch):
    from src import main

    calls = []

    def unavailable():
        raise updates.UpdateError("not a Git checkout")

    monkeypatch.setattr(supervisor, "Supervisor", unavailable)
    monkeypatch.setattr(main, "main", lambda: calls.append("unmanaged"))
    supervisor.main()
    assert calls == ["unmanaged"]


def test_original_entrypoint_switches_to_supervisor():
    import tomllib

    metadata = tomllib.loads(
        (Path(supervisor.__file__).parents[1] / "pyproject.toml").read_text()
    )
    assert metadata["project"]["scripts"]["anycast"] == "src.supervisor:main"
