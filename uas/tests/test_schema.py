"""Unit test validasi skema event (tidak butuh service)."""
import pytest

from app.schemas import Event


def test_event_valid():
    ev = Event(
        topic="app.logs",
        event_id="abc-123",
        timestamp="2026-06-17T10:00:00+00:00",
        source="svc",
        payload={"k": "v"},
    )
    assert ev.topic == "app.logs"
    assert ev.payload == {"k": "v"}


def test_event_missing_field():
    with pytest.raises(Exception):
        Event(topic="t", event_id="1", source="s")  # tanpa timestamp


def test_event_blank_topic_rejected():
    with pytest.raises(Exception):
        Event(topic="   ", event_id="1", timestamp="2026-06-17T10:00:00Z", source="s")


def test_event_invalid_timestamp_rejected():
    with pytest.raises(Exception):
        Event(topic="t", event_id="1", timestamp="bukan-tanggal", source="s")


def test_event_default_payload_empty():
    ev = Event(topic="t", event_id="1", timestamp="2026-06-17T10:00:00Z", source="s")
    assert ev.payload == {}


def test_event_serializes_to_json_isoformat():
    ev = Event(topic="t", event_id="1", timestamp="2026-06-17T10:00:00Z", source="s")
    dumped = ev.model_dump(mode="json")
    assert isinstance(dumped["timestamp"], str)
    assert dumped["topic"] == "t"
