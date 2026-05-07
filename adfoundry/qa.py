from __future__ import annotations

from pathlib import Path

from PIL import Image

from adfoundry.fixtures import fixture_final_qa, fixture_initial_qa
from adfoundry.models import CampaignHtml, QaReport


def evaluate_campaign(
    campaign_html: CampaignHtml,
    desktop_screenshot: str | None,
    mobile_screenshot: str | None,
    attempt: int,
) -> QaReport:
    """Deterministic visual QA for the demo repair loop."""

    if campaign_html.repair_notes:
        return fixture_final_qa()

    report = fixture_initial_qa()
    if not _screenshots_exist(desktop_screenshot, mobile_screenshot):
        report.overall_score = min(report.overall_score, 72)
        report.summary = "Screenshots were not available, so the campaign requires repair/re-render review."
    elif attempt > 0:
        return fixture_final_qa()
    return report


def should_repair(report: QaReport, attempts: int, max_attempts: int = 2) -> bool:
    high_severity = any(issue.severity == "high" for issue in report.issues)
    return attempts < max_attempts and (report.overall_score < 85 or high_severity)


def _screenshots_exist(desktop_screenshot: str | None, mobile_screenshot: str | None) -> bool:
    paths = [desktop_screenshot, mobile_screenshot]
    if not all(paths):
        return False
    for path in paths:
        try:
            image = Image.open(Path(path))
            image.verify()
        except Exception:
            return False
    return True
