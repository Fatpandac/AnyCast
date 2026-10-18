# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import hashlib
import secrets
from typing import Annotated, Literal
from urllib.parse import urlparse, urlsplit

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, field_validator, model_validator

from src.config import DEFAULT_PAGE_SIZE, Podcast, get_admin_password_hash
from src.passkeys import session_valid


_security = HTTPBasic(auto_error=False)
_DEFAULT_ADMIN_PASSWORD = "adminadmin"


class PasswordPayload(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=128)


class ServerSettings(BaseModel):
    host: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9.:-]+$")
    port: int = Field(ge=1, le=65535, strict=True)


class YouTubeSettings(BaseModel):
    cookies_file: str = ""
    cookies_from_browser: str = ""

    @model_validator(mode="after")
    def check_cookie_source(self):
        if self.cookies_file and self.cookies_from_browser:
            raise ValueError("只能选择一种 YouTube Cookie 来源")
        return self


class SettingsPayload(BaseModel):
    server: ServerSettings
    youtube: YouTubeSettings


class CookieFilePayload(BaseModel):
    path: str
    revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    content: str = Field(max_length=1048576)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.startswith(("# Netscape HTTP Cookie File", "# HTTP Cookie File")):
            raise ValueError("请输入 Netscape 格式的 Cookie 文件内容")
        if len(value.encode("utf-8")) > 1048576:
            raise ValueError("Cookie 文件不能超过 1 MiB")
        return value


class PodcastPayload(BaseModel):
    name: str = Field(pattern=r"^[\w-]{1,64}$")
    url: str
    update_period_cron: str
    keep_latest: int | None = Field(default=None, gt=0)
    sort_by: Literal["date", "title"] = "date"
    sort_order: Literal["asc", "desc"] = "desc"
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, gt=0)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("请输入有效的 HTTP(S) 播放列表地址")
        return value

    @field_validator("update_period_cron")
    @classmethod
    def validate_cron(cls, value: str) -> str:
        try:
            CronTrigger.from_crontab(value)
        except ValueError as exc:
            raise ValueError("Cron 表达式无效") from exc
        return value

    def to_podcast(self) -> Podcast:
        return {
            "name": self.name,
            "url": self.url,
            "update_period_cron": self.update_period_cron,
            "keep_latest": self.keep_latest,
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "page_size": self.page_size,
            "yt_dlp_options": {},
        }


def _verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return secrets.compare_digest(
            password.encode(),
            os.getenv("ANYCAST_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD).encode(),
        )
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != 200000:
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        )
        return secrets.compare_digest(actual, bytes.fromhex(expected))
    except ValueError:
        return False


def verify_admin_password(password: str) -> bool:
    return _verify_password(password, get_admin_password_hash())


def hash_admin_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200000)
    return f"pbkdf2_sha256$200000${salt.hex()}${digest.hex()}"


def require_admin(
    request: Request,
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
) -> None:
    from src.config import get_passkey_config

    if session_valid(request):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = get_passkey_config().get("passkey_origin")
            if request.headers.get("origin") != origin:
                raise HTTPException(status_code=403, detail="拒绝跨站管理请求")
        return
    expected_username = os.getenv("ANYCAST_ADMIN_USERNAME", "admin")
    username = credentials.username if credentials else ""
    password = credentials.password if credentials else ""
    valid = secrets.compare_digest(username.encode(), expected_username.encode())
    valid &= verify_admin_password(password)
    if not valid:
        headers = (
            {"WWW-Authenticate": "Basic"}
            if credentials or not get_passkey_config().get("passkeys")
            else {}
        )
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers=headers,
        )


def check_admin_request_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="拒绝跨站管理请求")


def uses_default_admin_password() -> bool:
    return get_admin_password_hash() is None and os.getenv(
        "ANYCAST_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD
    ) in ("", _DEFAULT_ADMIN_PASSWORD)
