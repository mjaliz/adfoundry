from __future__ import annotations

import json
from html import escape
from pathlib import Path

from pydantic import BaseModel

from adfoundry.fixtures import build_campaign_html
from adfoundry.image_assets import image_to_data_url
from adfoundry.llm import OpenAIModelGateway, json_prompt
from adfoundry.models import (
    BrandKit,
    CampaignBrief,
    CampaignCopy,
    CampaignHtml,
    CampaignImageAsset,
    HtmlAttempt,
    PageResearch,
    RunMode,
    StrategyOption,
    VisualConcept,
)
from adfoundry.settings import Settings, get_settings


class HtmlGenerationOutput(BaseModel):
    html: str
    css_summary: str
    layout: str
    rationale: str


def generate_campaign_html(
    brief: CampaignBrief,
    page_research: PageResearch,
    brand_kit: BrandKit,
    selected_strategy: StrategyOption,
    visual_concept: VisualConcept,
    campaign_copy: CampaignCopy,
    campaign_image_asset: CampaignImageAsset | None,
    output_dir: Path,
    mode: RunMode,
    prior_attempts: list[HtmlAttempt],
    settings: Settings | None = None,
) -> CampaignHtml:
    settings = settings or get_settings()
    attempt = len(prior_attempts)
    fallback = _fallback_html(
        brief,
        brand_kit,
        visual_concept,
        campaign_copy,
        campaign_image_asset,
        prior_attempts,
        attempt,
    )
    if mode == "fixture":
        return fallback

    context = _generation_context(
        brief,
        page_research,
        brand_kit,
        selected_strategy,
        visual_concept,
        campaign_copy,
        campaign_image_asset,
        output_dir,
        prior_attempts,
        attempt,
    )
    system, user = json_prompt("HTML Generator Agent", context)
    live = OpenAIModelGateway(mode, settings=settings).parse(HtmlGenerationOutput, system, user)
    if not live:
        return fallback.model_copy(
            update={
                "generation_mode": "fallback",
                "rationale": "Live HTML generation was unavailable, so fixture HTML was used as a safe fallback.",
            }
        )

    return CampaignHtml(
        html=_normalize_html(live.html),
        css_summary=live.css_summary,
        layout=live.layout,
        generation_mode="llm",
        attempt=attempt,
        rationale=live.rationale,
        repair_notes=_latest_repair_notes(prior_attempts),
    )


def _fallback_html(
    brief: CampaignBrief,
    brand_kit: BrandKit,
    visual_concept: VisualConcept,
    campaign_copy: CampaignCopy,
    campaign_image_asset: CampaignImageAsset | None,
    prior_attempts: list[HtmlAttempt],
    attempt: int,
) -> CampaignHtml:
    fallback = build_campaign_html(
        brief,
        brand_kit,
        visual_concept,
        campaign_copy,
        campaign_image_asset,
        repair_notes=_latest_repair_notes(prior_attempts),
    )
    return fallback.model_copy(
        update={
            "generation_mode": "fixture",
            "attempt": attempt,
            "rationale": "Deterministic fixture HTML used for reliable fixture or fallback mode.",
        }
    )


