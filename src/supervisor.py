# -*- coding: utf-8 -*-
"""Small POSIX parent process; survives replacement of the app and its venv."""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import time
from pathlib import Path
from types import FrameType
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from src.updates import (
    ACTIVE_PHASES,
    ROOT,
    SHA,
    Repository,
    UpdateError,
    command,
    read_json,
    write_json,
)

PREVIOUS_REF = "refs/anycast-updates/previous"
READY_TIMEOUT = 30
log = logging.getLogger(__name__)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# shortcut: the live parent keeps its loaded protocol; restart the launcher when updating supervisor logic.
class Supervisor:
    def __init__(self, root: Path = ROOT, cwd: Path | None = None):
        self.repo = Repository(root)
        self.directory = self.repo.state_dir
        self.cwd = cwd or Path.cwd()
        self.running_sha = self.repo.head()
        self.token = secrets.token_hex(32)
        self.child: subprocess.Popen | None = None
        self.lock_fd: int | None = None
        self.stopping = False
        self.request: dict = {}

    def acquire(self) -> None:
        import fcntl

        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        fd = os.open(self.directory / "supervisor.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(fd)
            raise UpdateError("同一工作树已有受管应用运行") from exc
        self.lock_fd = fd
        write_json(
            self.directory / "owner.json", {"pid": os.getpid(), "token": self.token}
        )
        # Requests belong to one live parent session, never the next startup.
        (self.directory / "request.json").unlink(missing_ok=True)

    def release(self) -> None:
        if self.lock_fd is not None:
            (self.directory / "owner.json").unlink(missing_ok=True)
            os.close(self.lock_fd)
            self.lock_fd = None

    def state(self, phase: str, message: str) -> None:
        write_json(
            self.directory / "state.json",
            {
                **{
                    k: self.request[k]
                    for k in ("previous", "target", "operation_id")
                    if k in self.request
                },
                "session": self.token,
                "phase": phase,
                "message": message,
            },
        )
        log.info("应用更新 [%s]: %s", phase, message)

    def start(self, verify: bool = False) -> None:
        uv = shutil.which("uv")
        if not uv:
            raise UpdateError("找不到 uv，无法启动服务")
        python = command(
            [
                uv,
                "run",
                "--no-sync",
                "python",
                "-c",
                "import sys; print(sys.executable)",
            ],
            self.repo.root,
        )
        (self.directory / "ready.json").unlink(missing_ok=True)
        env = {
            **os.environ,
            "ANYCAST_SUPERVISOR_TOKEN": self.token,
            "ANYCAST_UPDATE_VERIFY": "1" if verify else "0",
        }
        self.child = subprocess.Popen(
            [python, "-m", "src.main"],
            cwd=self.cwd,
            env=env,
            start_new_session=True,
        )

    def stop(self, force: bool = False) -> None:
        if not self.child or self.child.poll() is not None:
            return
        try:
            os.killpg(self.child.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            self.child.wait(timeout=10)
        except subprocess.TimeoutExpired as exc:
            if not force:
                raise UpdateError("服务退出超时，未修改代码，请检查终端后重启") from exc
            os.killpg(self.child.pid, signal.SIGKILL)
            self.child.wait(timeout=5)

    def sync(self) -> None:
        uv = shutil.which("uv")
        if not uv:
            raise UpdateError("找不到 uv，无法安装依赖")
        command([uv, "sync", "--locked"], self.repo.root, timeout=600)

    def wait_ready(self, sha: str) -> None:
        deadline = time.monotonic() + READY_TIMEOUT
        opener = build_opener(ProxyHandler({}), NoRedirect())
        while time.monotonic() < deadline:
            if self.child and self.child.poll() is not None:
                raise UpdateError("新服务提前退出，启动失败")
            ready = read_json(self.directory / "ready.json")
            url = ready.get("url", "")
            parsed = urlsplit(url)
            if (
                ready.get("token") == self.token
                and ready.get("sha") == sha
                and parsed.scheme == "http"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and parsed.path == "/_internal/update-health"
                and not parsed.query
            ):
                try:
                    request = Request(url, headers={"X-AnyCast-Supervisor": self.token})
                    with opener.open(request, timeout=1) as response:
                        health = json.loads(response.read(4096))
                    if health == {"sha": sha, "ready": True}:
                        return
                except (URLError, OSError, ValueError):
                    pass
            time.sleep(0.2)
        raise UpdateError("服务启动就绪检查超时")

    def backup(self) -> None:
        backup = self.directory / "backups" / self.request["operation_id"]
        backup.mkdir(mode=0o700, parents=True, exist_ok=False)
        os.chmod(backup.parent, 0o700)
        config = self.repo.root / "config.yaml"
        if config.is_file():
            target = backup / "config.yaml"
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "wb") as stream, config.open("rb") as source:
                shutil.copyfileobj(source, stream)
        database = self.cwd / "database.db"
        if database.is_file():
            target = backup / "database.db"
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
            with (
                sqlite3.connect(f"file:{database}?mode=ro", uri=True) as source,
                sqlite3.connect(target) as dest,
            ):
                source.backup(dest)

    def restore_code(self, previous: str, target: str) -> None:
        if (
            not isinstance(previous, str)
            or not isinstance(target, str)
            or not SHA.fullmatch(previous)
            or not SHA.fullmatch(target)
            or self.repo.git("rev-parse", PREVIOUS_REF) != previous
            or self.repo.git("branch", "--show-current") != "main"
            or self.repo.git("status", "--porcelain", "--untracked-files=normal")
        ):
            raise UpdateError("不能安全回退：存在本地修改或恢复记录不匹配，请人工处理")
        head = self.repo.head()
        if head == target:
            self.repo.git("-c", "core.hooksPath=/dev/null", "reset", "--keep", previous)
        elif head != previous:
            raise UpdateError("工作树已被其他操作修改，拒绝覆盖")

    def recover_interrupted(self) -> None:
        state = read_json(self.directory / "state.json")
        if state.get("phase") not in ACTIVE_PHASES:
            return
        self.request = state
        if state.get("phase") in {"installing", "restarting", "recovering"}:
            self.restore_code(state.get("previous", ""), state.get("target", ""))
            self.sync()
        self.running_sha = self.repo.head()
        self.state("failed", "上次更新已中断，已取消遗留请求并恢复旧版代码")

    def upgrade(self, request: dict) -> None:
        stopped = False
        try:
            prior = read_json(self.directory / "state.json")
            if (
                not all(
                    isinstance(request.get(key), str)
                    for key in ("token", "target", "previous", "operation_id")
                )
                or request.get("token") != self.token
                or not SHA.fullmatch(request.get("target", ""))
                or not SHA.fullmatch(request.get("previous", ""))
                or not re.fullmatch(r"[0-9a-f]{32}", request.get("operation_id", ""))
                or request.get("previous") != self.running_sha
                or request.get("operation_id") == prior.get("operation_id")
            ):
                raise UpdateError("更新请求无效、已处理或不属于当前运行会话")
            self.request = request
            self.state("preparing", "正在验证 main 提交并备份数据")
            result = self.repo.check(request["previous"])
            if not result["can_update"] or result["latest_sha"] != request["target"]:
                raise UpdateError(
                    result["reason"] or "main 已变化，请重新检查并确认目标"
                )
            self.repo.git("update-ref", PREVIOUS_REF, request["previous"])
            self.backup()
            self.stop()
            stopped = True
            reason = self.repo.eligibility(request["previous"])
            if reason:
                raise UpdateError(reason)
            self.state("installing", "正在快进代码并安装锁定依赖")
            self.repo.git(
                "-c",
                "core.hooksPath=/dev/null",
                "merge",
                "--ff-only",
                "--no-edit",
                "--no-overwrite-ignore",
                request["target"],
            )
            self.sync()
            self.state("restarting", "正在重启并验证运行版本")
            self.start(verify=True)
            self.wait_ready(request["target"])
            self.running_sha = request["target"]
            self.state("success", "更新成功，运行版本已确认")
        except (UpdateError, OSError, sqlite3.Error) as exc:
            message = (
                str(exc)
                if isinstance(exc, UpdateError)
                else "更新文件操作失败，请检查私有更新日志"
            )
            if stopped:
                try:
                    self.state("recovering", "更新失败，正在恢复旧版")
                    self.stop(force=True)
                    self.restore_code(request["previous"], request["target"])
                    self.sync()
                    self.start(verify=True)
                    self.wait_ready(request["previous"])
                    self.running_sha = request["previous"]
                    message += "；已恢复旧版"
                except (UpdateError, OSError) as recovery:
                    self.stop(force=True)
                    message += f"；恢复失败，请人工处理：{recovery}"
            self.state("failed", message)

    def on_signal(self, _signum: int, _frame: FrameType | None) -> None:
        self.stopping = True
        raise KeyboardInterrupt

    def run(self) -> int:
        self.acquire()
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, self.on_signal)
            self.recover_interrupted()
            self.start()
            while self.child and self.child.poll() is None:
                path = self.directory / "request.json"
                if path.exists():
                    request = read_json(path)
                    path.unlink()
                    self.upgrade(request)
                time.sleep(0.2)
            return self.child.returncode if self.child and self.child.returncode else 0
        except KeyboardInterrupt:
            return 0
        finally:
            try:
                self.stop(force=True)
            finally:
                self.release()


def main() -> None:
    try:
        if os.name != "posix" or not shutil.which("uv"):
            raise UpdateError("受管更新需要 macOS/Linux 和 uv")
        runner = Supervisor()
    except UpdateError as exc:
        log.warning("在线安装不可用，使用普通服务模式：%s", exc)
        from src.main import main as serve

        serve()
        return
    try:
        runner.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(runner.directory, 0o700)
        logfile = runner.directory / "update.log"
        fd = os.open(logfile, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
        os.close(fd)
        os.chmod(logfile, 0o600)
        handler = logging.FileHandler(logfile, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
        try:
            code = runner.run()
        finally:
            log.removeHandler(handler)
            handler.close()
        raise SystemExit(code)
    except (UpdateError, OSError) as exc:
        raise SystemExit(f"AnyCast 启动/更新失败：{exc}") from exc
