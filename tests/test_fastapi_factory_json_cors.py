"""FastAPI: ``GET /?format=json`` CORS headers (3.16).

The configuration document is public, so any origin may read it and no
credentials are allowed. It used to reflect the ``Origin`` together with
``Access-Control-Allow-Credentials: true``.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from actingweb.interface import ActingWebApp


def _client() -> TestClient:
    aw_app = ActingWebApp(
        aw_type="urn:actingweb:test:fastapi-factory-cors",
        database="dynamodb",
        fqdn="test.example.com",
        proto="https://",
    ).with_web_ui(enable=True)
    app = FastAPI()
    aw_app.integrate_fastapi(app)
    return TestClient(app)


def test_format_json_allows_any_origin_without_credentials() -> None:
    response = _client().get("/?format=json", headers={"Origin": "https://a.example"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
