from __future__ import annotations

from pathlib import Path

from PIL import Image

from adfoundry.fixtures import fixture_final_qa, fixture_initial_qa
from adfoundry.models import CampaignHtml, QaIssue, QaReport, RenderDiagnostics, ViewportRenderDiagnostics


def evaluate_campaign(
    campaign_html: CampaignHtml,
    desktop_screenshot: str | None,
    mobile_screenshot: str | None,
    attempt: int,
    diagnostics: RenderDiagnostics | None = None,
    min_score: int = 85,
) -> QaReport:
    """Evaluate rendered campaign output with deterministic visual diagnostics."""

    if campaign_html.generation_mode == "fixture":
        return _evaluate_fixture_campaign(campaign_html, desktop_screenshot, mobile_screenshot, attempt)

    if diagnostics:
        return _evaluate_diagnostics(campaign_html, diagnostics, min_score)

    if campaign_html.repair_notes:
        return fixture_final_qa()

    report = fixture_initial_qa()
    if not _screenshots_exist(desktop_screenshot, mobile_screenshot):
        report.overall_score = min(report.overall_score, 72)
        report.summary = "Screenshots were not available, so the campaign requires repair/re-render review."
    elif attempt > 0:
        return fixture_final_qa()
    return report


def _evaluate_fixture_campaign(
    campaign_html: CampaignHtml,
    desktop_screenshot: str | None,
    mobile_screenshot: str | None,
    attempt: int,
) -> QaReport:
    if campaign_html.repair_notes:
        return fixture_final_qa()
    report = fixture_initial_qa()
    if not _screenshots_exist(desktop_screenshot, mobile_screenshot):
        report.overall_score = min(report.overall_score, 72)
        report.summary = "Screenshots were not available, so the campaign requires repair/re-render review."
    elif attempt > 0:
        return fixture_final_qa()
    return report


def should_repair(
    report: QaReport,
    attempts: int,
    max_attempts: int = 2,
    min_score: int = 85,
) -> bool:
    high_severity = any(issue.severity == "high" for issue in report.issues)
    return attempts < max_attempts and (report.overall_score < min_score or high_severity)


def _evaluate_diagnostics(
    campaign_html: CampaignHtml,
    diagnostics: RenderDiagnostics,
    min_score: int,
) -> QaReport:
    issues: list[QaIssue] = []
    if diagnostics.error:
        issues.append(
            QaIssue(
                severity="high",
                problem="Campaign could not be rendered normally.",
                suspected_cause=diagnostics.error,
                recommended_fix="Regenerate simpler standalone HTML that Playwright can load without runtime errors.",
                regeneration_instruction="Remove fragile scripts, external dependencies, and invalid asset references.",
            )
        )
    if not _screenshots_exist(diagnostics.desktop_screenshot, diagnostics.mobile_screenshot):
        issues.append(
            QaIssue(
                severity="high",
                problem="Rendered screenshots are missing or invalid.",
                suspected_cause="Playwright did not produce verifiable screenshots.",
                recommended_fix="Regenerate valid standalone HTML and re-render desktop/mobile screenshots.",
                regeneration_instruction="Keep all CSS inline and use stable local or data image sources.",
            )
        )

    issues.extend(_viewport_issues("desktop", diagnostics.desktop))
    issues.extend(_viewport_issues("mobile", diagnostics.mobile))

    score = _score_from_issues(issues)
    approved = score >= min_score and not any(issue.severity == "high" for issue in issues)
    return QaReport(
        approved=approved,
        overall_score=score,
        visual_quality=_category_score(score, issues, {"image", "visual", "cropped"}),
        brand_consistency=9 if score >= 85 else 8,
        readability=_category_score(score, issues, {"text", "heading", "overflow"}),
        cta_visibility=_category_score(score, issues, {"cta", "button"}),
        responsive_layout=_category_score(score, issues, {"mobile", "viewport", "overflow", "fold"}),
        accessibility=8 if issues else 9,
        issues=issues,
        summary=(
            f"Approved attempt {campaign_html.attempt}: rendered desktop/mobile diagnostics pass."
            if approved
            else f"Attempt {campaign_html.attempt} needs regeneration: {len(issues)} visual issue(s) found."
        ),
    )


