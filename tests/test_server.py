from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import adfoundry.server as server_module
from adfoundry.server import app


def _wait_for(predicate, timeout: float = 30.0, interval: float = 0.1) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def _patch_output_root(monkeypatch, tmp_path: Path) -> None:
    """Point the server at an isolated output_root for the test."""
    monkeypatch.setattr(server_module, "_output_root", lambda: tmp_path)


def test_post_run_starts_thread_and_completes(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/runs",
        json={
            "brief": {
                "url": "https://www.nike.com",
                "theme": "Christmas",
            },
            "mode": "fixture",
        },
    )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    assert run_id

    # Wait for the background thread to finish — fixture mode should be quick.
    package_path = tmp_path / run_id / "campaign_package.json"
    events_path = tmp_path / run_id / "events.jsonl"
    assert _wait_for(lambda: package_path.exists(), timeout=60.0), (
        f"package never written; events: {events_path.read_text() if events_path.exists() else '(no events)'}"
    )

    # Run is no longer in active registry once thread exits.
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=10.0)

    # Snapshot endpoint returns the package.
    snapshot = client.get(f"/api/runs/{run_id}").json()
    assert snapshot["run_id"] == run_id
    assert snapshot["qa_report"]["approved"] is True


def test_get_runs_lists_completed_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/runs",
        json={"brief": {"url": "https://www.nike.com"}, "mode": "fixture"},
    )
    run_id = response.json()["run_id"]
    package_path = tmp_path / run_id / "campaign_package.json"
    assert _wait_for(lambda: package_path.exists(), timeout=60.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=10.0)

    runs = client.get("/api/runs").json()
    assert any(r["run_id"] == run_id and r["status"] == "completed" for r in runs)


def test_sse_replays_events_for_completed_run(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)
    response = client.post(
        "/api/runs",
        json={"brief": {"url": "https://www.nike.com"}, "mode": "fixture"},
    )
    run_id = response.json()["run_id"]
    package_path = tmp_path / run_id / "campaign_package.json"
    assert _wait_for(lambda: package_path.exists(), timeout=60.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=10.0)

    with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())

    # Parse SSE frames and assert key events occur in order.
    types: list[str] = []
    for frame in body.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("event: "):
                types.append(line[len("event: ") :].strip())
    assert types[0] == "run_started"
    assert types[-1] == "run_completed"
    assert "node_completed" in types
    assert "qa_report_completed" in types
    assert "agent_message_completed" in types


def test_get_artifact_serves_html(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    run_id = "manual-1"
    (tmp_path / run_id).mkdir(parents=True)
    (tmp_path / run_id / "index.html").write_text(
        "<!doctype html><html><body>ok</body></html>", encoding="utf-8"
    )
    client = TestClient(app)
    response = client.get(f"/api/runs/{run_id}/files/index.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "ok" in response.text


def test_get_artifact_blocks_path_traversal(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)
    # `..foo.png` would slip through a naive prefix check; ensure we reject any
    # filename containing `..`.
    r1 = client.get("/api/runs/foo/files/..bad.png")
    assert r1.status_code == 400
    # Unsupported file type rejected even if filename is otherwise safe.
    r2 = client.get("/api/runs/foo/files/some.exe")
    assert r2.status_code == 400


def test_get_run_404_when_unknown(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)
    assert client.get("/api/runs/does-not-exist").status_code == 404


def _seed_package_run(run_dir: Path, *, include: set[str] | None = None) -> None:
    """Build a synthetic run directory with the assets a package zip references.

    `include` is a subset of {"index.html", "campaign_desktop", "campaign_mobile",
    "hero"}; defaults to all four. The package JSON is always written.
    """
    include = include if include is not None else {
        "index.html",
        "campaign_desktop",
        "campaign_mobile",
        "hero",
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    if "index.html" in include:
        (run_dir / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    if "campaign_desktop" in include:
        (run_dir / "campaign_desktop.png").write_bytes(b"\x89PNGdesktop")
    if "campaign_mobile" in include:
        (run_dir / "campaign_mobile.png").write_bytes(b"\x89PNGmobile")
    if "hero" in include:
        (run_dir / "hero_image.png").write_bytes(b"\x89PNGhero")

    pkg = {
        "preview_html_path": "index.html" if "index.html" in include else None,
        "desktop_screenshot": "campaign_desktop.png"
        if "campaign_desktop" in include
        else None,
        "mobile_screenshot": "campaign_mobile.png"
        if "campaign_mobile" in include
        else None,
        "campaign_image_asset": {
            "hero_image_path": "hero_image.png" if "hero" in include else None,
            "generated_image_path": None,
        },
    }
    (run_dir / "campaign_package.json").write_text(json.dumps(pkg), encoding="utf-8")


def test_get_package_zip_returns_user_facing_assets(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    run_id = "pkg-1"
    _seed_package_run(tmp_path / run_id)
    client = TestClient(app)

    resp = client.get(f"/api/runs/{run_id}/package.zip")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/zip"
    assert resp.headers["content-disposition"].startswith("attachment")
    assert f'filename="{run_id}.zip"' in resp.headers["content-disposition"]

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            "campaign_package.json",
            "index.html",
            "campaign_desktop.png",
            "campaign_mobile.png",
            "hero.png",
        }
        assert zf.read("index.html") == b"<html>ok</html>"
        assert zf.read("campaign_desktop.png") == b"\x89PNGdesktop"
        assert zf.read("campaign_mobile.png") == b"\x89PNGmobile"
        assert zf.read("hero.png") == b"\x89PNGhero"
        # The JSON in the archive is the same bytes that were on disk.
        parsed = json.loads(zf.read("campaign_package.json"))
        assert parsed["preview_html_path"] == "index.html"


def test_get_package_zip_404_when_package_missing(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    (tmp_path / "pkg-mid-run").mkdir()
    client = TestClient(app)
    resp = client.get("/api/runs/pkg-mid-run/package.zip")
    assert resp.status_code == 404


def test_get_package_zip_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)
    # Single-segment run_ids that smuggle a `..` substring must be rejected
    # before they reach the filesystem.
    assert client.get("/api/runs/..evil/package.zip").status_code == 400
    assert client.get("/api/runs/foo..bar/package.zip").status_code == 400


def test_get_package_zip_skips_missing_optional_assets(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    run_id = "pkg-partial"
    # Desktop screenshot intentionally absent (path is None in JSON).
    _seed_package_run(
        tmp_path / run_id,
        include={"index.html", "campaign_mobile", "hero"},
    )
    client = TestClient(app)

    resp = client.get(f"/api/runs/{run_id}/package.zip")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
        assert names == {
            "campaign_package.json",
            "index.html",
            "campaign_mobile.png",
            "hero.png",
        }


def test_get_package_zip_falls_back_to_generated_image(
    monkeypatch, tmp_path: Path
) -> None:
    """When hero_image_path is null, generated_image_path is used as fallback."""
    _patch_output_root(monkeypatch, tmp_path)
    run_id = "pkg-gen-fallback"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "generated_hero.png").write_bytes(b"\x89PNGgen")
    pkg = {
        "preview_html_path": None,
        "desktop_screenshot": None,
        "mobile_screenshot": None,
        "campaign_image_asset": {
            "hero_image_path": None,
            "generated_image_path": "generated_hero.png",
        },
    }
    (run_dir / "campaign_package.json").write_text(json.dumps(pkg), encoding="utf-8")
    client = TestClient(app)

    resp = client.get(f"/api/runs/{run_id}/package.zip")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert "hero.png" in zf.namelist()
        assert zf.read("hero.png") == b"\x89PNGgen"
