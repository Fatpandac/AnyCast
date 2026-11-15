# -*- coding: utf-8 -*-
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src import downloader, ytdlp


def _fake_binary(tmp_path: Path) -> tuple[Path, Path]:
    calls = tmp_path / "calls.jsonl"
    binary = tmp_path / "yt-dlp"
    binary.write_text(
        f"#!{sys.executable}\n"
        "import json, pathlib, sys, time\n"
        f"root = pathlib.Path({str(tmp_path)!r})\n"
        "with (root / 'calls.jsonl').open('a') as f:\n"
        "    f.write(json.dumps(sys.argv[1:]) + '\\n')\n"
        "if '--version' in sys.argv:\n"
        "    print((root / 'version').read_text())\n"
        "elif '--update' in sys.argv:\n"
        "    if (root / 'update-fails').exists():\n"
        "        print('Use brew upgrade yt-dlp', file=sys.stderr); sys.exit(1)\n"
        "    (root / 'version').write_text('2026.10.26')\n"
        "else:\n"
        "    if (root / 'sleep').exists(): time.sleep(30)\n"
        "    if '--cookies' in sys.argv:\n"
        "        pathlib.Path(sys.argv[sys.argv.index('--cookies') + 1]).write_text('changed')\n"
        "    print('ERROR: No route to host' if (root / 'fails').exists() else '[download] 100%', file=sys.stderr)\n"
        "    result = (root / 'result').read_text()\n"
        "    if '--no-simulate' in sys.argv: print('[download] 100%')\n"
        "    if '--print-to-file' in sys.argv:\n"
        "        pathlib.Path(sys.argv[sys.argv.index('--print-to-file') + 2]).write_text(result)\n"
        "    else: print(result)\n"
        "    sys.exit(1 if (root / 'fails').exists() else 0)\n",
        encoding="utf-8",
    )
    binary.chmod(0o755)
    (tmp_path / "version").write_text("2026.10.26")
    (tmp_path / "result").write_text('{"id": "video"}')
    return binary, calls


@pytest.fixture
def external(monkeypatch, tmp_path):
    binary, calls = _fake_binary(tmp_path)
    settings = {"executable": str(binary), "auto_update": False}
    monkeypatch.setattr(downloader, "get_config", lambda: {"youtube": settings})
    monkeypatch.setattr(ytdlp, "_update_error", None, raising=False)
    downloader.request_stop_reset()
    yield settings, calls
    downloader.request_stop_reset()


def _extract(options=None, download=False):
    return downloader._extract_youtube_info(
        "https://www.youtube.com/watch?v=video", download, options or {}
    )


def _calls(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_external_binary_is_checked_before_each_execution(external):
    _, calls = external
    assert _extract() == {"id": "video"}
    _extract()
    commands = _calls(calls)
    assert len(commands) == 4
    assert commands[0] == ["--ignore-config", "--version"]
    assert commands[2] == commands[0]
    assert "--dump-single-json" in commands[1]
    assert "--skip-download" in commands[1]
    assert commands[1][-2:] == ["--", "https://www.youtube.com/watch?v=video"]
    assert not any("--update" in command for command in commands)


def test_missing_binary_has_installation_hint(external):
    settings, _ = external
    settings["executable"] = "/missing/yt-dlp"
    with pytest.raises(RuntimeError, match="yt-dlp.*安装"):
        _extract()


@pytest.mark.parametrize("version", ["2025.12.08", "not-a-version"])
def test_incompatible_version_is_rejected_before_extraction(
    external, tmp_path, version
):
    (tmp_path / "version").write_text(version)
    with pytest.raises(RuntimeError, match="版本"):
        _extract()
    assert len(_calls(external[1])) == 1


def test_auto_update_is_optional_and_throttled_under_concurrency(external, tmp_path):
    settings, calls = external
    settings["auto_update"] = True
    (tmp_path / "version").write_text("2025.12.08")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: _extract(), range(4)))
    assert results == [{"id": "video"}] * 4
    commands = _calls(calls)
    assert sum("--update" in command for command in commands) == 1
    assert commands[0] == ["--ignore-config", "--update"]


