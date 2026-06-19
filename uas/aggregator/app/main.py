"""Aggregator API (FastAPI).

Alur: publisher -> /publish -> broker (Redis Streams) -> consumer workers -> DB.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Union

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .broker import broker
from .consumer import worker_loop
from .db import db
from .schemas import Event, PublishResponse, StatsResponse

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("aggregator")

NUM_WORKERS = int(os.getenv("WORKERS", "4"))

START_TIME = time.time()
_workers: List[asyncio.Task] = []
_stop = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("startup: konek storage & broker ...")
    await db.connect()
    await broker.connect()
    _stop.clear()
    for i in range(NUM_WORKERS):
        _workers.append(asyncio.create_task(worker_loop(f"worker-{i}", db, broker, _stop)))
    log.info("startup selesai: %d worker aktif", NUM_WORKERS)
    try:
        yield
    finally:
        log.info("shutdown: hentikan worker ...")
        _stop.set()
        for w in _workers:
            w.cancel()
        await asyncio.gather(*_workers, return_exceptions=True)
        await broker.close()
        await db.close()


app = FastAPI(title="Pub-Sub Log Aggregator", version="1.0.0", lifespan=lifespan)

def _parse_events(body: Union[dict, list]) -> List[Event]:
    """Memvalidasi skema secara all-or-nothing: bila ada satu item invalid,
    menolak seluruh request (422)."""
    raw = body if isinstance(body, list) else [body]
    if not raw:
        raise HTTPException(status_code=422, detail="body kosong")
    try:
        return [Event(**item) for item in raw]
    except (ValidationError, TypeError) as e:
        raise HTTPException(status_code=422, detail=f"event invalid: {e}")


@app.post("/publish", response_model=PublishResponse)
async def publish(request: Request):
    # Membaca body mentah agar bisa menerima single (object) maupun batch (array)
    # tanpa ambiguitas binding FastAPI pada Union[dict, list].
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="body bukan JSON valid")
    events = _parse_events(body)
    await db.incr_received(len(events))
    for ev in events:
        await broker.publish(ev.model_dump(mode="json"))
    log.info("publish: %d event diterima -> broker", len(events))
    return PublishResponse(accepted=len(events), rejected=0, detail="enqueued")

@app.get("/events")
async def get_events(
    topic: str = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=100000),
):
    return await db.get_events(topic=topic, limit=limit)

@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    stats = await db.get_stats()
    return StatsResponse(
        received=stats.get("received", 0),
        unique_processed=stats.get("unique_processed", 0),
        duplicate_dropped=stats.get("duplicate_dropped", 0),
        topics=stats.get("topics", 0),
        uptime_seconds=round(time.time() - START_TIME, 2),
        queue_depth=await broker.pending_count(),
    )

@app.get("/healthz")
async def healthz():
    return {"status": "alive"}

@app.get("/readyz")
async def readyz():
    try:
        ok_db = db.pool is not None
        ok_broker = await broker.ping()
        if ok_db and ok_broker:
            return {"status": "ready"}
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "not-ready", "detail": str(e)})
    return JSONResponse(status_code=503, content={"status": "not-ready"})
