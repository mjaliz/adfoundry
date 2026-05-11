from __future__ import annotations

import json
import queue
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

EventType = Literal[
    "run_started",
    "node_started",
    "node_completed",
    "node_progress",
    "agent_message_started",
    "agent_message_delta",
    "agent_message_completed",
    "html_render_started",
    "html_render_completed",
    "qa_report_completed",
    "dialogue_turn_completed",
    "revision_started",
    "revision_completed",
    "run_completed",
    "run_failed",
]


class RunEvent(BaseModel):
    run_id: str
    seq: int
    timestamp: datetime
    type: EventType
    data: dict[str, Any] = Field(default_factory=dict)


_CLOSE_SENTINEL: RunEvent | None = None


class RunEventBus:
    """Thread-safe pub/sub of RunEvents with append-only JSONL persistence."""

    def __init__(
        self, run_id: str, output_dir: Path, *, append: bool = False
    ) -> None:
        self.run_id = run_id
        self.output_dir = output_dir
        self._lock = threading.Lock()
        self._seq = 0
        self._events: list[RunEvent] = []
        self._subscribers: list[queue.Queue[RunEvent | None]] = []
        self._closed = False
        output_dir.mkdir(parents=True, exist_ok=True)
        self._file_path = output_dir / "events.jsonl"
        if append and self._file_path.exists():
            # Resume an existing log: seed the in-memory replay buffer with the
            # prior events so new subscribers see the full history, and
            # continue seq numbering past the last event.
            for line in self._file_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = RunEvent.model_validate_json(line)
                except Exception:
                    continue
                self._events.append(event)
                if event.seq > self._seq:
                    self._seq = event.seq
            self._file = self._file_path.open("a", encoding="utf-8")
        else:
            # Truncate so a fresh run on the same output_dir starts clean.
            self._file = self._file_path.open("w", encoding="utf-8")

    def publish(self, type: EventType, data: dict[str, Any] | None = None) -> RunEvent:
        with self._lock:
            if self._closed:
                raise RuntimeError("event bus is closed")
            self._seq += 1
            event = RunEvent(
                run_id=self.run_id,
                seq=self._seq,
                timestamp=datetime.now(UTC),
                type=type,
                data=dict(data or {}),
            )
            self._events.append(event)
            self._file.write(event.model_dump_json() + "\n")
            self._file.flush()
            for q in self._subscribers:
                q.put(event)
            return event

    def subscribe(self) -> Iterator[RunEvent]:
        """Yield all past events in order, then live events until close()."""
        q: queue.Queue[RunEvent | None] = queue.Queue()
        with self._lock:
            for event in self._events:
                q.put(event)
            if self._closed:
                q.put(_CLOSE_SENTINEL)
            else:
                self._subscribers.append(q)
        while True:
            event = q.get()
            if event is _CLOSE_SENTINEL:
                return
            yield event

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for q in self._subscribers:
                q.put(_CLOSE_SENTINEL)
            self._subscribers.clear()
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass

    def __enter__(self) -> RunEventBus:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def replay_events(run_id: str, output_root: Path | str) -> Iterator[RunEvent]:
    """Yield events for a completed/historical run from disk."""
    path = Path(output_root) / run_id / "events.jsonl"
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            yield RunEvent.model_validate_json(line)
