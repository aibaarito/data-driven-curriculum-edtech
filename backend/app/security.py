"""Access control and request-size enforcement (pure ASGI middlewares, so they also cover streaming bodies).

Access model (single-school MVP, no user accounts):
* API_TOKEN configured  -> all /api routes except /api/health require "Authorization: Bearer <API_TOKEN>".
  The Next.js server adds this header when it proxies browser requests; the token never reaches the browser.
* API_TOKEN not set     -> restricted local-demo mode: only loopback clients are served (403 otherwise).
Destructive operations additionally require ENABLE_DATA_RESET=true and "X-Admin-Token" (see routes.reset_data).
"""
from __future__ import annotations

import hmac
import json
from typing import Any

from app.config import get_settings

LOOPBACK = {"127.0.0.1", "::1", "localhost"}
OPEN_PATHS = {"/api/health"}


async def _send_json(send: Any, status: int, detail: str) -> None:
    body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


def token_matches(provided: str | None, expected: str) -> bool:
    return bool(provided) and bool(expected) and hmac.compare_digest(provided.encode(), expected.encode())


class AccessControlMiddleware:
    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith("/api") or scope["path"] in OPEN_PATHS \
                or scope["method"] == "OPTIONS":
            await self.app(scope, receive, send)
            return
        settings = get_settings()
        if settings.api_token:
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode("latin-1")
            token = auth[7:] if auth.lower().startswith("bearer ") else None
            if not token_matches(token, settings.api_token):
                await _send_json(send, 401, "Требуется авторизация.")
                return
        else:
            client = (scope.get("client") or ("", 0))[0]
            if client not in LOOPBACK:
                await _send_json(send, 403, "Доступ разрешён только с этого компьютера (локальный демо-режим). "
                                            "Для сетевого доступа настройте API_TOKEN.")
                return
        await self.app(scope, receive, send)


class _BodyTooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Rejects request bodies above the limit while they are being received (Content-Length is not trusted)."""

    def __init__(self, app: Any, path_prefix: tuple[str, ...] | str = ("/api/imports/",),
                 overhead_bytes: int = 256 * 1024):
        self.app = app
        self.path_prefix = path_prefix if isinstance(path_prefix, tuple) else (path_prefix,)
        self.overhead = overhead_bytes  # multipart boundaries and headers

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(self.path_prefix):
            await self.app(scope, receive, send)
            return
        limit = get_settings().max_upload_bytes + self.overhead
        mb = get_settings().max_upload_mb
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _send_json(send, 413, f"Файл больше {mb:g} МБ.")
            return
        received = 0
        too_large = False
        started = False

        async def limited_receive() -> dict:
            nonlocal received, too_large
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    too_large = True
                    raise _BodyTooLarge()
            return message

        async def guarded_send(message: dict) -> None:
            nonlocal started
            if too_large:
                # The framework may convert the aborted body read into a generic error; answer 413 instead.
                if message["type"] == "http.response.start" and not started:
                    started = True
                    await _send_json(send, 413, f"Файл больше {mb:g} МБ.")
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, guarded_send)
        except _BodyTooLarge:
            if not started:
                await _send_json(send, 413, f"Файл больше {mb:g} МБ.")
