from src.nodes.queue_node import ConsistentHashRing


def test_basic_distribution():
    ring = ConsistentHashRing(virtual_nodes=100)
    for n in ["a", "b", "c"]:
        ring.add_node(n)

    counts = {"a": 0, "b": 0, "c": 0}
    for i in range(3000):
        node = ring.get_node(f"key-{i}")
        counts[node] += 1

    # Roughly balanced (within 30% of fair share)
    fair = 1000
    for n, c in counts.items():
        assert 0.7 * fair < c < 1.3 * fair, f"node {n} got {c}"


def test_remove_node_redistributes():
    ring = ConsistentHashRing(virtual_nodes=50)
    for n in ["a", "b", "c"]:
        ring.add_node(n)

    before = {f"key-{i}": ring.get_node(f"key-{i}") for i in range(500)}
    ring.remove_node("b")
    after = {f"key-{i}": ring.get_node(f"key-{i}") for i in range(500)}

    moved = sum(1 for k in before if before[k] != after[k])
    # Only keys previously assigned to "b" should move
    expected_max = sum(1 for v in before.values() if v == "b")
    assert moved <= expected_max + 5  # tolerate small variance


def test_replicas_are_distinct_physical_nodes():
    ring = ConsistentHashRing(virtual_nodes=100)
    for n in ["a", "b", "c", "d"]:
        ring.add_node(n)

    for i in range(100):
        replicas = ring.get_n_nodes(f"key-{i}", 3)
        assert len(replicas) == 3
        assert len(set(replicas)) == 3
