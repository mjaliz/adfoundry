from __future__ import annotations

import asyncio
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from loguru import logger

from adfoundry.events import RunEvent, RunEventBus, replay_events
from adfoundry.models import CampaignBrief, RunMode
from adfoundry.settings import get_settings
from adfoundry.workflow import run_campaign


# Module-level registry of live runs: run_id -> bus.
_active_runs: dict[str, RunEventBus] = {}
_active_lock = threading.Lock()


class StartRunRequest(BaseModel):
    brief: CampaignBrief
    mode: RunMode = "hybrid"


class StartRunResponse(BaseModel):
    run_id: str


class RunSummary(BaseModel):
    run_id: str
    created_at: datetime | None = None
    mode: str | None = None
    theme: str | None = None
    status: str  # "running" | "completed" | "failed" | "unknown"
    overall_score: int | None = None


def _new_run_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]


def _output_root() -> Path:
    return Path(get_settings().output_root)


def _register(run_id: str, bus: RunEventBus) -> None:
    with _active_lock:
        _active_runs[run_id] = bus


def _unregister(run_id: str) -> None:
    with _active_lock:
        _active_runs.pop(run_id, None)


def _get_active(run_id: str) -> RunEventBus | None:
    with _active_lock:
        return _active_runs.get(run_id)


def _format_sse(event: RunEvent) -> str:
    payload = event.model_dump(mode="json")
    return (
        f"event: {event.type}\n"
        f"id: {event.seq}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


def _run_in_thread(brief: CampaignBrief, mode: RunMode, run_id: str, bus: RunEventBus) -> None:
    try:
        run_campaign(
            brief=brief,
            mode=mode,
            output_root=_output_root(),
            event_bus=bus,
            run_id=run_id,
        )
    except Exception as exc:
        logger.exception("Run {} failed: {}", run_id, exc)
    finally:
        try:
            bus.close()
        except Exception:
            pass
        _unregister(run_id)


def _list_runs() -> list[RunSummary]:
    root = _output_root()
    if not root.exists():
        return []
    runs: list[RunSummary] = []
    for child in sorted(root.iterdir(), reverse=True):
        if not child.is_dir():
            continue
        run_id = child.name
        package_path = child / "campaign_package.json"
        events_path = child / "events.jsonl"
        active = _get_active(run_id) is not None
        status = "running" if active else (
            "completed" if package_path.exists() else (
                "failed" if events_path.exists() else "unknown"
            )
        )
        created_at: datetime | None = None
        mode_used: str | None = None
        theme: str | None = None
        overall_score: int | None = None
        if package_path.exists():
            try:
                data = json.loads(package_path.read_text(encoding="utf-8"))
                created_at = datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
                mode_used = data.get("mode_used")
                theme = data.get("brief", {}).get("theme")
                overall_score = data.get("qa_report", {}).get("overall_score")
            except Exception:
                pass
        if created_at is None:
            try:
                created_at = datetime.fromtimestamp(child.stat().st_mtime, tz=UTC)
            except Exception:
                created_at = None
        runs.append(
            RunSummary(
                run_id=run_id,
                created_at=created_at,
                mode=mode_used,
                theme=theme,
                status=status,
                overall_score=overall_score,
            )
        )
    return runs


app = FastAPI(title="AdFoundry Live")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/runs", response_model=StartRunResponse)
def start_run(request: StartRunRequest) -> StartRunResponse:
    run_id = _new_run_id()
    output_dir = _output_root() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    bus = RunEventBus(run_id, output_dir)
    _register(run_id, bus)
    thread = threading.Thread(
        target=_run_in_thread,
        args=(request.brief, request.mode, run_id, bus),
        daemon=True,
        name=f"run-{run_id}",
    )
    thread.start()
    return StartRunResponse(run_id=run_id)


@app.get("/api/runs", response_model=list[RunSummary])
def list_runs() -> list[RunSummary]:
    return _list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    package_path = _output_root() / run_id / "campaign_package.json"
    if package_path.exists():
        return json.loads(package_path.read_text(encoding="utf-8"))
    if _get_active(run_id) is not None:
        return {"run_id": run_id, "status": "running"}
    raise HTTPException(status_code=404, detail="run not found")


@app.get("/api/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    bus = _get_active(run_id)
    output_root = _output_root()

    if bus is None and not (output_root / run_id / "events.jsonl").exists():
        raise HTTPException(status_code=404, detail="run not found")

    async def event_iterator() -> AsyncIterator[str]:
        if bus is not None:
            sub = bus.subscribe()
            while True:
                event = await asyncio.to_thread(next, sub, None)
                if event is None:
                    break
                yield _format_sse(event)
        else:
            for event in replay_events(run_id, output_root):
                yield _format_sse(event)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(
        event_iterator(), media_type="text/event-stream", headers=headers
    )


_SAFE_ARTIFACT_SUFFIXES = {".png", ".jpg", ".jpeg", ".html", ".json"}


@app.get("/api/runs/{run_id}/files/{filename}")
def get_artifact(run_id: str, filename: str) -> FileResponse:
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="invalid filename")
    suffix = Path(filename).suffix.lower()
    if suffix not in _SAFE_ARTIFACT_SUFFIXES:
        raise HTTPException(status_code=400, detail="unsupported file type")
    path = (_output_root() / run_id / filename).resolve()
    root = _output_root().resolve()
    if not str(path).startswith(str(root)):
        raise HTTPException(status_code=400, detail="path traversal blocked")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    media = (
        "text/html"
        if suffix == ".html"
        else "application/json"
        if suffix == ".json"
        else None
    )
    return FileResponse(path, media_type=media)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
