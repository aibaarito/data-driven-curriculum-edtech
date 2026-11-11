"""Deployment regressions, using only the explicit _test database when needed."""
import socket

import pytest
from fastapi.responses import Response
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from app.api.routes import health
from app.config import Settings
from app.serve import listen_socket


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_database_url_preserves_escaped_credentials_ipv6_and_query(scheme):
    tail = "user:p%40ss%25word@[fd00::1]:5432/railway?sslmode=require&application_name=demo%20app"
    st = Settings(_env_file=None, database_url=f"{scheme}://{tail}")
    assert st.database_url == f"postgresql+psycopg://{tail}"
    parsed = make_url(st.database_url)
    assert parsed.password == "p@ss%word"
    assert parsed.host == "fd00::1"
    assert parsed.query["sslmode"] == "require"


def test_database_url_survives_alembic_config_interpolation():
    from alembic.config import Config
    value = Settings(_env_file=None, database_url="postgresql://user:p%25%40@db/railway?options=a%20b").database_url
    cfg = Config()
    cfg.set_main_option("sqlalchemy.url", value.replace("%", "%%"))
    assert cfg.get_main_option("sqlalchemy.url") == value


def test_health_failure_is_not_a_successful_http_status():
    class OfflineDB:
        def execute(self, *args):
            raise OperationalError("query", {}, RuntimeError("private connection details"))
    response = Response()
    body = health(OfflineDB(), response)
    assert response.status_code == 503
    assert body["database"] is False
    assert body["status"] == "degraded"
    assert "private" not in str(body)
    assert response.headers["cache-control"] == "no-store"


def test_health_success_works_without_api_token(client):
    client.headers.clear()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["database"] is True
    assert client.get("/api/meta").status_code == 401


def test_listener_accepts_both_ip_families():
    if not socket.has_dualstack_ipv6():
        pytest.skip("host does not support dual-stack IPv6")
    with listen_socket(0) as server:
        server.settimeout(2)
        port = server.getsockname()[1]
        for host in ("127.0.0.1", "::1"):
            with socket.create_connection((host, port), timeout=2):
                conn, _ = server.accept()
                conn.close()