def test_failed_auto_update_logs_hint_and_keeps_compatible_version(
    external, tmp_path, caplog
):
    external[0]["auto_update"] = True
    (tmp_path / "update-fails").touch()
    assert _extract() == {"id": "video"}
    assert "brew upgrade yt-dlp" in caplog.text


def test_upgrade_failure_is_visible_until_a_successful_upgrade(external, tmp_path):
    external[0]["auto_update"] = True
    (tmp_path / "update-fails").touch()
    assert _extract() == {"id": "video"}
    update_error = ytdlp.get_update_error()
    assert update_error is not None
    assert "brew upgrade yt-dlp" in update_error
    # A successful extraction must not erase the failed upgrade notification.
    _extract()
    assert ytdlp.get_update_error() is not None
    (tmp_path / "update-fails").unlink()
    ytdlp._last_update_attempt.clear()
    _extract()
    assert ytdlp.get_update_error() is None


def test_failed_auto_update_does_not_allow_old_version(external, tmp_path):
    external[0]["auto_update"] = True
    (tmp_path / "version").write_text("2025.12.08")
    (tmp_path / "update-fails").touch()
    with pytest.raises(RuntimeError, match="版本"):
        _extract()


def test_cookie_file_is_copied_and_cli_options_are_translated(external, tmp_path):
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("original")
    _extract(
        {
            "cookiefile": str(cookies),
            "extract_flat": True,
            "proxy": "http://127.0.0.1:7890",
            "extractor_args": {"youtube": {"player_client": ["default", "-tv"]}},
            "js_runtimes": {"node": {}},
        }
    )
    command = _calls(external[1])[-1]
    assert cookies.read_text() == "original"
    assert command[command.index("--cookies") + 1] != str(cookies)
    assert "--flat-playlist" in command
    assert command[command.index("--proxy") + 1] == "http://127.0.0.1:7890"
    assert "youtube:player_client=default,-tv" in command
    assert "node" in command


def test_unsupported_api_option_is_not_silently_ignored(external):
    with pytest.raises(ValueError, match="unsupported_option"):
        _extract({"unsupported_option": True})


def test_download_uses_final_filepath_json_and_non_simulation(external):
    assert _extract(download=True) == {"id": "video"}
    command = _calls(external[1])[-1]
    assert "--no-simulate" in command
    assert "--print-to-file" in command
    assert "after_move:%()j" in command
    assert "--skip-download" not in command


def test_process_error_is_logged_and_never_returns_partial_download(
    external, tmp_path, caplog
):
    (tmp_path / "fails").touch()
    with pytest.raises(RuntimeError, match="yt-dlp"):
        _extract(download=True)
    assert "No route to host" in caplog.text


def test_ignored_metadata_error_logs_and_returns_empty(external, tmp_path, caplog):
    (tmp_path / "fails").touch()
    (tmp_path / "result").write_text("")
    assert _extract({"ignoreerrors": True}) == {}
    assert "No route to host" in caplog.text


def test_invalid_json_is_rejected(external, tmp_path):
    (tmp_path / "result").write_text("invalid JSON")
    with pytest.raises(RuntimeError, match="JSON"):
        _extract()


def test_auto_update_interval_and_busy_download_are_respected(external, monkeypatch):
    settings, calls = external
    settings["auto_update"] = True
    clock = [1_000_000.0]
    monkeypatch.setattr(ytdlp.time, "monotonic", lambda: clock[0])
    _extract()
    clock[0] += ytdlp.UPDATE_INTERVAL + 1
    monkeypatch.setattr(ytdlp, "_active_processes", 1)
    _extract()
    assert sum("--update" in cmd for cmd in _calls(calls)) == 1
    monkeypatch.setattr(ytdlp, "_active_processes", 0)
    _extract()
    assert sum("--update" in cmd for cmd in _calls(calls)) == 2


