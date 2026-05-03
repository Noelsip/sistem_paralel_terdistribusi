from src.nodes.cache_node import LRUPolicy, LFUPolicy


def test_lru_basic():
    p = LRUPolicy()
    for k in ["a", "b", "c"]:
        p.insert(k)
    p.access("a")
    assert p.evict() == "b"
    assert p.evict() == "c"
    assert p.evict() == "a"
    assert p.evict() is None


def test_lfu_basic():
    p = LFUPolicy()
    for k in ["a", "b", "c"]:
        p.insert(k)
    p.access("a")
    p.access("a")
    p.access("c")
    # b has count 1 (lowest)
    assert p.evict() == "b"
