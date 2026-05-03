import time
import asyncio
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MetricSnapshot:
    timestamp: float
    value: float


class Counter:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def inc(self, amount: float = 1.0):
        self._value += amount

    @property
    def value(self) -> float:
        return self._value

    def reset(self):
        self._value = 0.0


class Gauge:
    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value: float = 0.0

    def set(self, value: float):
        self._value = value

    def inc(self, amount: float = 1.0):
        self._value += amount

    def dec(self, amount: float = 1.0):
        self._value -= amount

    @property
    def value(self) -> float:
        return self._value


class Histogram:
    def __init__(self, name: str, description: str = "", buckets: int = 100):
        self.name = name
        self.description = description
        self._samples: deque = deque(maxlen=buckets)
        self._sum: float = 0.0
        self._count: int = 0

    def observe(self, value: float):
        self._samples.append(value)
        self._sum += value
        self._count += 1

    @property
    def mean(self) -> float:
        if self._count == 0:
            return 0.0
        return self._sum / self._count

    @property
    def p99(self) -> float:
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * 0.99)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def p95(self) -> float:
        if not self._samples:
            return 0.0
        sorted_samples = sorted(self._samples)
        idx = int(len(sorted_samples) * 0.95)
        return sorted_samples[min(idx, len(sorted_samples) - 1)]

    @property
    def count(self) -> int:
        return self._count


class MetricsRegistry:
    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def counter(self, name: str, description: str = "") -> Counter:
        if name not in self._counters:
            self._counters[name] = Counter(name, description)
        return self._counters[name]

    def gauge(self, name: str, description: str = "") -> Gauge:
        if name not in self._gauges:
            self._gauges[name] = Gauge(name, description)
        return self._gauges[name]

    def histogram(self, name: str, description: str = "") -> Histogram:
        if name not in self._histograms:
            self._histograms[name] = Histogram(name, description)
        return self._histograms[name]

    def snapshot(self) -> dict:
        snap = {
            "timestamp": time.time(),
            "counters": {k: v.value for k, v in self._counters.items()},
            "gauges": {k: v.value for k, v in self._gauges.items()},
            "histograms": {
                k: {
                    "mean": v.mean,
                    "p95": v.p95,
                    "p99": v.p99,
                    "count": v.count,
                }
                for k, v in self._histograms.items()
            },
        }
        return snap

    def record_history(self):
        ts = time.time()
        for name, counter in self._counters.items():
            self._history[name].append(MetricSnapshot(ts, counter.value))
        for name, gauge in self._gauges.items():
            self._history[name].append(MetricSnapshot(ts, gauge.value))

    def get_history(self, name: str) -> List[MetricSnapshot]:
        return list(self._history.get(name, []))

    async def start_collection(self, interval: float = 5.0):
        while True:
            self.record_history()
            await asyncio.sleep(interval)


registry = MetricsRegistry()
