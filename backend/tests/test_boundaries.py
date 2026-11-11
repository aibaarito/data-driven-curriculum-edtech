"""Application boundaries: no original credentials, files, or identifiers are used."""
import json

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text

from app.main import app
from tests.conftest import API_TOKEN, ADMIN_TOKEN, make_csv
from tests.test_api import OK, upload


def test_all_api_routes_consistently_require_the_shared_token(client):
    paths = app.openapi()["paths"]
    with TestClient(app) as anonymous:
        checked = 0
        for path, definitions in paths.items():
            for method in definitions:
                if method not in {"get", "post", "put", "delete"}:
                    continue
                concrete = path
                for parameter in ("batch_id", "report_id", "topic_id", "run_id", "edge_id", "intervention_id"):
                    concrete = concrete.replace("{" + parameter + "}", "999999")
                response = anonymous.request(method.upper(), concrete)
                assert response.status_code == (200 if path == "/api/health" else 401)
                checked += 1
        assert checked == 45  # 28 original + 17 decision-intelligence routes
    health = client.get("/api/health")
    assert set(health.json()) == {"status", "database", "llm_enabled"}
    assert API_TOKEN not in health.text and ADMIN_TOKEN not in health.text


@pytest.mark.parametrize("filename", ["../../outside.csv", "C:\\private\\outside.csv"])
def test_uploaded_filename_is_reduced_to_basename(client, migrated_db, filename):
    preview = upload(client, make_csv([OK]), filename).json()
    assert preview["ok"] and preview["filename"] == "outside.csv"
    with migrated_db.connect() as connection:
        assert connection.execute(text("SELECT filename FROM import_batches")).scalar() == "outside.csv"


def test_provider_failure_logs_and_api_response_do_not_echo_credentials(client, monkeypatch, caplog):
    from app.config import get_settings
    from app.api import routes
    from app.services.ai import generate_insights
    import httpx
    p = upload(client, make_csv([OK.replace(",pre,", ",post,")])).json()
    assert client.post(f"/api/imports/{p['batch_id']}/commit").status_code == 200
    fake_key = "sentinel-private-credential"
    monkeypatch.setattr(get_settings(), "llm_api_key", fake_key)
    monkeypatch.setattr(get_settings(), "llm_provider", "openai_compatible")
    def failure(*args):
        raise httpx.ConnectTimeout("provider included " + fake_key)
    monkeypatch.setattr(routes, "generate_insights", lambda context, settings: generate_insights(context, settings, llm=failure))
    result = client.post("/api/ai/insights", json={})
    assert result.status_code == 200 and result.json()["mode"] == "deterministic"
    assert result.json()["attempts"] == 1
    for secret in (fake_key, API_TOKEN, ADMIN_TOKEN):
        assert secret not in result.text + caplog.text


def test_unknown_context_data_cannot_enter_outbound_aggregate_facts():
    from app.config import Settings
    from app.services.ai import generate_insights
    from tests.test_ai import CTX, GOOD_LLM
    context = {**CTX, "raw_student_rows": [{"student_id": "SENTINEL-DO-NOT-SEND"}],
               "private_credential": "SENTINEL-SECRET"}
    requests = []
    def capture(settings, system, user):
        requests.append(user)
        return json.dumps(GOOD_LLM)
    result = generate_insights(context, Settings(_env_file=None, llm_api_key="fake-key"), llm=capture)
    assert result["mode"] == "llm" and len(requests) == 1
    assert "SENTINEL" not in requests[0]
    assert all(key.split(".")[0] in {"overview", "settings", "topic", "textbook", "comparison", "plan"}
               for key in result["facts"])
