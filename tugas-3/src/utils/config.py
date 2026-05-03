import os
from dataclasses import dataclass, field
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class NodeConfig:
    node_id: str = os.getenv("NODE_ID", "node-1")
    host: str = os.getenv("NODE_HOST", "0.0.0.0")
    port: int = int(os.getenv("NODE_PORT", "8000"))
    peers: List[str] = field(default_factory=lambda: [
        p.strip() for p in os.getenv("PEERS", "").split(",") if p.strip()
    ])


@dataclass
class RaftConfig:
    election_timeout_min: float = float(os.getenv("ELECTION_TIMEOUT_MIN", "0.15"))
    election_timeout_max: float = float(os.getenv("ELECTION_TIMEOUT_MAX", "0.30"))
    heartbeat_interval: float = float(os.getenv("HEARTBEAT_INTERVAL", "0.05"))
    rpc_timeout: float = float(os.getenv("RPC_TIMEOUT", "0.1"))


@dataclass
class QueueConfig:
    virtual_nodes: int = int(os.getenv("VIRTUAL_NODES", "150"))
    persistence_path: str = os.getenv("PERSISTENCE_PATH", "/tmp/queue_data")
    max_queue_size: int = int(os.getenv("MAX_QUEUE_SIZE", "10000"))
    replication_factor: int = int(os.getenv("REPLICATION_FACTOR", "2"))


@dataclass
class CacheConfig:
    max_size: int = int(os.getenv("CACHE_MAX_SIZE", "1000"))
    eviction_policy: str = os.getenv("CACHE_EVICTION", "LRU")
    coherence_protocol: str = os.getenv("COHERENCE_PROTOCOL", "MESI")
    ttl: int = int(os.getenv("CACHE_TTL", "300"))


@dataclass
class RedisConfig:
    enabled: bool = os.getenv("REDIS_ENABLED", "false").lower() == "true"
    host: str = os.getenv("REDIS_HOST", "localhost")
    port: int = int(os.getenv("REDIS_PORT", "6379"))
    db: int = int(os.getenv("REDIS_DB", "0"))
    password: str = os.getenv("REDIS_PASSWORD", "")


@dataclass
class MetricsConfig:
    enabled: bool = os.getenv("METRICS_ENABLED", "true").lower() == "true"
    prometheus_port: int = int(os.getenv("PROMETHEUS_PORT", "9090"))
    collection_interval: float = float(os.getenv("METRICS_INTERVAL", "5.0"))


@dataclass
class AppConfig:
    node: NodeConfig = field(default_factory=NodeConfig)
    raft: RaftConfig = field(default_factory=RaftConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


config = AppConfig()