def _viewport_issues(label: str, viewport: ViewportRenderDiagnostics) -> list[QaIssue]:
    issues: list[QaIssue] = []
    if viewport.image_crop_risk:
        visible_w = _percent(viewport.image_visible_width_ratio)
        visible_h = _percent(viewport.image_visible_height_ratio)
        issues.append(
            QaIssue(
                severity="high",
                problem=(
                    f"{label.title()} hero image is heavily cropped "
                    f"({visible_w} width visible, {visible_h} height visible)."
                ),
                suspected_cause=(
                    f"Image uses object-fit '{viewport.object_fit or 'unknown'}' in a box "
                    "whose aspect ratio differs from the source image."
                ),
                recommended_fix="Regenerate the layout so the important image content fits inside the hero.",
                regeneration_instruction=(
                    "Use object-fit: contain, a full-width visual band, or a layout that matches the source image aspect ratio; "
                    "do not crop wide ecommerce banners into a tall/narrow pane."
                ),
            )
        )
    if viewport.horizontal_overflow > 2:
        issues.append(
            QaIssue(
                severity="high",
                problem=f"{label.title()} layout has horizontal overflow of {viewport.horizontal_overflow:.0f}px.",
                suspected_cause="An element is wider than the viewport.",
                recommended_fix="Constrain all sections, media, and text to the viewport width.",
                regeneration_instruction="Use max-width: 100%, min-width: 0, responsive grids, and no fixed widths above the viewport.",
            )
        )
    if not viewport.cta_box:
        issues.append(
            QaIssue(
                severity="high",
                problem=f"{label.title()} CTA is missing.",
                suspected_cause="No anchor, button, or role=button element was detected.",
                recommended_fix="Add a prominent clickable CTA above the fold.",
                regeneration_instruction="Render a visible <a href> CTA using the campaign CTA text and brief URL.",
            )
        )
    elif not viewport.cta_above_fold:
        issues.append(
            QaIssue(
                severity="medium" if label == "desktop" else "high",
                problem=f"{label.title()} CTA falls below the first viewport.",
                suspected_cause="Vertical spacing or media height pushes the CTA out of view.",
                recommended_fix="Move the CTA higher and reduce first-screen vertical pressure.",
                regeneration_instruction="Keep the primary headline, supporting copy, and CTA visible without scrolling.",
            )
        )
    if viewport.text_overflows:
        issues.append(
            QaIssue(
                severity="medium",
                problem=f"{label.title()} text overflows its container.",
                suspected_cause="Type size or container width is not responsive enough.",
                recommended_fix="Regenerate with responsive type and flexible text containers.",
                regeneration_instruction="Use clamp() conservatively, min-width: 0, wrapping, and avoid viewport-width font scaling.",
            )
        )
    return issues


def _score_from_issues(issues: list[QaIssue]) -> int:
    score = 96
    for issue in issues:
        if issue.severity == "high":
            score -= 18
        elif issue.severity == "medium":
            score -= 9
        else:
            score -= 4
    return max(0, min(100, score))


def _category_score(score: int, issues: list[QaIssue], keywords: set[str]) -> int:
    matching = [
        issue
        for issue in issues
        if any(keyword in f"{issue.problem} {issue.suspected_cause}".lower() for keyword in keywords)
    ]
    if any(issue.severity == "high" for issue in matching):
        return 5
    if matching:
        return 7
    return 9 if score >= 85 else 8


def _percent(value: float | None) -> str:
    if value is None:
        return "unknown"
    return f"{value * 100:.0f}%"


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
