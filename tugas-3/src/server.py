"""
HTTP/REST API server exposing the distributed sync system.
Each container runs one server on its NODE_PORT, hosting all 3 components
(lock manager, queue, cache). Inter-node messaging uses the in-process
MessageBus when running as a single process for testing, and HTTP forwarding
when running as separate Docker containers (orchestrated via docker-compose).
"""

import asyncio
import logging
import os
import time
from typing import Any, Dict

from aiohttp import web

from src.communication.message_passing import global_bus
from src.nodes.cache_node import CacheNode
from src.nodes.lock_manager import LockManagerNode, LockMode
from src.nodes.queue_node import QueueNode
from src.utils.config import config
from src.utils.metrics import registry

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


class DistSyncServer:
    def __init__(self):
        self.node_id = config.node.node_id
        self.peers = config.node.peers
        self.lock_manager = LockManagerNode(
            self.node_id, self.peers, bus=global_bus
        )
        self.queue = QueueNode(
            self.node_id,
            self.peers,
            bus=global_bus,
            virtual_nodes=config.queue.virtual_nodes,
            replication_factor=config.queue.replication_factor,
            persistence_dir=config.queue.persistence_path,
        )
        self.cache = CacheNode(
            self.node_id,
            self.peers,
            bus=global_bus,
            max_size=config.cache.max_size,
            eviction_policy=config.cache.eviction_policy,
        )
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/health", self.health)
        self.app.router.add_get("/metrics", self.metrics)
        self.app.router.add_get("/state", self.state)

        # Lock endpoints
        self.app.router.add_post("/locks/acquire", self.lock_acquire)
        self.app.router.add_post("/locks/release", self.lock_release)
        self.app.router.add_get("/locks", self.lock_list)

        # Queue endpoints
        self.app.router.add_post("/queues/{queue}/messages", self.queue_enqueue)
        self.app.router.add_get("/queues/{queue}/messages", self.queue_dequeue)
        self.app.router.add_post("/queues/messages/{msg_id}/ack", self.queue_ack)
        self.app.router.add_get("/queues/stats", self.queue_stats)

        # Cache endpoints
        self.app.router.add_get("/cache/{key}", self.cache_get)
        self.app.router.add_put("/cache/{key}", self.cache_put)
        self.app.router.add_delete("/cache/{key}", self.cache_delete)
        self.app.router.add_get("/cache/stats/all", self.cache_stats)

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "status": "ok",
                "node_id": self.node_id,
                "peers": self.peers,
                "raft": self.lock_manager.raft.get_state_info(),
                "timestamp": time.time(),
            }
        )

    async def metrics(self, request: web.Request) -> web.Response:
        return web.json_response(registry.snapshot())

    async def state(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "node_id": self.node_id,
                "raft": self.lock_manager.raft.get_state_info(),
                "queue": self.queue.get_stats(),
                "cache": self.cache.get_stats(),
                "locks": self.lock_manager.get_lock_table(),
            }
        )

    # --- Lock endpoints ---
    async def lock_acquire(self, request: web.Request) -> web.Response:
        data = await request.json()
        client_id = data["client_id"]
        resource = data["resource"]
        mode = LockMode(data.get("mode", "exclusive"))
        timeout = float(data.get("timeout", 10.0))
        granted = await self.lock_manager.acquire(
            client_id, resource, mode, timeout=timeout
        )
        return web.json_response(
            {
                "granted": granted,
                "leader": self.lock_manager.raft.leader_id,
                "is_leader": self.lock_manager.is_leader,
            }
        )

    async def lock_release(self, request: web.Request) -> web.Response:
        data = await request.json()
        released = await self.lock_manager.release(
            data["client_id"], data["resource"]
        )
        return web.json_response({"released": released})

    async def lock_list(self, request: web.Request) -> web.Response:
        return web.json_response(self.lock_manager.get_lock_table())

    # --- Queue endpoints ---
    async def queue_enqueue(self, request: web.Request) -> web.Response:
        queue = request.match_info["queue"]
        data = await request.json()
        msg_id = await self.queue.enqueue(
            queue, data.get("payload"), data.get("partition_key")
        )
        return web.json_response({"msg_id": msg_id})

    async def queue_dequeue(self, request: web.Request) -> web.Response:
        queue = request.match_info["queue"]
        msg = await self.queue.dequeue(queue)
        if not msg:
            return web.json_response({"message": None})
        return web.json_response(
            {
                "message": {
                    "msg_id": msg.msg_id,
                    "payload": msg.payload,
                    "delivery_count": msg.delivery_count,
                    "timestamp": msg.timestamp,
                }
            }
        )

    async def queue_ack(self, request: web.Request) -> web.Response:
        msg_id = request.match_info["msg_id"]
        ok = await self.queue.ack(msg_id)
        return web.json_response({"acked": ok})

    async def queue_stats(self, request: web.Request) -> web.Response:
        return web.json_response(self.queue.get_stats())

    # --- Cache endpoints ---
    async def cache_get(self, request: web.Request) -> web.Response:
        key = request.match_info["key"]
        value = await self.cache.get(key)
        return web.json_response({"key": key, "value": value, "found": value is not None})

    async def cache_put(self, request: web.Request) -> web.Response:
        key = request.match_info["key"]
        data = await request.json()
        ok = await self.cache.put(key, data.get("value"))
        return web.json_response({"ok": ok})

    async def cache_delete(self, request: web.Request) -> web.Response:
        key = request.match_info["key"]
        ok = await self.cache.delete(key)
        return web.json_response({"deleted": ok})

    async def cache_stats(self, request: web.Request) -> web.Response:
        return web.json_response(self.cache.get_stats())

    async def start_nodes(self):
        await self.lock_manager.start()
        await self.queue.start()
        await self.cache.start()
        logger.info(
            f"All node components started for {self.node_id} "
            f"on port {config.node.port}"
        )

    async def stop_nodes(self):
        await self.lock_manager.stop()
        await self.queue.stop()
        await self.cache.stop()


async def init_app() -> web.Application:
    server = DistSyncServer()
    await server.start_nodes()
    server.app["server"] = server

    async def cleanup(app):
        await server.stop_nodes()

    server.app.on_cleanup.append(cleanup)
    return server.app


def main():
    logging.basicConfig(level=config.log_level)
    web.run_app(
        init_app(),
        host=config.node.host,
        port=config.node.port,
    )


if __name__ == "__main__":
    main()
