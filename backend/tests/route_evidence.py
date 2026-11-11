"""Optional pytest plugin: record API route templates/statuses, without bodies or credentials.

Usage: python -m pytest -p tests.route_evidence
"""
import json
import os
from pathlib import Path

import pytest
from fastapi.routing import APIRoute


@pytest.fixture(scope="session", autouse=True)
def route_evidence():
    from app.main import app
    from app.api.routes import router

    seen: dict[tuple[str, str], set[int]] = {}
    routes = [r for r in router.routes if isinstance(r, APIRoute)]

    class ObserveRoutes:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            async def observe_send(message):
                if message["type"] == "http.response.start":
                    for route in routes:
                        if scope["method"] in route.methods and route.path_regex.fullmatch(scope["path"]):
                            seen.setdefault((scope["method"], route.path), set()).add(message["status"])
                            break
                await send(message)
            await self.app(scope, receive, observe_send)

    app.add_middleware(ObserveRoutes)
    yield
    expected = {(method, route.path) for route in routes
                for method in route.methods}
    result = {"expected_method_routes": len(expected), "exercised_method_routes": len(expected & set(seen)),
              "routes": [{"method": method, "path": path, "statuses": sorted(seen.get((method, path), set()))}
                         for method, path in sorted(expected)]}
    target = Path(os.environ.get("ROUTE_EVIDENCE_PATH", "../verification/route-coverage.json"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, indent=2))
