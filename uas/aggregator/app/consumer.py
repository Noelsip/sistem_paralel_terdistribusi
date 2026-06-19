"""Consumer internal: worker yang mengkonsumsi stream dan memproses event."""
from __future__ import annotations

import asyncio
import logging

from .broker import Broker
from .db import Database

log = logging.getLogger("consumer")

async def worker_loop(
    name: str, db: Database, broker: Broker, stop: asyncio.Event
) -> None:
    """Menjalankan loop satu worker: meng-claim entry stale -> membaca entry baru -> memproses -> ACK."""
    log.info("worker %s start", name)
    idle_cycles = 0
    while not stop.is_set():
        try:
            if idle_cycles % 5 == 0:
                claimed = await broker.claim_stale(name)
                for msg_id, ev in claimed:
                    await db.process_event(ev, name)
                    await broker.ack([msg_id])
                if claimed:
                    log.info("worker %s reclaim %d entri", name, len(claimed))

            msgs = await broker.read_group(name, count=50, block_ms=2000)
            if not msgs:
                idle_cycles += 1
                continue
            idle_cycles = 0

            ack_ids = []
            for msg_id, ev in msgs:
                try:
                    is_new = await db.process_event(ev, name)
                    ack_ids.append(msg_id)
                    if not is_new:
                        log.debug(
                            "DUPLICATE drop topic=%s event_id=%s by %s",
                            ev.get("topic"), ev.get("event_id"), name,
                        )
                except Exception as e:  # noqa: BLE001
                    log.warning("worker %s gagal proses %s: %s", name, msg_id, e)
            await broker.ack(ack_ids)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001
            log.warning("worker %s error loop: %s", name, e)
            await asyncio.sleep(0.5)
    log.info("worker %s stop", name)
