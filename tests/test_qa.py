from adfoundry.fixtures import (
    build_campaign_html,
    fixture_brand_kit,
    fixture_copy,
    fixture_page_research,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.models import CampaignBrief
from adfoundry.models import CampaignHtml, RenderDiagnostics, ViewportRenderDiagnostics
from adfoundry.qa import evaluate_campaign, should_repair


def test_visual_qa_requests_repair_before_html_is_fixed() -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[1])
    copy = fixture_copy(brief)
    html = build_campaign_html(brief, brand, visual, copy)

    report = evaluate_campaign(html, None, None, attempt=0)

    assert report.approved is False
    assert should_repair(report, attempts=0) is True


def test_visual_qa_approves_repaired_html() -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[1])
    copy = fixture_copy(brief)
    html = build_campaign_html(brief, brand, visual, copy, repair_notes=["Move CTA higher."])

    report = evaluate_campaign(html, None, None, attempt=1)

    assert report.approved is True
    assert should_repair(report, attempts=1) is False


def test_visual_qa_rejects_cropped_wide_hero_image() -> None:
    html = CampaignHtml(
        html="<!doctype html><html><body><main><img></main><a href='/'>Shop</a></body></html>",
        css_summary="test",
        layout="test",
        generation_mode="llm",
        attempt=0,
    )
    diagnostics = RenderDiagnostics(
        html_path="index.html",
        desktop_screenshot=__file__,
        mobile_screenshot=__file__,
        desktop=ViewportRenderDiagnostics(
            viewport={"width": 1440, "height": 960},
            screenshot_path=__file__,
            natural_image_width=3000,
            natural_image_height=675,
            object_fit="cover",
            image_visible_width_ratio=0.18,
            image_visible_height_ratio=1.0,
            image_crop_risk=True,
            cta_above_fold=True,
        ),
        mobile=ViewportRenderDiagnostics(
            viewport={"width": 390, "height": 844},
            screenshot_path=__file__,
            natural_image_width=3000,
            natural_image_height=675,
            object_fit="cover",
            image_visible_width_ratio=0.2,
            image_visible_height_ratio=1.0,
            image_crop_risk=True,
            cta_above_fold=True,
        ),
    )

    report = evaluate_campaign(
        html,
        diagnostics.desktop_screenshot,
        diagnostics.mobile_screenshot,
        attempt=0,
        diagnostics=diagnostics,
    )

    assert report.approved is False
    assert any("cropped" in issue.problem for issue in report.issues)
    assert should_repair(report, attempts=0, max_attempts=2) is True
