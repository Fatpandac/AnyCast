# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import secrets
from typing import Annotated, Literal
from urllib.parse import urlparse

from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field, field_validator

from src.config import DEFAULT_PAGE_SIZE, Podcast


_security = HTTPBasic(auto_error=False)
_DEFAULT_ADMIN_PASSWORD = "adminadmin"


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


def require_admin(
    credentials: Annotated[HTTPBasicCredentials | None, Depends(_security)],
) -> None:
    expected_password = os.getenv("ANYCAST_ADMIN_PASSWORD", _DEFAULT_ADMIN_PASSWORD)
    expected_username = os.getenv("ANYCAST_ADMIN_USERNAME", "admin")
    username = credentials.username if credentials else ""
    password = credentials.password if credentials else ""
    valid = secrets.compare_digest(username.encode(), expected_username.encode())
    valid &= secrets.compare_digest(password.encode(), expected_password.encode())
    if not valid:
        raise HTTPException(
            status_code=401,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Basic"},
        )


def check_admin_request_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.url.netloc:
        raise HTTPException(status_code=403, detail="拒绝跨站管理请求")


def uses_default_admin_password() -> bool:
    return "ANYCAST_ADMIN_PASSWORD" not in os.environ
