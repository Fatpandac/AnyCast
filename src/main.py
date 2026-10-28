# -*- coding: utf-8 -*-
from __future__ import annotations

import mimetypes
import logging
from logging.handlers import RotatingFileHandler
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import quote, urlsplit
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from fastapi.security import HTTPBasicCredentials
from typing import Annotated
from fastapi import Depends, FastAPI, Query
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from feedgen.feed import FeedGenerator
from src.admin import (
    CookieFilePayload,
    PasswordPayload,
    PodcastPayload,
    SettingsPayload,
    check_admin_request_origin,
    hash_admin_password,
    require_admin,
    uses_default_admin_password,
    verify_admin_password,
    _security,
)
from src.config import (
    add_podcast,
    check_config_file,
    get_admin_settings,
    get_admin_cookie_file,
    get_admin_password_hash,
    get_passkey_config,
    update_passkey_origin,
    get_config,
    remove_podcast,
    update_admin_cookie_file,
    update_admin_password_hash,
    update_admin_settings,
    update_podcast,
)
from src import passkeys
from src.database import (
    count_episodes_by_podcast,
    get_episodes,
    get_podcast,
    init_database,
)
from src.downloader import run_downloader, request_stop, request_stop_reset
from src.jobs import start_cron_jobs, stop_cron_jobs, sync_cron_jobs


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


log = logging.getLogger(__name__)
RUNTIME_LOG_PATH = Path("logs/anycast-runtime.log")
LOG_BACKUPS = 5


def start_runtime_log() -> RotatingFileHandler:
    # shortcut: file rotation assumes one writer; use a shared log service with multiple workers.
    RUNTIME_LOG_PATH.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    handler = PrivateRotatingFileHandler(
        RUNTIME_LOG_PATH,
        maxBytes=10 * 1024 * 1024,
        backupCount=LOG_BACKUPS,
        encoding="utf-8",
    )
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    return handler


@asynccontextmanager
async def lifespan(_app: FastAPI):
    check_config_file()
    init_database()
    request_stop_reset()
    config = get_config()
    runtime_handler = start_runtime_log()
    download_tasks = [
        asyncio.create_task(run_downloader(podcast)) for podcast in config["podcasts"]
    ]
    start_cron_jobs()
    yield
    request_stop()
    for task in download_tasks:
        task.cancel()
    await asyncio.gather(*download_tasks, return_exceptions=True)
    stop_cron_jobs()
    logging.getLogger().removeHandler(runtime_handler)
    runtime_handler.close()