@pytest.mark.parametrize(
    "setting,value", [("auto_update", "false"), ("executable", [])]
)
def test_invalid_external_settings_are_rejected(external, setting, value):
    external[0][setting] = value
    with pytest.raises(ValueError, match=setting):
        _extract()


def test_version_probe_timeout_has_clear_error(external, monkeypatch):
    import subprocess

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 10)

    monkeypatch.setattr(ytdlp.subprocess, "run", timeout)
    with pytest.raises(RuntimeError, match="检查 yt-dlp 版本"):
        _extract()


def test_update_timeout_still_checks_current_version(external, monkeypatch, caplog):
    import subprocess

    external[0]["auto_update"] = True
    run = subprocess.run

    def timeout_update(args, **kwargs):
        if "--update" in args:
            raise subprocess.TimeoutExpired(args, 120)
        return run(args, **kwargs)

    monkeypatch.setattr(ytdlp.subprocess, "run", timeout_update)
    assert _extract() == {"id": "video"}
    assert "自动升级失败" in caplog.text
    assert ytdlp.get_update_error() is not None


@pytest.mark.parametrize("raw", ["[]", "null"])
def test_non_object_json_is_rejected(external, tmp_path, raw):
    (tmp_path / "result").write_text(raw)
    with pytest.raises(RuntimeError, match="JSON"):
        _extract()


def test_ignored_null_metadata_is_empty(external, tmp_path):
    (tmp_path / "result").write_text("null")
    assert _extract({"ignoreerrors": True}) == {}


def test_stopped_command_is_not_started(external):
    downloader.request_stop()
    with pytest.raises(RuntimeError, match="取消"):
        _extract()
    assert len(_calls(external[1])) == 1


def test_options_keep_browser_headers_paths_and_audio_quality():
    args = ytdlp._options_to_args(
        {
            "cookiesfrombrowser": ("firefox", "profile", "basictext", "personal"),
            "paths": {"home": "/tmp/audio"},
            "outtmpl": {"default": "%(id)s.%(ext)s"},
            "http_headers": {"User-Agent": "AnyCast"},
            "js_runtimes": {"node": {"path": "/bin/node"}},
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "128",
                }
            ],
            "skip_download": True,
            "noplaylist": False,
            "no_warnings": False,
            "proxy": None,
        }
    )
    assert args == [
        "--cookies-from-browser",
        "firefox+basictext:profile::personal",
        "--paths",
        "home:/tmp/audio",
        "--output",
        "%(id)s.%(ext)s",
        "--add-headers",
        "User-Agent:AnyCast",
        "--js-runtimes",
        "node:/bin/node",
        "--extract-audio",
        "--audio-format",
        "m4a",
        "--audio-quality",
        "128",
        "--yes-playlist",
    ]


@pytest.mark.parametrize(
    "options",
    [
        {"proxy": []},
        {"quiet": "false"},
        {"skip_download": 1},
        {"paths": []},
        {"extractor_args": {"youtube": []}},
        {"js_runtimes": {"node": {"unknown": 1}}},
        {"cookiesfrombrowser": "chrome"},
        {"postprocessors": [{"key": "Unsupported"}]},
        {"postprocessors": {}},
        {"postprocessors": ["invalid"]},
    ],
)
def test_invalid_api_options_fail_explicitly(options):
    with pytest.raises(ValueError):
        ytdlp._options_to_args(options)


def test_stop_terminates_external_process(external, tmp_path):
    import time

    (tmp_path / "sleep").touch()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_extract)
        deadline = time.monotonic() + 5
        while (
            not external[1].exists() or len(_calls(external[1])) < 2
        ) and time.monotonic() < deadline:
            time.sleep(0.02)
        downloader.request_stop()
        with pytest.raises(RuntimeError, match="取消"):
            future.result(timeout=5)
