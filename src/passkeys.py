# -*- coding: utf-8 -*-
"""Single-admin WebAuthn challenges and signed, short-lived login cookies."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, options_to_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from src.config import (
    add_passkey,
    get_admin_password_hash,
    get_passkey_config,
    update_passkey_counter,
)

COOKIE = "anycast_session"
# shortcut: challenges live in one worker; use shared storage for multi-worker deployments.
_challenges: dict[str, tuple[float, str, str]] = {}
_lock = threading.Lock()


def _domain(request: Request, *, require_origin: bool = True) -> str:
    origin = get_passkey_config().get("passkey_origin") or ""
    if not origin:
        raise HTTPException(400, "请先配置 HTTPS 域名")
    # Do not trust X-Forwarded-* headers: the proxy must preserve Host.
    if request.headers.get("host") != urlsplit(origin).netloc or (
        require_origin and request.headers.get("origin") != origin
    ):
        raise HTTPException(403, "请通过配置的 HTTPS 域名访问")
    return origin


def _new_challenge(kind: str, origin: str, challenge: bytes) -> None:
    key = bytes_to_base64url(challenge)
    with _lock:
        now = time.time()
        for old, (expires, _, _) in list(_challenges.items()):
            if expires < now:
                del _challenges[old]
        if len(_challenges) >= 128:
            raise HTTPException(429, "尝试过于频繁，请稍后再试")
        _challenges[key] = (now + 120, kind, origin)


def _use_challenge(value: str, kind: str, origin: str) -> bytes:
    with _lock:
        entry = _challenges.pop(value, None)
    if not entry or entry[0] < time.time() or entry[1:] != (kind, origin):
        raise HTTPException(400, "验证已过期，请重新开始")
    try:
        return base64url_to_bytes(value)
    except ValueError as exc:
        raise HTTPException(400, "无效验证") from exc


def registration_options(request: Request) -> dict:
    origin = _domain(request)
    options = generate_registration_options(
        rp_id=urlsplit(origin).hostname or "",
        rp_name="AnyCast",
        user_name="admin",
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _new_challenge("register", origin, options.challenge)
    return json.loads(options_to_json(options))


def register(request: Request, challenge: str, credential: dict) -> None:
    origin = _domain(request)
    challenge_bytes = _use_challenge(challenge, "register", origin)
    try:
        result = verify_registration_response(
            credential=credential,
            expected_challenge=challenge_bytes,
            expected_rp_id=urlsplit(origin).hostname or "",
            expected_origin=origin,
            require_user_verification=True,
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Passkey 验证失败") from exc
    try:
        add_passkey(
            origin,
            {
                "id": bytes_to_base64url(result.credential_id),
                "public_key": bytes_to_base64url(result.credential_public_key),
                "sign_count": result.sign_count,
            },
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def authentication_options(request: Request) -> dict:
    origin = _domain(request)
    if not get_passkey_config().get("passkeys"):
        raise HTTPException(404, "尚未注册 Passkey")
    options = generate_authentication_options(
        rp_id=urlsplit(origin).hostname or "",
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _new_challenge("login", origin, options.challenge)
    return json.loads(options_to_json(options))


def authenticate(request: Request, challenge: str, credential: dict) -> str:
    origin = _domain(request)
    challenge_bytes = _use_challenge(challenge, "login", origin)
    config = get_passkey_config()
    key = next(
        (
            item
            for item in config.get("passkeys") or []
            if item["id"] == credential.get("id")
        ),
        None,
    )
    if not key:
        raise HTTPException(400, "未知 Passkey")
    try:
        result = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge_bytes,
            expected_rp_id=urlsplit(origin).hostname or "",
            expected_origin=origin,
            credential_public_key=base64url_to_bytes(key["public_key"]),
            credential_current_sign_count=key["sign_count"],
            require_user_verification=True,
        )
        if result.credential_id != base64url_to_bytes(key["id"]):
            raise ValueError("credential mismatch")
        update_passkey_counter(
            origin, key["id"], key["sign_count"], result.new_sign_count
        )
    except (WebAuthnException, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(400, "Passkey 验证失败") from exc
    return make_session(origin)


def _secret(config: dict) -> bytes:
    return (
        bytes.fromhex(config["passkey_secret"])
        + (
            get_admin_password_hash()
            or os.getenv("ANYCAST_ADMIN_PASSWORD", "adminadmin")
        ).encode()
    )


def make_session(origin: str) -> str:
    config = get_passkey_config()
    message = f"{origin}|{int(time.time()) + 12 * 3600}|{secrets.token_hex(16)}"
    signature = hmac.new(_secret(config), message.encode(), hashlib.sha256).hexdigest()
    return f"{message}|{signature}"


def session_valid(request: Request) -> bool:
    config = get_passkey_config()
    if not config.get("passkeys") or not config.get("passkey_secret"):
        return False
    try:
        origin = _domain(request, require_origin=False)
        token = request.cookies[COOKIE]
        token_origin, expires, nonce, signature = token.split("|")
        message = f"{token_origin}|{expires}|{nonce}"
        return (
            token_origin == origin
            and int(expires) > time.time()
            and hmac.compare_digest(
                signature,
                hmac.new(_secret(config), message.encode(), hashlib.sha256).hexdigest(),
            )
        )
    except (KeyError, ValueError, HTTPException):
        return False
