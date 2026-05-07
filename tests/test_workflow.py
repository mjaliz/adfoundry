from pathlib import Path

from PIL import Image

from adfoundry.fixtures import (
    build_campaign_html,
    fixture_brand_kit,
    fixture_copy,
    fixture_page_research,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.models import CampaignBrief, CampaignImageAsset
from adfoundry.workflow import run_campaign


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


def test_campaign_records_decisions_and_repair_history(tmp_path: Path) -> None:
    package = run_campaign(CampaignBrief(), mode="fixture", output_root=tmp_path)

    decision_agents = {decision.agent for decision in package.decisions}
    assert "Brand Analyst" in decision_agents
    assert "Campaign Strategist" in decision_agents
    assert "Brand Guardian" in decision_agents
    assert len(package.repair_history) == 2
    assert package.repair_history[0].approved is False
    assert package.repair_history[-1].approved is True


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
