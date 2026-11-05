"""URL shortener API.

A deliberately small app so the focus stays on the platform around it:
- Stores short codes in Redis, so it's stateless and can scale horizontally
- /healthz (liveness) and /readyz (readiness) for Kubernetes probes
- /metrics in Prometheus format for monitoring
"""

import os
import secrets
import string
import time

import redis
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, HttpUrl

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CODE_LENGTH = int(os.getenv("CODE_LENGTH", "7"))
ALPHABET = string.ascii_letters + string.digits

app = FastAPI(title="shortener", version=os.getenv("APP_VERSION", "dev"))

# Created lazily so tests can swap in a fake Redis.
_redis: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _redis
    if _redis is None:
        _redis = redis.Redis.from_url(REDIS_URL, decode_responses=True, socket_timeout=2)
    return _redis


def set_redis(client: redis.Redis) -> None:
    global _redis
    _redis = client


# ---- Prometheus metrics -------------------------------------------------
REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["method", "path"])
LINKS_CREATED = Counter("shortener_links_created_total", "Short links created")
REDIRECTS = Counter("shortener_redirects_total", "Redirects served")


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    # Use the route template (/{code}) not the raw path, so every short
    # code doesn't create a new metric series (high cardinality).
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    LATENCY.labels(request.method, path).observe(time.perf_counter() - start)
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


# ---- Health -------------------------------------------------------------
@app.get("/healthz")
def healthz():
    """Liveness: the process is up. Never checks dependencies, so a Redis
    outage doesn't make Kubernetes restart every pod in a loop."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: can we serve traffic? If Redis is down, Kubernetes stops
    sending requests to this pod until it recovers."""
    try:
        get_redis().ping()
    except redis.RedisError as err:
        raise HTTPException(status_code=503, detail="redis unavailable") from err
    return {"status": "ready"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ---- API ----------------------------------------------------------------
class ShortenRequest(BaseModel):
    url: HttpUrl


class ShortenResponse(BaseModel):
    code: str
    url: str


@app.post("/api/links", response_model=ShortenResponse, status_code=201)
def create_link(body: ShortenRequest):
    r = get_redis()
    for _ in range(5):
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        # SET NX only writes if the key doesn't exist, so codes never clash.
        if r.set(f"link:{code}", str(body.url), nx=True):
            LINKS_CREATED.inc()
            return ShortenResponse(code=code, url=str(body.url))
    raise HTTPException(status_code=500, detail="could not allocate code")


@app.get("/api/links/{code}", response_model=ShortenResponse)
def get_link(code: str):
    url = get_redis().get(f"link:{code}")
    if url is None:
        raise HTTPException(status_code=404, detail="not found")
    return ShortenResponse(code=code, url=url)


@app.get("/{code}")
def redirect(code: str):
    url = get_redis().get(f"link:{code}")
    if url is None:
        raise HTTPException(status_code=404, detail="not found")
    REDIRECTS.inc()
    return RedirectResponse(url, status_code=307)
