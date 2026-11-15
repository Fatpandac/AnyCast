# -*- coding: utf-8 -*-
"""External yt-dlp command adapter; no dependency on its Python environment."""

from __future__ import annotations

import contextlib
import errno
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from src.config import YouTubeConfig

log = logging.getLogger(__name__)
MIN_VERSION = (2026, 10, 26)
UPDATE_INTERVAL = 24 * 60 * 60
_execution_lock = threading.Lock()
_active_processes = 0
_last_update_attempt: dict[str, float] = {}
_update_error: str | None = None


def get_update_error() -> str | None:
    return _update_error


@contextlib.contextmanager
def _checked_binary(settings: YouTubeConfig):
    global _active_processes, _update_error
    executable = settings.get("executable", "yt-dlp")
    if not isinstance(executable, str):
        raise ValueError("youtube.executable 必须是 yt-dlp 命令或路径")
    auto_update = settings.get("auto_update", False)
    if not isinstance(auto_update, bool):
        raise ValueError("youtube.auto_update 必须是 true 或 false")
    binary = shutil.which(os.path.expanduser(executable))
    if not binary:
        raise RuntimeError(
            f"找不到可执行的 yt-dlp：{executable}。请先安装 yt-dlp，"
            "确保它在 PATH 中，或设置 youtube.executable 为绝对路径。"
        )
    with _execution_lock:
        now = time.monotonic()
        # Only update while idle, so concurrent metadata/download processes keep their installation intact.
        if (
            auto_update
            and not _active_processes
            and now - _last_update_attempt.get(binary, -UPDATE_INTERVAL)
            >= UPDATE_INTERVAL
        ):
            _last_update_attempt[binary] = now
            try:
                result = subprocess.run(
                    [binary, "--ignore-config", "--update"],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    stdin=subprocess.DEVNULL,
                    timeout=120,
                )
                message = (result.stdout + result.stderr).strip()
                if result.returncode:
                    _update_error = (
                        message or f"yt-dlp --update 退出码 {result.returncode}"
                    )
                    log.warning(
                        "yt-dlp 自动升级失败，请使用安装时的包管理器升级（如 brew upgrade yt-dlp）：%s",
                        _update_error,
                    )
                else:
                    _update_error = None
                    log.info("yt-dlp 自动升级检查：%s", message)
            except (OSError, subprocess.TimeoutExpired) as exc:
                _update_error = str(exc)
                log.warning("yt-dlp 自动升级失败，请手动升级：%s", exc)
        try:
            result = subprocess.run(
                [binary, "--ignore-config", "--version"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdin=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"无法检查 yt-dlp 版本：{binary}；{exc}") from exc
        version = result.stdout.strip()
        match = re.fullmatch(r"(\d{4})\.(\d{1,2})\.(\d{1,2})(?:[.\w+-]*)", version)
        if result.returncode or not match:
            raise RuntimeError(
                f"无法识别 yt-dlp 版本：{version or result.stderr.strip()}"
            )
        if tuple(map(int, match.groups())) < MIN_VERSION:
            required = ".".join(map(str, MIN_VERSION))
            raise RuntimeError(
                f"yt-dlp 版本 {version} 过旧，需要 >= {required}。请独立升级 yt-dlp：{binary}"
            )
        log.info("使用外部 yt-dlp：%s（版本 %s）", binary, version)
        _active_processes += 1
    try:
        yield binary
    finally:
        with _execution_lock:
            _active_processes -= 1


def _options_to_args(options: dict) -> list[str]:
    """Keep the documented API-style options; reject unsupported options instead of changing their meaning."""
    scalar = {
        "format": "--format",
        "proxy": "--proxy",
        "cookiefile": "--cookies",
        "socket_timeout": "--socket-timeout",
        "retries": "--retries",
        "fragment_retries": "--fragment-retries",
        "extractor_retries": "--extractor-retries",
        "concurrent_fragment_downloads": "--concurrent-fragments",
        "ratelimit": "--limit-rate",
        "source_address": "--source-address",
        "ffmpeg_location": "--ffmpeg-location",
        "sleep_interval": "--sleep-interval",
        "max_sleep_interval": "--max-sleep-interval",
        "sleep_interval_requests": "--sleep-requests",
        "impersonate": "--impersonate",
    }
    boolean = {
        "quiet": ("--quiet", "--no-quiet"),
        "no_warnings": ("--no-warnings", None),
        "noplaylist": ("--no-playlist", "--yes-playlist"),
        "ignoreerrors": ("--ignore-errors", "--abort-on-error"),
        "extract_flat": ("--flat-playlist", "--no-flat-playlist"),
        "skip_unavailable_fragments": (
            "--skip-unavailable-fragments",
            "--abort-on-unavailable-fragments",
        ),
        "nocheckcertificate": ("--no-check-certificates", None),
        "continuedl": ("--continue", "--no-continue"),
        "overwrites": ("--force-overwrites", "--no-overwrites"),
    }
    args: list[str] = []
    for key, value in options.items():
        if value is None:
            continue
        if key in scalar:
            if isinstance(value, bool) or not isinstance(value, (str, int, float)):
                raise ValueError(f"yt_dlp_options.{key} 必须是字符串或数值")
            args.extend([scalar[key], str(value)])
        elif key in boolean:
            if not isinstance(value, bool):
                raise ValueError(f"yt_dlp_options.{key} 必须是 true 或 false")
            flag = boolean[key][0 if value else 1]
            if flag:
                args.append(flag)
        elif key == "skip_download":
            if not isinstance(value, bool):
                raise ValueError("yt_dlp_options.skip_download 必须是 true 或 false")
            # The caller decides metadata-only vs download mode, not user configuration.
        elif key in (
            "paths",
            "outtmpl",
            "http_headers",
            "extractor_args",
            "js_runtimes",
        ):
            if not isinstance(value, dict):
                raise ValueError(f"yt_dlp_options.{key} 必须是字典")
            for name, item in value.items():
                if key == "extractor_args":
                    if not isinstance(item, dict):
                        raise ValueError("extractor_args 中每个提取器的参数必须是字典")
                    encoded = ";".join(
                        f"{arg}={','.join(map(str, val)) if isinstance(val, (list, tuple)) else val}"
                        for arg, val in item.items()
                    )
                    args.extend(["--extractor-args", f"{name}:{encoded}"])
                elif key == "js_runtimes":
                    if not isinstance(item, dict) or set(item) - {"path"}:
                        raise ValueError("js_runtimes 仅支持 path 配置")
                    args.extend(
                        [
                            "--js-runtimes",
                            f"{name}:{item['path']}" if item.get("path") else str(name),
                        ]
                    )
                else:
                    flag = {
                        "paths": "--paths",
                        "outtmpl": "--output",
                        "http_headers": "--add-headers",
                    }[key]
                    args.extend(
                        [
                            flag,
                            (
                                str(item)
                                if key == "outtmpl" and name == "default"
                                else f"{name}:{item}"
                            ),
                        ]
                    )
        elif key == "cookiesfrombrowser":
            if not isinstance(value, (list, tuple)) or len(value) != 4:
                raise ValueError(
                    "cookiesfrombrowser 必须是 [browser, profile, keyring, container]"
                )
            browser, profile, keyring, container = value
            spec = str(browser)
            if keyring:
                spec += f"+{keyring}"
            if profile:
                spec += f":{profile}"
            if container:
                spec += f"::{container}"
            args.extend(["--cookies-from-browser", spec])
        elif key == "postprocessors":
            if not isinstance(value, list):
                raise ValueError("postprocessors 必须是列表")
            for processor in value:
                if (
                    not isinstance(processor, dict)
                    or processor.get("key") != "FFmpegExtractAudio"
                    or set(processor) - {"key", "preferredcodec", "preferredquality"}
                ):
                    raise ValueError("外部 yt-dlp 仅支持 FFmpegExtractAudio 后处理配置")
                args.extend(
                    [
                        "--extract-audio",
                        "--audio-format",
                        processor.get("preferredcodec", "m4a"),
                    ]
                )
                if "preferredquality" in processor:
                    args.extend(["--audio-quality", str(processor["preferredquality"])])
        else:
            raise ValueError(
                f"外部 yt-dlp 不支持 yt_dlp_options 参数：{key}；请删除或改用已支持的参数"
            )
    return args


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.wait()
    except ProcessLookupError:
        process.wait()


def extract_info(
    url: str,
    download: bool,
    options: dict,
    settings: YouTubeConfig,
    stop: threading.Event,
) -> dict:
    args = _options_to_args(options)
    with (
        _checked_binary(settings) as binary,
        tempfile.TemporaryDirectory() as temporary,
    ):
        result_path = Path(temporary) / "result.json"
        if download:
            # Progress is also written to stdout; keep machine-readable results in a separate file.
            args.extend(
                [
                    "--no-simulate",
                    "--no-playlist",
                    "--print-to-file",
                    "after_move:%()j",
                    str(result_path),
                    "--progress",
                    "--newline",
                    "--progress-delta",
                    "1",
                ]
            )
        else:
            args.extend(["--skip-download", "--dump-single-json"])
        if stop.is_set():
            raise RuntimeError("yt-dlp 操作已取消")
        last_error: list[str] = []
        with (
            result_path.open("w+", encoding="utf-8") as output,
            subprocess.Popen(
                [binary, "--ignore-config", "--no-update", *args, "--", url],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if download else output,
                stderr=subprocess.STDOUT if download else subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=os.name == "posix",
            ) as process,
        ):

            def read_log():
                stream = process.stdout if download else process.stderr
                assert stream is not None
                for raw in stream:
                    line = raw.rstrip()
                    if not line:
                        continue
                    level = (
                        logging.ERROR
                        if "ERROR:" in line
                        else logging.WARNING if "WARNING:" in line else logging.INFO
                    )
                    if level == logging.ERROR:
                        last_error[:] = [line]
                    log.log(level, "%s", line)

            reader = threading.Thread(target=read_log, daemon=True)
            reader.start()
            try:
                while True:
                    try:
                        process.wait(timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        if stop.is_set():
                            raise RuntimeError("yt-dlp 操作已取消")
            finally:
                _terminate(process)
                reader.join()
            if stop.is_set():
                raise RuntimeError("yt-dlp 操作已取消")
            if process.returncode and (download or not options.get("ignoreerrors")):
                message = (
                    last_error[0] if last_error else f"退出码 {process.returncode}"
                )
                if "No space left on device" in message:
                    raise OSError(errno.ENOSPC, message)
                raise RuntimeError(f"yt-dlp 执行失败：{message}")
        raw = result_path.read_text(encoding="utf-8").strip()
        if not raw and not download and options.get("ignoreerrors"):
            return {}
        try:
            info = json.loads(raw)
        except ValueError as exc:
            raise RuntimeError("yt-dlp 未返回有效 JSON，请检查运行日志") from exc
        if info is None and not download and options.get("ignoreerrors"):
            return {}
        if not isinstance(info, dict):
            raise RuntimeError("yt-dlp 返回的 JSON 不是对象")
        return info
