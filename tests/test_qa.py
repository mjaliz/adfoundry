from adfoundry.fixtures import (
    build_campaign_html,
    fixture_brand_kit,
    fixture_copy,
    fixture_page_research,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.models import CampaignBrief
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
