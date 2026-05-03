from src.nodes.lock_manager import DeadlockDetector


def test_no_cycle():
    d = DeadlockDetector()
    d.add_wait("A", "B")
    d.add_wait("B", "C")
    assert d.detect_cycle() is None


def test_simple_cycle():
    d = DeadlockDetector()
    d.add_wait("A", "B")
    d.add_wait("B", "A")
    cycle = d.detect_cycle()
    assert cycle is not None
    assert "A" in cycle and "B" in cycle


def test_three_node_cycle():
    d = DeadlockDetector()
    d.add_wait("A", "B")
    d.add_wait("B", "C")
    d.add_wait("C", "A")
    cycle = d.detect_cycle()
    assert cycle is not None
    assert set(cycle) >= {"A", "B", "C"}


def test_victim_selection_picks_youngest():
    d = DeadlockDetector()
    d.set_client_age("A", 100.0)
    d.set_client_age("B", 200.0)
    d.set_client_age("C", 150.0)
    victim = d.select_victim(["A", "B", "C"])
    assert victim == "B"
