import json
import os
import signal

import psycopg
import redis
from prometheus_client import Counter, start_http_server

DATABASE_URL = os.environ["DATABASE_URL"]
REDIS_URL = os.environ["REDIS_URL"]

PROCESSED = Counter("jobs_processed_total", "Jobs processed by the worker", ["result"])
running = True


def stop(*_):
    global running
    running = False


def handle(job: dict) -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        row = conn.execute("SELECT body FROM notes WHERE id = %s", (job["note_id"],)).fetchone()
        if row is None:
            return
        conn.execute(
            "UPDATE notes SET word_count = %s WHERE id = %s",
            (len(row[0].split()), job["note_id"]),
        )


def main() -> None:
    signal.signal(signal.SIGTERM, stop)
    start_http_server(9100)
    queue = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    print("worker started, waiting for jobs", flush=True)
    while running:
        item = queue.blpop("jobs", timeout=2)
        if item is None:
            continue
        try:
            handle(json.loads(item[1]))
            PROCESSED.labels("ok").inc()
        except Exception as exc:
            PROCESSED.labels("error").inc()
            print(f"job failed: {exc}", flush=True)
    print("worker stopped", flush=True)


if __name__ == "__main__":
    main()
