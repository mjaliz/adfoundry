import json
import threading
from pathlib import Path

import pytest

from adfoundry.events import RunEvent, RunEventBus, replay_events


def test_publish_assigns_monotonic_seq_and_writes_jsonl(tmp_path: Path) -> None:
    output_dir = tmp_path / "run-1"
    with RunEventBus("run-1", output_dir) as bus:
        e1 = bus.publish("run_started", {"mode": "fixture"})
        e2 = bus.publish("node_started", {"node": "research"})
        e3 = bus.publish("node_completed", {"node": "research"})

    assert (e1.seq, e2.seq, e3.seq) == (1, 2, 3)
    lines = (output_dir / "events.jsonl").read_text().splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["type"] for p in parsed] == ["run_started", "node_started", "node_completed"]
    assert parsed[0]["data"] == {"mode": "fixture"}
    assert parsed[0]["run_id"] == "run-1"


def test_subscribe_replays_past_then_lives(tmp_path: Path) -> None:
    bus = RunEventBus("run-2", tmp_path / "run-2")
    bus.publish("run_started", {})
    bus.publish("node_started", {"node": "research"})

    received: list[RunEvent] = []
    done = threading.Event()

    def consume() -> None:
        for event in bus.subscribe():
            received.append(event)
        done.set()

    thread = threading.Thread(target=consume)
    thread.start()

    # Give the subscriber a moment to drain past events.
    while len(received) < 2:
        pass

    bus.publish("node_completed", {"node": "research"})
    bus.close()
    thread.join(timeout=2)
    assert done.is_set()
    assert [e.type for e in received] == ["run_started", "node_started", "node_completed"]
    assert [e.seq for e in received] == [1, 2, 3]


def test_multiple_subscribers_each_get_full_stream(tmp_path: Path) -> None:
    bus = RunEventBus("run-3", tmp_path / "run-3")
    receivers: list[list[RunEvent]] = [[], []]
    threads: list[threading.Thread] = []

    for i in range(2):
        def consume(idx: int = i) -> None:
            for event in bus.subscribe():
                receivers[idx].append(event)

        t = threading.Thread(target=consume)
        t.start()
        threads.append(t)

    bus.publish("run_started", {})
    bus.publish("node_started", {"node": "brand"})
    bus.publish("run_completed", {})
    bus.close()
    for t in threads:
        t.join(timeout=2)

    for events in receivers:
        assert [e.type for e in events] == ["run_started", "node_started", "run_completed"]


def test_replay_events_reads_jsonl_back(tmp_path: Path) -> None:
    with RunEventBus("run-4", tmp_path / "run-4") as bus:
        bus.publish("run_started", {"mode": "live"})
        bus.publish("agent_message_started", {"role": "html_generator", "attempt": 0})
        bus.publish("agent_message_completed", {"role": "html_generator", "attempt": 0})
        bus.publish("run_completed", {})

    events = list(replay_events("run-4", tmp_path))
    assert [e.type for e in events] == [
        "run_started",
        "agent_message_started",
        "agent_message_completed",
        "run_completed",
    ]
    assert events[1].data == {"role": "html_generator", "attempt": 0}
    assert all(isinstance(e, RunEvent) for e in events)


def test_replay_returns_empty_for_missing_run(tmp_path: Path) -> None:
    assert list(replay_events("nope", tmp_path)) == []


def test_publish_after_close_raises(tmp_path: Path) -> None:
    bus = RunEventBus("run-5", tmp_path / "run-5")
    bus.publish("run_started", {})
    bus.close()
    with pytest.raises(RuntimeError):
        bus.publish("run_completed", {})
