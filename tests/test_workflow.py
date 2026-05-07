from pathlib import Path

from adfoundry.models import CampaignBrief
from adfoundry.workflow import run_campaign


def test_fixture_campaign_generates_package(tmp_path: Path) -> None:
    package = run_campaign(CampaignBrief(), mode="fixture", output_root=tmp_path)

    assert package.brand_kit.brand_name == "Nike"
    assert package.selected_strategy.angle == "Christmas performance gifting"
    assert package.qa_report.approved is True
    assert package.qa_report.overall_score >= 85
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
