"""
Generate plots from benchmark JSON output.

Usage:
    python benchmarks/plot_results.py benchmarks/results/bench-*.json
"""

import glob
import json
import os
import sys

try:
    import matplotlib.pyplot as plt
except ImportError:
    print("matplotlib not installed; install with: pip install matplotlib")
    sys.exit(1)


def main():
    pattern = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/results/bench-*.json"
    files = sorted(glob.glob(pattern))
    if not files:
        print(f"No benchmark files match: {pattern}")
        return

    out_dir = "benchmarks/results"
    os.makedirs(out_dir, exist_ok=True)

    cache_writes, cache_reads, queue_enq, lock_aps = [], [], [], []
    labels = []
    for f in files:
        with open(f) as fh:
            d = json.load(fh)
        labels.append(os.path.basename(f).replace(".json", ""))
        cache_writes.append(d.get("cache", {}).get("write_ops_per_sec", 0))
        cache_reads.append(d.get("cache", {}).get("read_ops_per_sec", 0))
        queue_enq.append(d.get("queue", {}).get("enqueue_ops_per_sec", 0))
        lock_aps.append(d.get("lock", {}).get("acquire_ops_per_sec", 0))

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes[0, 0].bar(labels, cache_reads); axes[0, 0].set_title("Cache reads ops/s")
    axes[0, 1].bar(labels, cache_writes); axes[0, 1].set_title("Cache writes ops/s")
    axes[1, 0].bar(labels, queue_enq); axes[1, 0].set_title("Queue enqueue ops/s")
    axes[1, 1].bar(labels, lock_aps); axes[1, 1].set_title("Lock acquire ops/s")
    for ax in axes.flat:
        ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    out = os.path.join(out_dir, "throughput_comparison.png")
    fig.savefig(out, dpi=120)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