app = FastAPI(
    title="AnyCast",
    debug=os.getenv("DEBUG", "").lower() in ("1", "true", "yes"),
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_admin_static_dir = Path(__file__).resolve().parent / "admin_static"
_admin_index = _admin_static_dir / "index.html"
app.mount(
    "/admin/assets",
    StaticFiles(directory=_admin_static_dir / "assets", check_dir=False),
    name="admin-assets",
)


@app.get("/")
async def root():
    podcasts = _get_podcasts_from_file()
    return {"status": "ok", "podcast_count": len(podcasts)}


def _runtime_log_page(before: str | None, after: str | None = None) -> dict:
    paths = [
        RUNTIME_LOG_PATH,
        *(Path(f"{RUNTIME_LOG_PATH}.{i}") for i in range(1, LOG_BACKUPS + 1)),
    ]
    files = [
        (path, path.stat()) for path in paths if path.is_file() and path.stat().st_size
    ]
    if not files:
        return {"lines": [], "before": None, "after": None}
    if after:
        inode, position = map(int, after.split(":"))
        index = next(
            (i for i, (_, stat) in enumerate(files) if stat.st_ino == inode), None
        )
        if index is None or position > files[index][1].st_size:
            raise HTTPException(status_code=409, detail="日志已轮转，正在加载最新记录")
        lines: list[bytes] = []
        cursor = after
        for path, stat in reversed(files[: index + 1]):
            with path.open("rb") as stream:
                stream.seek(position if stat.st_ino == inode else 0)
                while stream.tell() < stat.st_size and len(lines) < 100:
                    line = stream.readline(stat.st_size - stream.tell())
                    if not line.endswith(b"\n"):
                        break
                    lines.append(line)
                    cursor = f"{stat.st_ino}:{stream.tell()}"
            if len(lines) == 100:
                break
        return {
            "lines": [
                line.decode("utf-8", errors="replace").rstrip("\r\n") for line in lines
            ],
            "before": None,
            "after": cursor,
        }
    if before:
        inode, position = map(int, before.split(":"))
        index = next(
            (i for i, (_, stat) in enumerate(files) if stat.st_ino == inode), None
        )
        if index is None or position > files[index][1].st_size:
            raise HTTPException(
                status_code=409, detail="更早的日志已轮转，无法继续加载"
            )
    else:
        index, position = 0, files[0][1].st_size

    lines: list[bytes] = []
    cursor = None
    while index < len(files) and len(lines) < 100:
        path, stat = files[index]
        with path.open("rb") as stream:
            data = b""
            offset = position
            while offset > 0 and data.count(b"\n") <= 100 - len(lines):
                count = min(offset, 8192)
                offset -= count
                stream.seek(offset)
                data = stream.read(count) + data
            entries = data.splitlines(keepends=True)
            if offset > 0:
                entries = entries[1:]  # first fragment may start mid-line
            selected = entries[-(100 - len(lines)) :]
            start = position - sum(map(len, selected))
            lines = selected + lines
        index += 1
        cursor = (
            f"{stat.st_ino}:{start}"
            if start > 0
            else (
                f"{files[index][1].st_ino}:{files[index][1].st_size}"
                if index < len(files)
                else None
            )
        )
        position = files[index][1].st_size if index < len(files) else 0
    return {
        "lines": [
            line.decode("utf-8", errors="replace").rstrip("\r\n") for line in lines
        ],
        "before": cursor,
        "after": f"{files[0][1].st_ino}:{files[0][1].st_size}",
    }


@app.get("/api/admin/logs")
async def admin_logs(
    response: Response,
    before: Annotated[
        str | None, Query(max_length=50, pattern=r"^[0-9]+:[0-9]+$")
    ] = None,
    after: Annotated[
        str | None, Query(max_length=50, pattern=r"^[0-9]+:[0-9]+$")
    ] = None,
    _auth: None = Depends(require_admin),
):
    if before and after:
        raise HTTPException(status_code=422, detail="只能指定 before 或 after")
    response.headers["Cache-Control"] = "no-store"
    return _runtime_log_page(before, after)


@app.get("/api/admin/settings")
async def admin_settings(_auth: None = Depends(require_admin)):
    return get_admin_settings()


@app.put("/api/admin/settings")
async def admin_save_settings(
    payload: SettingsPayload, request: Request, _auth: None = Depends(require_admin)
):
    check_admin_request_origin(request)
    update_admin_settings(
        {"host": payload.server.host, "port": payload.server.port},
        {
            "cookies_file": payload.youtube.cookies_file,
            "cookies_from_browser": payload.youtube.cookies_from_browser,
        },
    )
    return get_admin_settings()


@app.put("/api/admin/settings/password")
async def admin_change_password(
    payload: PasswordPayload, request: Request, _auth: None = Depends(require_admin)
):
    check_admin_request_origin(request)
    previous_hash = get_admin_password_hash()
    if not verify_admin_password(payload.current_password):
        raise HTTPException(status_code=403, detail="当前密码错误")
    if (
        payload.new_password == payload.current_password
        or payload.new_password == "adminadmin"
    ):
        raise HTTPException(
            status_code=422, detail="新密码不能与当前密码或默认密码相同"
        )
    try:
        update_admin_password_hash(
            previous_hash, hash_admin_password(payload.new_password)
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "updated"}


@app.get("/api/admin/settings/cookies")
async def admin_cookie_file(
    request: Request, response: Response, _auth: None = Depends(require_admin)
):
    check_admin_request_origin(request)
    response.headers["Cache-Control"] = "no-store"
    try:
        return get_admin_cookie_file()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, UnicodeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.put("/api/admin/settings/cookies")
async def admin_save_cookie_file(
    payload: CookieFilePayload, request: Request, _auth: None = Depends(require_admin)
):
    check_admin_request_origin(request)
    try:
        revision = update_admin_cookie_file(
            payload.path, payload.content, payload.revision
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"revision": revision}


@app.get("/api/admin/podcasts")
async def admin_podcasts(_auth: None = Depends(require_admin)):
    podcasts = [
        {**podcast, "episode_count": count_episodes_by_podcast(podcast["name"])}
        for podcast in _get_podcasts_from_file()
    ]
    return {
        "podcasts": podcasts,
        "uses_default_password": uses_default_admin_password(),
    }


@app.post("/api/admin/podcasts", status_code=201)
async def admin_add_podcast(
    payload: PodcastPayload,
    request: Request,
    _auth: None = Depends(require_admin),
):
    check_admin_request_origin(request)
    podcast = payload.to_podcast()
    try:
        add_podcast(podcast)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    init_database()
    sync_cron_jobs()
    return {"podcast": podcast}


@app.put("/api/admin/podcasts/{name}")
async def admin_update_podcast(
    name: str,
    payload: PodcastPayload,
    request: Request,
    _auth: None = Depends(require_admin),
):
    check_admin_request_origin(request)
    if payload.name != name:
        raise HTTPException(status_code=400, detail="不能修改播客名称")
    podcast = payload.to_podcast()
    try:
        update_podcast(name, podcast)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    init_database()
    sync_cron_jobs()
    return {"podcast": podcast}


@app.get("/api/admin/podcasts/{name}")
async def admin_podcast_detail(name: str, _auth: None = Depends(require_admin)):
    podcast = next(
        (item for item in _get_podcasts_from_file() if item["name"] == name), None
    )
    if not podcast:
        raise HTTPException(status_code=404, detail=f"Podcast {name} not found")
    episodes = get_episodes(name, sort_by="date", sort_order="desc")
    return {"podcast": podcast, "episodes": episodes}


@app.delete("/api/admin/podcasts/{name}")
async def admin_remove_podcast(
    name: str, request: Request, _auth: None = Depends(require_admin)
):
    check_admin_request_origin(request)
    try:
        remove_podcast(name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    sync_cron_jobs()
    return {"status": "removed"}


class PasskeyOriginPayload(BaseModel):
    origin: str

    @field_validator("origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        if not value:
            return value
        parsed = urlsplit(value.rstrip("/"))
        host = parsed.hostname or ""
        if (
            parsed.scheme != "https"
            or not host
            or "." not in host
            or parsed.username
            or parsed.password
            or ":" in parsed.netloc
            or parsed.path not in ("", "/")
            or parsed.query
            or parsed.fragment
            or value.count("/") > 3
            or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in host)
        ):
            raise ValueError("请输入完整的 HTTPS 域名，不包含路径或参数")
        return f"https://{host}"


class PasskeyCredentialPayload(BaseModel):
    challenge: str = Field(min_length=32, max_length=256)
    credential: dict


@app.put("/api/admin/settings/passkey-origin")
async def admin_passkey_origin(
    payload: PasskeyOriginPayload,
    request: Request,
    _auth: None = Depends(require_admin),
):
    check_admin_request_origin(request)
    update_passkey_origin(payload.origin)
    return get_admin_settings()["admin"]


def _require_strong_password() -> None:
    if uses_default_admin_password():
        raise HTTPException(403, "请先修改默认管理员密码，再注册 Passkey")


@app.post("/api/admin/passkeys/register/options")
async def admin_passkey_registration_options(
    request: Request, _auth: None = Depends(require_admin)
):
    _require_strong_password()
    return passkeys.registration_options(request)


@app.post("/api/admin/passkeys/register/verify")
async def admin_passkey_registration(
    payload: PasskeyCredentialPayload,
    request: Request,
    _auth: None = Depends(require_admin),
):
    _require_strong_password()
    passkeys.register(request, payload.challenge, payload.credential)
    return get_admin_settings()["admin"]


@app.post("/api/admin/passkeys/login/options")
async def admin_passkey_auth_options(request: Request):
    return passkeys.authentication_options(request)


@app.post("/api/admin/passkeys/login/verify")
async def admin_passkey_auth(
    payload: PasskeyCredentialPayload, request: Request, response: Response
):
    session = passkeys.authenticate(request, payload.challenge, payload.credential)
    response.set_cookie(
        passkeys.COOKIE,
        session,
        max_age=12 * 3600,
        secure=True,
        httponly=True,
        samesite="lax",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@app.get("/admin/basic", include_in_schema=False)
async def admin_basic(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
):
    try:
        require_admin(request, credentials)
    except HTTPException as exc:
        if exc.status_code == 401:
            raise HTTPException(
                401, "请使用管理员密码登录", headers={"WWW-Authenticate": "Basic"}
            ) from exc
        raise
    return RedirectResponse("/admin", status_code=303)


@app.get("/admin", include_in_schema=False)
@app.get("/admin/{path:path}", include_in_schema=False)
async def admin_spa(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
):
    if request.url.path != "/admin/login":
        try:
            require_admin(request, credentials)
        except HTTPException as exc:
            if exc.status_code != 401 or not get_passkey_config().get("passkeys"):
                raise
            return RedirectResponse("/admin/login", status_code=303)
    if not _admin_index.exists():
        raise HTTPException(
            status_code=503,
            detail="管理前端尚未构建，请运行 pnpm install && pnpm build",
        )
    return FileResponse(_admin_index)


def _get_podcasts_from_file():
    return get_config()["podcasts"]


def podcast_exists(name: str):
    return name in list(map(lambda podcast: podcast["name"], _get_podcasts_from_file()))


def _build_rss(
    channel_title: str,
    channel_link: str,
    channel_rss_url: str,
    channel_description: str,
    channel_image: str | None,
    episodes: list[dict],
    name: str,
    request: Request,
) -> bytes:
    _BRANDING = "由 AnyCast 生成 · https://github.com/Fatpandac/AnyCast"
    fg = FeedGenerator()
    fg.load_extension("podcast")
    fg.id(channel_rss_url)
    fg.title(channel_title)
    fg.link(href=channel_link)
    fg.description(channel_description)
    if channel_image:
        fg.podcast.itunes_image(channel_image)  # type: ignore[attr-defined]
        fg.image(url=channel_image, title=channel_title, link=channel_link)

    for ep in episodes:
        encoded_name = quote(ep["file_name"])
        ep_url = str(
            request.url_for("podcast_media", name=name, file_name=encoded_name)
        )
        media_type, _ = mimetypes.guess_type(ep["file_name"])
        media_file = Path("downloads") / name / ep["file_name"]
        file_size = media_file.stat().st_size if media_file.exists() else 0

        fe = fg.add_entry()
        fe.id(ep["episode_id"])
        fe.title(ep["title"] or ep["file_name"])
        fe.link(href=ep_url)
        fe.enclosure(ep_url, file_size, media_type or "audio/mpeg")
        desc = ep.get("description") or ""
        fe.description(f"{desc}\n\n{_BRANDING}" if desc else _BRANDING)
        if ep.get("cover_image_url"):
            fe.podcast.itunes_image(ep["cover_image_url"])  # type: ignore[attr-defined]

        raw_pub = ep.get("published_at") or ep.get("created_at")
        if raw_pub:
            try:
                pub_dt = datetime.fromisoformat(str(raw_pub))
            except ValueError:
                pub_dt = datetime.strptime(str(raw_pub), "%Y-%m-%d %H:%M:%S")
            if pub_dt.tzinfo is None:
                pub_dt = pub_dt.replace(tzinfo=timezone.utc)
            fe.published(pub_dt)

    return fg.rss_str(pretty=True)


@app.get("/podcasts")
async def podcasts():
    return {"podcasts": _get_podcasts_from_file()}


@app.get("/podcasts/{name}", name="podcast_info")
async def podcasts_with_name(name: str, request: Request):
    if podcast_exists(name):
        config = list(filter(lambda it: it["name"] == name, _get_podcasts_from_file()))[
            0
        ]
        return {
            "name": name,
            "rss": str(request.url_for("podcast_rss", name=name)),
            "config": config,
        }
    else:
        raise HTTPException(status_code=404, detail=f"Podcast {name} not found")


@app.get("/media/{name}/{file_name}")
async def podcast_media(name: str, file_name: str):
    media_dir = Path("downloads") / name
    media_file = media_dir / Path(file_name).name
    if not media_file.exists():
        raise HTTPException(status_code=404, detail="media not found")
    media_type, _ = mimetypes.guess_type(media_file.name)
    return FileResponse(media_file, media_type=media_type or "application/octet-stream")


@app.get("/rss/{name}", name="podcast_rss")
async def podcast_rss(name: str, request: Request):
    if not podcast_exists(name):
        raise HTTPException(status_code=404, detail=f"Podcast {name} not found")

    config = list(filter(lambda it: it["name"] == name, _get_podcasts_from_file()))[0]
    podcast_row = get_podcast(name) or {}
    channel_title: str = podcast_row.get("channel_title") or config["name"]
    channel_description: str = (
        podcast_row.get("channel_description")
        or "由 AnyCast 生成 · https://github.com/Fatpandac/AnyCast"
    )
    channel_image: str | None = podcast_row.get("channel_image") or None

    episodes = get_episodes(
        name,
        limit=config["keep_latest"],
        sort_by="date",
        sort_order="desc",
    )
    if not channel_image and episodes:
        channel_image = episodes[0].get("cover_image_url")

    rss_bytes = _build_rss(
        channel_title=channel_title,
        channel_link=str(request.url_for("podcast_info", name=name)),
        channel_rss_url=str(request.url_for("podcast_rss", name=name)),
        channel_description=channel_description,
        channel_image=channel_image,
        episodes=episodes,
        name=name,
        request=request,
    )
    return Response(content=rss_bytes, media_type="application/rss+xml; charset=utf-8")


def main():
    import uvicorn

    config = get_config()
    server = config.get("server", {})
    host = server.get("host", "0.0.0.0")
    port = server.get("port", 8000)
    uvicorn.run(
        app, host=host, port=port, log_level="debug", timeout_graceful_shutdown=2
    )


if __name__ == "__main__":
    main()
