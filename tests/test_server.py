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


def test_start_run_threads_per_request_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    """POSTing provider+api_key results in run_campaign receiving an override
    Settings whose openai_base_url and openai_api_key reflect the request."""
    _patch_output_root(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    def fake_run_campaign(**kwargs: object) -> None:
        # Mirror what the real run does so the thread shuts down cleanly.
        bus = kwargs.get("event_bus")
        if bus is not None:
            bus.publish(  # type: ignore[union-attr]
                "run_started",
                {
                    "run_id": kwargs.get("run_id"),
                    "mode": kwargs.get("mode"),
                    "brief": {},
                    "output_dir": "",
                },
            )
        captured["settings"] = kwargs.get("settings")

    monkeypatch.setattr(server_module, "run_campaign", fake_run_campaign)
    client = TestClient(app)

    resp = client.post(
        "/api/runs",
        json={
            "brief": {"url": "https://www.nike.com", "theme": "Holiday"},
            "mode": "fixture",
            "provider": "avalai",
            "api_key": "sk-from-frontend",
        },
    )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert _wait_for(lambda: "settings" in captured, timeout=5.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=5.0)

    settings = captured["settings"]
    assert settings is not None
    assert settings.openai_api_key == "sk-from-frontend"
    assert settings.openai_base_url == "https://api.avalai.ir/v1"


def test_start_run_falls_back_to_env_when_no_credentials(
    monkeypatch, tmp_path: Path
) -> None:
    """When the request omits provider/api_key, run_campaign receives
    settings=None so it falls back to the env-loaded defaults."""
    _patch_output_root(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    def fake_run_campaign(**kwargs: object) -> None:
        bus = kwargs.get("event_bus")
        if bus is not None:
            bus.publish(  # type: ignore[union-attr]
                "run_started",
                {
                    "run_id": kwargs.get("run_id"),
                    "mode": kwargs.get("mode"),
                    "brief": {},
                    "output_dir": "",
                },
            )
        captured["settings"] = kwargs.get("settings")

    monkeypatch.setattr(server_module, "run_campaign", fake_run_campaign)
    client = TestClient(app)

    resp = client.post(
        "/api/runs",
        json={"brief": {"url": "https://www.nike.com"}, "mode": "fixture"},
    )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert _wait_for(lambda: "settings" in captured, timeout=5.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=5.0)

    assert captured["settings"] is None


def test_start_run_openai_provider_clears_base_url(
    monkeypatch, tmp_path: Path
) -> None:
    """provider='openai' produces a Settings with openai_base_url=None
    so the OpenAI default endpoint is used."""
    _patch_output_root(monkeypatch, tmp_path)

    captured: dict[str, object] = {}

    def fake_run_campaign(**kwargs: object) -> None:
        bus = kwargs.get("event_bus")
        if bus is not None:
            bus.publish(  # type: ignore[union-attr]
                "run_started",
                {
                    "run_id": kwargs.get("run_id"),
                    "mode": kwargs.get("mode"),
                    "brief": {},
                    "output_dir": "",
                },
            )
        captured["settings"] = kwargs.get("settings")

    monkeypatch.setattr(server_module, "run_campaign", fake_run_campaign)
    client = TestClient(app)

    resp = client.post(
        "/api/runs",
        json={
            "brief": {"url": "https://www.nike.com"},
            "mode": "fixture",
            "provider": "openai",
            "api_key": "sk-openai",
        },
    )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert _wait_for(lambda: "settings" in captured, timeout=5.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=5.0)

    settings = captured["settings"]
    assert settings is not None
    assert settings.openai_api_key == "sk-openai"
    assert settings.openai_base_url is None


def test_revise_endpoint_e2e_fixture_mode(monkeypatch, tmp_path: Path) -> None:
    """Run a fixture-mode campaign to completion, then POST /revise and
    verify the package gains new attempts + a human DialogueMessage."""
    _patch_output_root(monkeypatch, tmp_path)
    client = TestClient(app)

    # 1) Run an initial fixture-mode campaign to completion.
    start = client.post(
        "/api/runs",
        json={"brief": {"url": "https://www.nike.com"}, "mode": "fixture"},
    )
    assert start.status_code == 200
    run_id = start.json()["run_id"]
    pkg_path = tmp_path / run_id / "campaign_package.json"
    assert _wait_for(lambda: pkg_path.exists(), timeout=60.0)
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=10.0)

    before = json.loads(pkg_path.read_text(encoding="utf-8"))
    attempts_before = len(before["html_attempts"])
    msgs_before = len(before["dialogue_messages"])

    # 2) Submit a revision in fixture mode.
    revise = client.post(
        f"/api/runs/{run_id}/revise",
        json={"feedback": "Punchier headline, deeper hero blue."},
    )
    assert revise.status_code == 200, revise.text
    assert revise.json()["revision_index"] == 1

    # 3) Wait for the thread to finish.
    assert _wait_for(lambda: server_module._get_active(run_id) is None, timeout=60.0)

    after = json.loads(pkg_path.read_text(encoding="utf-8"))
    # Attempts grew by at least 1 (fixture mode always produces an attempt).
    assert len(after["html_attempts"]) > attempts_before
    # The human bubble was recorded.
    human_msgs = [
        m for m in after["dialogue_messages"] if m["role"] == "human"
    ]
    assert len(human_msgs) == 1
    assert "Punchier headline" in human_msgs[0]["content"]
    # Dialogue grew overall.
    assert len(after["dialogue_messages"]) > msgs_before

    # 4) events.jsonl contains revision_started followed by a later run_completed.
    lines = (tmp_path / run_id / "events.jsonl").read_text(encoding="utf-8").splitlines()
    types = [json.loads(line)["type"] for line in lines]
    assert "revision_started" in types
    # Seq numbering is monotonic across the whole file.
    seqs = [json.loads(line)["seq"] for line in lines]
    assert seqs == sorted(seqs)
    assert len(set(seqs)) == len(seqs)


def test_event_bus_append_mode_resumes_seq(tmp_path: Path) -> None:
    """Reopening a bus with append=True preserves history and continues seq."""
    from adfoundry.events import RunEventBus, replay_events

    b1 = RunEventBus("resume-run", tmp_path)
    b1.publish("run_started", {"hello": 1})
    b1.publish("node_started", {"node": "brand"})
    b1.publish("node_completed", {"node": "brand"})
    b1.close()

    b2 = RunEventBus("resume-run", tmp_path, append=True)
    assert b2._seq == 3  # noqa: SLF001
    assert len(b2._events) == 3  # noqa: SLF001
    b2.publish("revision_started", {"revision_index": 1, "feedback": "tighter"})
    b2.publish("run_completed", {"approved": True, "overall_score": 90})
    b2.close()

    events = list(replay_events("resume-run", tmp_path.parent))
    # replay_events takes an output_root, so we need a wrapper directory.
    # Reading the file directly is simpler and more direct:
    lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    seqs = [json.loads(line)["seq"] for line in lines]
    assert seqs == [1, 2, 3, 4, 5]
    types = [json.loads(line)["type"] for line in lines]
    assert types[0] == "run_started"
    assert types[3] == "revision_started"
    assert types[4] == "run_completed"
    # Suppress the unused replay_events binding (kept for ergonomics).
    _ = events


def test_revise_endpoint_404_when_no_package(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    (tmp_path / "mid-run").mkdir()
    client = TestClient(app)
    resp = client.post(
        "/api/runs/mid-run/revise", json={"feedback": "punchier please"}
    )
    assert resp.status_code == 404


def test_revise_endpoint_409_when_active_revision(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    run_dir = tmp_path / "busy-run"
    run_dir.mkdir()
    # Synthesize a completed package so the endpoint passes the 404 check.
    (run_dir / "campaign_package.json").write_text(
        '{"preview_html_path": "index.html"}', encoding="utf-8"
    )
    # Pre-register a fake bus as if a revision were already in flight.
    from adfoundry.events import RunEventBus

    fake_bus = RunEventBus("busy-run", run_dir)
    server_module._register("busy-run", fake_bus)
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/runs/busy-run/revise", json={"feedback": "tighter"}
        )
        assert resp.status_code == 409
    finally:
        fake_bus.close()
        server_module._unregister("busy-run")


def test_revise_endpoint_400_on_empty_feedback(
    monkeypatch, tmp_path: Path
) -> None:
    _patch_output_root(monkeypatch, tmp_path)
    run_dir = tmp_path / "empty-feedback-run"
    run_dir.mkdir()
    (run_dir / "campaign_package.json").write_text("{}", encoding="utf-8")
    client = TestClient(app)
    resp = client.post(
        "/api/runs/empty-feedback-run/revise", json={"feedback": "   "}
    )
    assert resp.status_code == 400


def test_revise_endpoint_threads_credentials_and_starts_thread(
    monkeypatch, tmp_path: Path
) -> None:
    """POST /revise builds an append-mode bus, kicks a thread that calls
    run_revision, and the thread receives the per-request settings override."""
    _patch_output_root(monkeypatch, tmp_path)
    run_dir = tmp_path / "credentials-revise-run"
    run_dir.mkdir()
    (run_dir / "campaign_package.json").write_text("{}", encoding="utf-8")

    captured: dict[str, object] = {}

    def fake_run_revision(**kwargs: object) -> None:
        captured["settings"] = kwargs.get("settings")
        captured["feedback"] = kwargs.get("feedback")
        captured["run_id"] = kwargs.get("run_id")

    monkeypatch.setattr(server_module, "run_revision", fake_run_revision)

    client = TestClient(app)
    resp = client.post(
        "/api/runs/credentials-revise-run/revise",
        json={
            "feedback": "make headline punchier",
            "provider": "avalai",
            "api_key": "sk-from-frontend",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["run_id"] == "credentials-revise-run"
    assert payload["revision_index"] == 1
    assert _wait_for(lambda: "settings" in captured, timeout=5.0)
    assert _wait_for(
        lambda: server_module._get_active("credentials-revise-run") is None,
        timeout=5.0,
    )

    settings = captured["settings"]
    assert settings is not None
    assert settings.openai_api_key == "sk-from-frontend"
    assert settings.openai_base_url == "https://api.avalai.ir/v1"
    assert captured["feedback"] == "make headline punchier"
    # Append-mode bus should have been used: events.jsonl exists after the thread closes.
    assert (run_dir / "events.jsonl").exists()


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