def _generation_context(
    brief: CampaignBrief,
    page_research: PageResearch,
    brand_kit: BrandKit,
    selected_strategy: StrategyOption,
    visual_concept: VisualConcept,
    campaign_copy: CampaignCopy,
    campaign_image_asset: CampaignImageAsset | None,
    output_dir: Path,
    prior_attempts: list[HtmlAttempt],
    attempt: int,
) -> str:
    hero_src = _hero_image_src(campaign_image_asset, output_dir)
    hero_size = _hero_image_size(campaign_image_asset)
    payload = {
        "attempt": attempt,
        "brief": brief.model_dump(),
        "page_research": {
            "final_url": page_research.final_url,
            "title": page_research.title,
            "headings": page_research.headings,
            "buttons": page_research.buttons,
            "color_candidates": page_research.color_candidates,
            "source_screenshots": {
                "desktop": page_research.desktop_screenshot,
                "mobile": page_research.mobile_screenshot,
            },
        },
        "brand_kit": brand_kit.model_dump(),
        "selected_strategy": selected_strategy.model_dump(),
        "visual_concept": visual_concept.model_dump(),
        "campaign_copy": campaign_copy.model_dump(),
        "hero_image": {
            "src": hero_src,
            "size": hero_size,
            "generation_mode": campaign_image_asset.generation_mode if campaign_image_asset else None,
            "fallback_reason": campaign_image_asset.fallback_reason if campaign_image_asset else None,
        },
        "prior_attempts": [_attempt_summary(attempt_item) for attempt_item in prior_attempts[-3:]],
    }
    return (
        json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n\nHTML generation requirements:\n"
        "- Return a complete standalone HTML document with inline CSS only.\n"
        "- Do not choose from a fixed template; design the layout that best fits the evidence and media.\n"
        "- Use the hero_image.src value exactly for the primary visual if it is non-empty.\n"
        "- Preserve important image content. If the source image is very wide, prefer contain, a wide band, or a layout with matching aspect ratio over cropping.\n"
        "- Keep desktop and mobile first viewports polished, readable, and conversion-focused.\n"
        "- Put a visible CTA above the fold on desktop and mobile.\n"
        "- Avoid external JS, external CSS, external fonts, and hidden explanatory copy."
    )


def _attempt_summary(attempt: HtmlAttempt) -> dict[str, object]:
    report = attempt.qa_report
    diagnostics = attempt.render_diagnostics
    return {
        "attempt": attempt.attempt,
        "layout": attempt.campaign_html.layout,
        "approved": report.approved if report else None,
        "score": report.overall_score if report else None,
        "issues": [
            {
                "severity": issue.severity,
                "problem": issue.problem,
                "suspected_cause": issue.suspected_cause,
                "regeneration_instruction": issue.regeneration_instruction or issue.recommended_fix,
            }
            for issue in (report.issues if report else [])
        ],
        "desktop_image_fit": _fit_summary(diagnostics.desktop if diagnostics else None),
        "mobile_image_fit": _fit_summary(diagnostics.mobile if diagnostics else None),
    }


def _fit_summary(viewport) -> dict[str, object] | None:
    if not viewport:
        return None
    return {
        "object_fit": viewport.object_fit,
        "visible_width_ratio": viewport.image_visible_width_ratio,
        "visible_height_ratio": viewport.image_visible_height_ratio,
        "crop_risk": viewport.image_crop_risk,
        "text_overflows": viewport.text_overflows,
        "cta_above_fold": viewport.cta_above_fold,
    }


def _latest_repair_notes(prior_attempts: list[HtmlAttempt]) -> list[str]:
    if not prior_attempts or not prior_attempts[-1].qa_report:
        return []
    return [
        issue.regeneration_instruction or issue.recommended_fix
        for issue in prior_attempts[-1].qa_report.issues
        if issue.severity in {"high", "medium"}
    ]


def _hero_image_src(
    campaign_image_asset: CampaignImageAsset | None,
    output_dir: Path,
) -> str:
    if not campaign_image_asset or not campaign_image_asset.hero_image_path:
        return ""
    raw_path = campaign_image_asset.hero_image_path
    if raw_path.startswith(("http://", "https://", "data:")):
        return raw_path
    path = Path(raw_path.removeprefix("file://"))
    if not path.exists():
        return escape(raw_path, quote=True)
    try:
        return escape(path.relative_to(output_dir).as_posix(), quote=True)
    except ValueError:
        return image_to_data_url(path)


def _hero_image_size(campaign_image_asset: CampaignImageAsset | None) -> str | None:
    if not campaign_image_asset or not campaign_image_asset.hero_image_path:
        return None
    raw_path = campaign_image_asset.hero_image_path
    if raw_path.startswith(("http://", "https://", "data:")):
        return None
    path = Path(raw_path.removeprefix("file://"))
    if not path.exists():
        return None
    try:
        from PIL import Image

        with Image.open(path) as image:
            return f"{image.width}x{image.height}"
    except Exception:
        return None


def _normalize_html(html: str) -> str:
    normalized = html.strip()
    if normalized.startswith("```"):
        lines = normalized.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        normalized = "\n".join(lines).strip()
    if "<!doctype" not in normalized[:40].lower():
        normalized = "<!doctype html>\n" + normalized
    return normalized
