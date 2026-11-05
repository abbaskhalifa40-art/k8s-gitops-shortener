import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient

from shortener import main


@pytest.fixture
def client():
    main.set_redis(fakeredis.FakeRedis(decode_responses=True))
    return TestClient(main.app, follow_redirects=False)


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_ok(client):
    assert client.get("/readyz").status_code == 200


def test_readyz_fails_when_redis_down(client):
    class Broken:
        def ping(self):
            raise redis.ConnectionError("down")

    main.set_redis(Broken())
    assert client.get("/readyz").status_code == 503
    # Liveness must stay healthy, or Kubernetes would restart pods for
    # a problem that restarting can't fix.
    assert client.get("/healthz").status_code == 200


def test_create_and_redirect(client):
    res = client.post("/api/links", json={"url": "https://example.com/page"})
    assert res.status_code == 201
    code = res.json()["code"]
    assert len(code) == 7

    lookup = client.get(f"/api/links/{code}")
    assert lookup.json()["url"] == "https://example.com/page"

    redirect = client.get(f"/{code}")
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "https://example.com/page"


def test_rejects_invalid_url(client):
    assert client.post("/api/links", json={"url": "not a url"}).status_code == 422


def test_unknown_code_404(client):
    assert client.get("/nope123").status_code == 404


def test_metrics_exposed(client):
    client.get("/healthz")
    body = client.get("/metrics").text
    assert "http_requests_total" in body
    assert 'path="/healthz"' in body
