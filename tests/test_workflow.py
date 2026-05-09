from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from adfoundry.fixtures import (
    build_campaign_html,
    fixture_brand_kit,
    fixture_copy,
    fixture_page_research,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.models import (
    CampaignBrief,
    CampaignHtml,
    CampaignImageAsset,
    QaReport,
    RenderDiagnostics,
    ViewportRenderDiagnostics,
)
from adfoundry.workflow import _merge_live_visual_qa_if_required, _polish_campaign_copy, run_campaign


def test_fixture_campaign_generates_package(tmp_path: Path) -> None:
    package = run_campaign(CampaignBrief(), mode="fixture", output_root=tmp_path)

    assert package.brand_kit.brand_name == "Nike"
    assert package.selected_strategy.angle == "Christmas performance gifting"
    assert package.qa_report.approved is True
    assert package.qa_report.overall_score >= 85
    assert package.campaign_image_asset.generation_mode == "fixture_fallback"
    assert package.campaign_image_asset.hero_image_path is not None
    assert len(package.activities) >= 8
    assert Path(package.preview_html_path).exists()
    assert Path(package.output_dir, "campaign_package.json").exists()
    assert len(package.html_attempts) == 2
    assert package.render_diagnostics is not None


def test_campaign_records_decisions_and_repair_history(tmp_path: Path) -> None:
    package = run_campaign(CampaignBrief(), mode="fixture", output_root=tmp_path)

    decision_agents = {decision.agent for decision in package.decisions}
    assert "Brand Analyst" in decision_agents
    assert "Campaign Strategist" in decision_agents
    assert "Brand Guardian" in decision_agents
    assert len(package.repair_history) == 2
    assert package.repair_history[0].approved is False
    assert package.repair_history[-1].approved is True
    assert package.html_attempts[0].qa_report is not None
    assert package.html_attempts[-1].campaign_html.repair_notes


def test_campaign_html_embeds_local_hero_image(tmp_path: Path) -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[0])
    copy = fixture_copy(brief)
    hero_path = tmp_path / "generated_hero.png"
    Image.new("RGB", (24, 24), "#111111").save(hero_path)
    image_asset = CampaignImageAsset(
        generation_prompt="test prompt",
        generated_image_path=str(hero_path),
        hero_image_path=str(hero_path),
        generation_mode="generated",
    )

    campaign_html = build_campaign_html(brief, brand, visual, copy, image_asset)

    assert 'src="data:image/png;base64,' in campaign_html.html
    assert "file://" not in campaign_html.html


def test_campaign_html_uses_brand_color_as_integrated_treatment() -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[0])
    copy = fixture_copy(brief)

    campaign_html = build_campaign_html(brief, brand, visual, copy)

    assert "--brand-primary: #111111;" in campaign_html.html
    assert "min-height: max(720px, 100vh);" in campaign_html.html
    assert "body {\n      margin: 0;\n      background: #111111;" not in campaign_html.html
    assert "linear-gradient(90deg, var(--brand-accent), transparent)" in campaign_html.html


def test_generic_gift_edit_headline_is_polished() -> None:
    copy = fixture_copy(CampaignBrief())
    copy = copy.model_copy(
        update={
            "headline": "The Christmas Gift Edit",
            "alternates": [
                "Gift Beauty, Beautifully",
                "Holiday Beauty Gifts, Curated",
            ],
            "subheadline": "Premium beauty sets, fragrance, and skincare for holiday gifting.",
        }
    )

    polished = _polish_campaign_copy(CampaignBrief(), copy)

    assert polished.headline == "Gift Beauty, Beautifully"
    assert "The Christmas Gift Edit" in polished.alternates


