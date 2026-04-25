import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import ValidationError

from src.models import Event
from src.service import AggregatorService
from src.store import DedupStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)


def _parse_events(raw_body: object) -> list[Event]:
    raw_items: list[object]
    if isinstance(raw_body, dict):
        raw_items = [raw_body]
    elif isinstance(raw_body, list):
        raw_items = raw_body
    else:
        raise HTTPException(status_code=422, detail="Body harus object event atau array event")

    events: list[Event] = []
    errors: list[dict] = []
    for idx, item in enumerate(raw_items):
        try:
            events.append(Event.model_validate(item))
        except ValidationError as exc:
            errors.append({"index": idx, "errors": exc.errors()})

    if errors:
        raise HTTPException(status_code=422, detail=errors)
    return events


def create_app() -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_path = os.getenv("DEDUP_DB_PATH", "data/dedup.db")
        store = DedupStore(db_path=db_path)
        service = AggregatorService(store=store)
        await service.start()
        app.state.service = service
        app.state.store = store
        try:
            yield
        finally:
            await service.stop()
            store.close()

    app = FastAPI(
        title="UTS Pub-Sub Log Aggregator",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.post("/publish")
    async def publish(request: Request) -> dict:
        try:
            body = await request.json()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"JSON tidak valid: {exc}") from exc

        events = _parse_events(body)
        result = await app.state.service.publish(events)
        return {
            "received": len(events),
            "status": "queued",
            **result,
        }

    @app.get("/events")
    async def get_events(topic: str | None = Query(default=None)) -> dict:
        events = await app.state.service.get_events(topic=topic)
        return {"count": len(events), "events": events}

    @app.get("/stats")
    async def get_stats() -> dict:
        return await app.state.service.get_stats()

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
