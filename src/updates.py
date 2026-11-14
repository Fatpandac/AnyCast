# -*- coding: utf-8 -*-
"""Fixed-source Git checks and private IPC; no application dependencies."""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://github.com/Fatpandac/AnyCast.git"
UPDATE_REF = "refs/anycast-updates/main"
CHECK_INTERVAL = 60
ACTIVE_PHASES = {"preparing", "installing", "restarting", "recovering"}
SHA = re.compile(r"^[0-9a-f]{40}$")


class UpdateError(Exception):
    pass


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("not an object")
        return value
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise UpdateError("更新状态文件无效，请检查终端日志") from exc


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".update-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def command(args: list[str], cwd: Path, timeout: int = 30) -> str:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_SSH_COMMAND="ssh -oBatchMode=yes")
    try:
        process = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise UpdateError(f"{Path(args[0]).name} {args[1]} 无法执行") from exc
    try:
        stdout, _stderr = process.communicate(timeout=timeout)
    except BaseException as exc:
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
        process.communicate()
        if isinstance(exc, subprocess.TimeoutExpired):
            raise UpdateError(f"{Path(args[0]).name} {args[1]} 执行超时") from exc
        raise
    if process.returncode:
        # Do not expose command output: dependency URLs may contain credentials.
        operation = "fetch" if "fetch" in args else args[1]
        raise UpdateError(
            f"{Path(args[0]).name} {operation} 失败（退出码 {process.returncode}）"
        )
    return stdout.strip()


class Repository:
    def __init__(self, root: Path = ROOT):
        self.root = root.resolve()

    def git(self, *args: str) -> str:
        return command(["git", *args], self.root)

    @property
    def state_dir(self) -> Path:
        path = Path(self.git("rev-parse", "--git-path", "anycast-updates"))
        return path if path.is_absolute() else self.root / path

    def head(self) -> str:
        if Path(self.git("rev-parse", "--show-toplevel")).resolve() != self.root:
            raise UpdateError("当前安装不是独立 Git 源码目录")
        return self.git("rev-parse", "HEAD")

    def eligibility(self, running_sha: str | None) -> str:
        if self.head() != running_sha:
            return "运行版本与工作树不一致，请先重启服务"
        if self.git("branch", "--show-current") != "main":
            return "仅支持 main 分支更新"
        if self.git("status", "--porcelain", "--untracked-files=normal"):
            return "工作区有未提交修改，请先自行处理"
        if os.name != "posix" or not shutil.which("uv"):
            return "更新需要 macOS/Linux 和 uv"
        if not os.access(self.root, os.W_OK):
            return "代码目录不可写"
        return ""

    def check(self, running_sha: str | None) -> dict:
        self.head()
        self.git("fetch", "--no-tags", "--", SOURCE, f"+refs/heads/main:{UPDATE_REF}")
        latest = self.git("rev-parse", UPDATE_REF)
        if (
            not SHA.fullmatch(latest)
            or not running_sha
            or not SHA.fullmatch(running_sha)
        ):
            raise UpdateError("无法确定运行版本或远端目标提交")
        if latest == running_sha:
            relation = "current"
        else:
            try:
                base = self.git("merge-base", running_sha, latest)
            except UpdateError:
                base = ""
            relation = (
                "behind"
                if base == running_sha
                else "ahead" if base == latest else "diverged"
            )
        reason = self.eligibility(running_sha)
        if not reason and relation in {"ahead", "diverged"}:
            reason = (
                "本地提交领先 main"
                if relation == "ahead"
                else "提交历史已分叉或 main 被强推，请人工处理"
            )
        return {
            "current_sha": running_sha,
            "latest_sha": latest,
            "latest_message": self.git("show", "-s", "--format=%s", latest),
            "latest_date": self.git("show", "-s", "--format=%cI", latest),
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "relation": relation,
            "update_available": relation == "behind",
            "can_update": relation == "behind" and not reason,
            "reason": reason,
        }


class UpdateService:
    def __init__(self, root: Path = ROOT):
        self.repo = Repository(root)
        try:
            self.running_sha: str | None = self.repo.head()
        except UpdateError:
            self.running_sha = None
        self.token = os.getenv("ANYCAST_SUPERVISOR_TOKEN", "")
        self.lock = threading.Lock()
        self.last_check = 0.0
        self.requested = False
        self.request_id = ""
        self.cached: dict = {
            "current_sha": self.running_sha,
            "latest_sha": None,
            "latest_message": "",
            "latest_date": None,
            "checked_at": None,
            "relation": "unknown",
            "update_available": False,
            "can_update": False,
            "reason": "尚未检查更新",
            "error": "",
        }

    def managed(self) -> bool:
        if not self.token:
            return False
        owner = read_json(self.repo.state_dir / "owner.json")
        return owner.get("token") == self.token and owner.get("pid") == os.getppid()

    def operation(self) -> dict:
        if not self.running_sha:
            return {}
        state = read_json(self.repo.state_dir / "state.json")
        return {
            k: state[k]
            for k in ("phase", "target", "previous", "message", "operation_id")
            if k in state
        }

    def busy(self) -> bool:
        operation = self.operation()
        if (
            self.requested
            and operation.get("operation_id") == self.request_id
            and operation.get("phase") not in ACTIVE_PHASES
        ):
            self.requested = False
        return self.requested or (
            self.managed() and operation.get("phase") in ACTIVE_PHASES
        )

    def status(self) -> dict:
        result = {**self.cached, **self.operation()}
        result.setdefault("phase", "idle")
        reason = ""
        try:
            reason = self.repo.eligibility(self.running_sha)
            if not self.managed():
                reason = reason or "请用 uv run anycast 受管模式重启一次后再安装更新"
            if self.busy():
                reason = "应用更新中"
        except UpdateError as exc:
            reason = str(exc)
        if reason:
            result.update(can_update=False, reason=reason)
        if result.get("error"):
            result["can_update"] = False
        if self.requested and result["phase"] not in ACTIVE_PHASES:
            result["phase"] = "preparing"
        return result

    def check(self) -> dict:
        with self.lock:
            if self.busy():
                return self.status()
            if time.monotonic() - self.last_check >= CHECK_INTERVAL:
                try:
                    self.cached.update(self.repo.check(self.running_sha), error="")
                except UpdateError as exc:
                    self.cached.update(error=str(exc), can_update=False)
                self.last_check = time.monotonic()
            return self.status()

    def queue(self, target: str) -> dict:
        with self.lock:
            if self.busy():
                raise UpdateError("应用更新中，请勿重复提交")
            if not self.managed():
                raise UpdateError("需要 uv run anycast 受管模式")
            if not SHA.fullmatch(target) or target != self.cached.get("latest_sha"):
                raise UpdateError("目标提交无效，请重新检查更新")
            status = self.status()
            if not status["can_update"]:
                raise UpdateError(
                    status.get("error") or status["reason"] or "当前不能更新"
                )
            import secrets

            self.request_id = secrets.token_hex(16)
            write_json(
                self.repo.state_dir / "request.json",
                {
                    "token": self.token,
                    "target": target,
                    "previous": self.running_sha,
                    "operation_id": self.request_id,
                },
            )
            self.requested = True
            return {
                **status,
                "phase": "preparing",
                "target": target,
                "can_update": False,
            }
