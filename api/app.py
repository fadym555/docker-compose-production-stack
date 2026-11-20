import json
import os
import time
from contextlib import asynccontextmanager

import psycopg
import redis
from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]

cache = redis.Redis.from_url(REDIS_URL, decode_responses=True)

REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["path"])
JOBS_QUEUED = Counter("jobs_enqueued_total", "Jobs pushed to the worker queue")


def db():
    return psycopg.connect(DATABASE_URL, autocommit=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    with db() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS notes ("
            "id SERIAL PRIMARY KEY, body TEXT NOT NULL, word_count INT, "
            "created_at TIMESTAMPTZ DEFAULT now())"
        )
    yield


app = FastAPI(title="compose-production-stack", lifespan=lifespan)


@app.middleware("http")
async def record_metrics(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = route.path if route else "unmatched"
    LATENCY.labels(path).observe(time.perf_counter() - start)
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    return response


class Note(BaseModel):
    body: str


@app.get("/healthz")
def healthz() -> dict:
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        cache.ping()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="dependency unavailable") from exc
    return {"status": "ok", "postgres": "up", "redis": "up"}


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/notes", status_code=201)
def create_note(note: Note) -> dict:
    with db() as conn:
        row = conn.execute(
            "INSERT INTO notes (body) VALUES (%s) RETURNING id", (note.body,)
        ).fetchone()
    cache.delete("notes:count")
    cache.rpush("jobs", json.dumps({"note_id": row[0]}))
    JOBS_QUEUED.inc()
    return {"id": row[0], "body": note.body}


@app.get("/notes")
def list_notes() -> list[dict]:
    with db() as conn:
        rows = conn.execute("SELECT id, body, word_count FROM notes ORDER BY id").fetchall()
    return [{"id": r[0], "body": r[1], "word_count": r[2]} for r in rows]


@app.get("/notes/count")
def count_notes() -> dict:
    cached = cache.get("notes:count")
    if cached is not None:
        return {"count": int(cached), "cached": True}
    with db() as conn:
        count = conn.execute("SELECT count(*) FROM notes").fetchone()[0]
    cache.set("notes:count", count, ex=60)
    return {"count": count, "cached": False}


@app.get("/notes/{note_id}")
def get_note(note_id: int) -> dict:
    with db() as conn:
        row = conn.execute(
            "SELECT id, body, word_count FROM notes WHERE id = %s", (note_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="note not found")
    return {"id": row[0], "body": row[1], "word_count": row[2]}
