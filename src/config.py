# -*- coding: utf-8 -*-
from typing import Literal, TypedDict
from apscheduler.executors.base import logging
from pathlib import Path
import hashlib
import os
import tempfile
import threading
import yaml


class Podcast(TypedDict):
    name: str
    url: str
    update_period_cron: str
    keep_latest: int | None  # 不填则保留全部已下载剧集，仅首次抓取最新若干集
    sort_by: Literal["date", "title"]
    sort_order: Literal["asc", "desc"]
    page_size: int  # 每次从播放列表最新的一端取多少条参与筛选
    yt_dlp_options: dict  # 透传给 yt-dlp 的额外参数，覆盖内置默认值


class ServerConfig(TypedDict, total=False):
    host: str
    port: int


class YouTubeConfig(TypedDict, total=False):
    cookies_file: str
    cookies_from_browser: str


class Config(TypedDict):
    podcasts: list[Podcast]
    server: ServerConfig
    youtube: YouTubeConfig


log = logging.getLogger(__name__)

__configFile = "config.yaml"
_config_lock = threading.Lock()

# 每次从播放列表取多少条参与筛选。播放列表可能有上百条，而每条没缓存的都要
# 单独解析一次详情，所以默认只取最新的一段。
DEFAULT_PAGE_SIZE = 20


def __get_config_file() -> str:
    config_path = Path(__file__).resolve().parents[1] / __configFile
    if not config_path.exists():
        raise FileNotFoundError(
            "Missing config.yaml. 请先复制 config.yaml.example 为 config.yaml 并按需修改后重试。"
        )
    return str(config_path)


def __check_podcast_name_is_unique(podcasts: list[Podcast]):
    return set(podcast["name"] for podcast in podcasts).__len__() == len(podcasts)


def __apply_podcast_defaults(podcast: dict) -> Podcast:
    """补全可选字段：keep_latest 缺省为 None（不清理旧集），排序缺省按最新发布。"""
    keep_latest = podcast.get("keep_latest")
    return {
        **podcast,
        "keep_latest": int(keep_latest) if keep_latest is not None else None,
        "sort_by": podcast.get("sort_by") or "date",
        "sort_order": podcast.get("sort_order") or "desc",
        "page_size": int(podcast.get("page_size") or DEFAULT_PAGE_SIZE),
        "yt_dlp_options": podcast.get("yt_dlp_options") or {},
    }  # type: ignore[return-value]


def check_config_file():
    with open(__get_config_file(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    if not __check_podcast_name_is_unique(config["podcasts"]):
        raise Exception("Podcast name must be unique")


def get_config() -> Config:
    with open(__get_config_file(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    config["podcasts"] = [
        __apply_podcast_defaults(podcast) for podcast in config["podcasts"]
    ]
    return config


def _write_config(config: dict) -> None:
    path = Path(__get_config_file())
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    # shortcut: PyYAML 不保留手写注释；需要保留注释时再换 round-trip YAML 库。
    temporary.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def get_admin_password_hash() -> str | None:
    with open(__get_config_file(), "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return (config.get("admin") or {}).get("password_hash")


def update_admin_password_hash(previous_hash: str | None, password_hash: str) -> None:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        admin = config.get("admin") or {}
        if admin.get("password_hash") != previous_hash:
            raise ValueError("密码已被其他请求修改，请刷新后重试")
        config["admin"] = {**admin, "password_hash": password_hash}
        _write_config(config)


def get_admin_settings() -> dict:
    config = get_config()
    server = config.get("server") or {}
    youtube = config.get("youtube") or {}
    return {
        "server": {
            "host": server.get("host", "0.0.0.0"),
            "port": server.get("port", 8000),
        },
        "youtube": {
            "cookies_file": youtube.get("cookies_file") or "",
            "cookies_from_browser": youtube.get("cookies_from_browser") or "",
        },
    }


def update_admin_settings(server: ServerConfig, youtube: YouTubeConfig) -> None:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        config["server"] = {**(config.get("server") or {}), **server}
        existing_youtube = dict(config.get("youtube") or {})
        existing_youtube.pop("cookies_file", None)
        existing_youtube.pop("cookies_from_browser", None)
        config["youtube"] = {
            **existing_youtube,
            **{key: value for key, value in youtube.items() if value},
        }
        _write_config(config)


def get_admin_cookie_file() -> dict:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        path = (config.get("youtube") or {}).get("cookies_file")
        if not path:
            raise FileNotFoundError("未配置 Cookie 文件")
        if not Path(path).is_file():
            raise FileNotFoundError(f"Cookie 文件不存在或不是普通文件：{path}")
        with open(path, "rb") as f:
            content = f.read(1048577)
        if len(content) > 1048576:
            raise ValueError("Cookie 文件超过 1 MiB，无法在线编辑")
        return {
            "path": path,
            "content": content.decode("utf-8"),
            "revision": hashlib.sha256(content).hexdigest(),
        }


def update_admin_cookie_file(path: str, content: str, revision: str) -> str:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        configured = (config.get("youtube") or {}).get("cookies_file")
        if not configured or path != configured:
            raise ValueError("Cookie 文件路径已改变，请刷新页面")
        target = Path(configured)
        if not target.is_file():
            raise FileNotFoundError(f"Cookie 文件不存在：{configured}")
        if target.is_symlink():
            raise ValueError("请将 Cookie 文件路径指向实际文件，而不是符号链接")
        with open(target, "rb") as f:
            current = f.read(1048577)
        if hashlib.sha256(current).hexdigest() != revision:
            raise ValueError("Cookie 文件已被修改，请刷新页面后重试")
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return hashlib.sha256(content.encode("utf-8")).hexdigest()


def add_podcast(podcast: Podcast) -> None:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        podcasts = config.setdefault("podcasts", [])
        if any(item.get("name") == podcast["name"] for item in podcasts):
            raise ValueError(f"播客 {podcast['name']} 已存在")
        podcasts.append(dict(podcast))
        _write_config(config)


def update_podcast(name: str, podcast: Podcast) -> None:
    if podcast["name"] != name:
        raise ValueError("不能修改播客名称")
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        podcasts = config.get("podcasts", [])
        for index, current in enumerate(podcasts):
            if current.get("name") == name:
                podcasts[index] = {
                    **current,
                    **podcast,
                    "yt_dlp_options": current.get("yt_dlp_options") or {},
                }
                _write_config(config)
                return
        raise ValueError(f"播客 {name} 不存在")


def remove_podcast(name: str) -> None:
    with _config_lock:
        with open(__get_config_file(), "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        podcasts = config.get("podcasts", [])
        remaining = [item for item in podcasts if item.get("name") != name]
        if len(remaining) == len(podcasts):
            raise ValueError(f"播客 {name} 不存在")
        config["podcasts"] = remaining
        _write_config(config)
