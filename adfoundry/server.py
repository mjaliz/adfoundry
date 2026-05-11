from __future__ import annotations

import asyncio
import io
import json
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from loguru import logger

from adfoundry.events import RunEvent, RunEventBus, replay_events
from adfoundry.models import CampaignBrief, RunMode
from adfoundry.settings import Settings, get_settings
from adfoundry.workflow import run_campaign


Provider = Literal["openai", "avalai"]

_PROVIDER_BASE_URLS: dict[Provider, str | None] = {
    "openai": None,
    "avalai": "https://api.avalai.ir/v1",
}


def _resolve_runtime_settings(
    provider: Provider | None, api_key: str | None
) -> Settings | None:
    """Build a Settings override for a single run.

    Returns None when no credentials were supplied, signalling that the
    default env-based settings should be used (CLI / dev fallback path).
    """
    if not provider and not api_key:
        return None
    base = get_settings()
    update: dict[str, Any] = {}
    if api_key:
        update["openai_api_key"] = api_key
    if provider:
        update["openai_base_url"] = _PROVIDER_BASE_URLS.get(provider)
    return base.model_copy(update=update)


# Module-level registry of live runs: run_id -> bus.
_active_runs: dict[str, RunEventBus] = {}
_active_lock = threading.Lock()


class StartRunRequest(BaseModel):
    brief: CampaignBrief
    mode: RunMode = "hybrid"
    provider: Provider | None = None
    api_key: str | None = None


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


def _run_in_thread(
    brief: CampaignBrief,
    mode: RunMode,
    run_id: str,
    bus: RunEventBus,
    settings: Settings | None,
) -> None:
    try:
        run_campaign(
            brief=brief,
            mode=mode,
            output_root=_output_root(),
            event_bus=bus,
            run_id=run_id,
            settings=settings,
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
    runtime_settings = _resolve_runtime_settings(request.provider, request.api_key)
    thread = threading.Thread(
        target=_run_in_thread,
        args=(request.brief, request.mode, run_id, bus, runtime_settings),
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


def _validate_run_id(run_id: str) -> None:
    if "/" in run_id or "\\" in run_id or ".." in run_id:
        raise HTTPException(status_code=400, detail="invalid run id")


def _resolve_inside(run_dir: Path, candidate: str | None) -> Path | None:
    """Resolve `candidate` against `run_dir`, returning the path only if it
    lives inside `run_dir`. Accepts both relative basenames (e.g. ``index.html``)
    and absolute paths (e.g. ``output/<id>/index.html`` as stored in the JSON).
    Returns None for falsy inputs or paths that escape the run dir."""
    if not candidate:
        return None
    raw = Path(candidate)
    path = raw if raw.is_absolute() else run_dir / raw.name
    resolved = path.resolve()
    root = run_dir.resolve()
    if not str(resolved).startswith(str(root)):
        return None
    if not resolved.exists() or not resolved.is_file():
        return None
    return resolved


def _zip_member(
    zf: zipfile.ZipFile, run_dir: Path, source: str | None, archive_name: str
) -> None:
    path = _resolve_inside(run_dir, source)
    if path is None:
        logger.debug("Skipping zip member %s — source %r missing", archive_name, source)
        return
    zf.write(path, arcname=archive_name)


@app.get("/api/runs/{run_id}/package.zip")
def get_package_zip(run_id: str) -> Response:
    _validate_run_id(run_id)
    run_dir = (_output_root() / run_id).resolve()
    root = _output_root().resolve()
    if not str(run_dir).startswith(str(root)):
        raise HTTPException(status_code=400, detail="path traversal blocked")
    package_path = run_dir / "campaign_package.json"
    if not package_path.exists():
        raise HTTPException(status_code=404, detail="package not ready")

    try:
        package = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"invalid package.json: {exc}")

    image_asset = package.get("campaign_image_asset") or {}
    hero_source = image_asset.get("hero_image_path") or image_asset.get(
        "generated_image_path"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(package_path, arcname="campaign_package.json")
        _zip_member(zf, run_dir, package.get("preview_html_path"), "index.html")
        _zip_member(
            zf, run_dir, package.get("desktop_screenshot"), "campaign_desktop.png"
        )
        _zip_member(
            zf, run_dir, package.get("mobile_screenshot"), "campaign_mobile.png"
        )
        _zip_member(zf, run_dir, hero_source, "hero.png")

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{run_id}.zip"',
        },
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