def test_short_mood_gift_edit_headline_is_polished() -> None:
    brief = CampaignBrief(theme="Halloween")
    copy = fixture_copy(brief)
    copy = copy.model_copy(
        update={
            "headline": "The Midnight Gift Edit",
            "alternates": [],
            "subheadline": "After-dark picks for every athlete, including shoes and apparel.",
        }
    )

    polished = _polish_campaign_copy(brief, copy)

    assert polished.headline == "Give the Gift of Movement"
    assert "The Midnight Gift Edit" in polished.alternates


def test_live_visual_qa_receives_raw_html_and_screenshot_images(tmp_path: Path, monkeypatch) -> None:
    desktop = tmp_path / "desktop.png"
    mobile = tmp_path / "mobile.png"
    Image.new("RGB", (1440, 960), "#111111").save(desktop)
    Image.new("RGB", (390, 844), "#222222").save(mobile)
    report = _passing_qa_report()
    state = _live_qa_state(tmp_path, desktop, mobile)
    captured = {}

    def fake_parse(self, schema, system, user):
        captured["schema"] = schema
        captured["system"] = system
        captured["user"] = user
        return report

    monkeypatch.setattr(
        "adfoundry.workflow.get_settings",
        lambda: SimpleNamespace(html_require_live_qa=True),
    )
    monkeypatch.setattr("adfoundry.workflow.OpenAIModelGateway.parse", fake_parse)

    result = _merge_live_visual_qa_if_required(state, report)

    assert result is report
    assert captured["schema"] is QaReport
    user = captured["user"]
    assert user[0]["type"] == "input_text"
    assert "<main><h1>Generated campaign</h1></main>" in user[0]["text"]
    image_parts = user[1:]
    assert [part["type"] for part in image_parts] == ["input_image", "input_image"]
    assert all(part["image_url"].startswith("data:image/png;base64,") for part in image_parts)


def test_live_visual_qa_skips_when_screenshots_are_missing(tmp_path: Path, monkeypatch) -> None:
    mobile = tmp_path / "mobile.png"
    Image.new("RGB", (390, 844), "#222222").save(mobile)
    report = _passing_qa_report()
    state = _live_qa_state(tmp_path, None, mobile)
    called = False

    def fake_parse(self, schema, system, user):
        nonlocal called
        called = True
        return report

    monkeypatch.setattr(
        "adfoundry.workflow.get_settings",
        lambda: SimpleNamespace(html_require_live_qa=True),
    )
    monkeypatch.setattr("adfoundry.workflow.OpenAIModelGateway.parse", fake_parse)

    result = _merge_live_visual_qa_if_required(state, report)

    assert result.approved is False
    assert result.overall_score == 72
    assert any("could not inspect" in issue.problem for issue in result.issues)
    assert called is False


def _passing_qa_report() -> QaReport:
    return QaReport(
        approved=True,
        overall_score=94,
        visual_quality=9,
        brand_consistency=9,
        readability=9,
        cta_visibility=9,
        responsive_layout=9,
        accessibility=9,
        issues=[],
        summary="Deterministic QA passed.",
    )


def _live_qa_state(tmp_path: Path, desktop: Path | None, mobile: Path | None):
    campaign_html = CampaignHtml(
        html="<!doctype html><html><body><main><h1>Generated campaign</h1></main></body></html>",
        css_summary="Responsive hero CSS.",
        layout="Hero layout.",
        generation_mode="llm",
        attempt=0,
        rationale="Built for visual QA.",
    )
    return {
        "brief": CampaignBrief(),
        "campaign_html": campaign_html,
        "desktop_screenshot": str(desktop) if desktop else None,
        "mobile_screenshot": str(mobile) if mobile else None,
        "render_diagnostics": RenderDiagnostics(
            html_path=str(tmp_path / "index.html"),
            desktop_screenshot=str(desktop) if desktop else "",
            mobile_screenshot=str(mobile) if mobile else "",
            desktop=ViewportRenderDiagnostics(viewport={"width": 1440, "height": 960}),
            mobile=ViewportRenderDiagnostics(viewport={"width": 390, "height": 844}),
        ),
        "mode_requested": "live",
    }
