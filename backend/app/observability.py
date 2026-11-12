"""Request identity and one structured access-log line per request.

Logged: request id, method, route template (e.g. /api/interventions/{intervention_id}), status, duration, outcome
class. Never logged: query strings, bodies, headers, tokens, student identifiers or uploaded rows.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar
from typing import Any

log = logging.getLogger("ddc.access")
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]{8,64}$")


def outcome_class(status: int) -> str:
    if status < 400:
        return "ok"
    if status in (401, 403):
        return "denied"
    if status in (409, 410, 422, 413, 404, 400):
        return "client_error"
    if status == 503:
        return "unavailable"
    return "server_error"


class RequestContextMiddleware:
    """Pure ASGI middleware: assigns X-Request-ID (accepts a safe client value) and logs the request outcome."""

    def __init__(self, app: Any):
        self.app = app

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if SAFE_ID.match(incoming) else uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status_holder = {"status": 500}

        async def send_wrapper(message: dict) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [*message["headers"], (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", None) or ("/api/…" if scope.get("path", "").startswith("/api") else "other")
            status = status_holder["status"]
            log.info(json.dumps({"request_id": rid, "method": scope.get("method"), "route": path, "status": status,
                                 "duration_ms": round((time.perf_counter() - start) * 1000, 1),
                                 "outcome": outcome_class(status)}, ensure_ascii=False))
            request_id_var.reset(token)
