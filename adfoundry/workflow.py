from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict
from uuid import uuid4

from langchain_core._api.deprecation import LangChainPendingDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message=r"The default value of `allowed_objects` will change.*",
    category=LangChainPendingDeprecationWarning,
    module=r"langgraph\.cache\.base.*",
)
from langgraph.graph import END, START, StateGraph
from loguru import logger
from pydantic import BaseModel

from adfoundry.browser import render_campaign_html, research_page
from adfoundry.fixtures import (
    build_campaign_html,
    choose_strategy,
    fixture_brand_kit,
    fixture_copy,
    fixture_decisions,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.image_assets import build_campaign_image_asset
from adfoundry.logging_config import configure_logging
from adfoundry.llm import OpenAIModelGateway, json_prompt
from adfoundry.models import (
    AgentActivity,
    BrandKit,
    CampaignBrief,
    CampaignCopy,
    CampaignHtml,
    CampaignImageAsset,
    CampaignPackage,
    DecisionRecord,
    PageResearch,
    QaReport,
    RunMode,
    StrategyOption,
    VisualConcept,
    ensure_http_url,
)
from adfoundry.qa import evaluate_campaign, should_repair
from adfoundry.settings import get_settings


class CampaignState(TypedDict, total=False):
    run_id: str
    mode_requested: RunMode
    mode_used: RunMode
    output_dir: Path
    brief: CampaignBrief
    page_research: PageResearch
    brand_kit: BrandKit
    strategy_options: list[StrategyOption]
    selected_strategy: StrategyOption
    decisions: list[DecisionRecord]
    visual_concept: VisualConcept
    campaign_image_asset: CampaignImageAsset
    campaign_copy: CampaignCopy
    campaign_html: CampaignHtml
    qa_report: QaReport
    repair_history: list[QaReport]
    activities: list[AgentActivity]
    preview_html_path: str
    desktop_screenshot: str
    mobile_screenshot: str
    repair_attempts: int
    package: CampaignPackage


class StrategyOptionsOutput(BaseModel):
    options: list[StrategyOption]


class DecisionsOutput(BaseModel):
    decisions: list[DecisionRecord]


def run_campaign(
    brief: CampaignBrief,
    mode: RunMode | None = None,
    output_root: Path | str | None = None,
) -> CampaignPackage:
    settings = get_settings()
    mode = mode or settings.default_run_mode
    output_root = output_root or settings.output_root
    normalized_brief = brief.model_copy(update={"url": ensure_http_url(brief.url)})
    run_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "-" + uuid4().hex[:8]
    output_dir = Path(output_root) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(output_dir=output_dir, run_id=run_id, level=settings.log_level)
    logger.info(
        "Campaign run started run_id={} mode={} url={} theme={} goal={} output_dir={}",
        run_id,
        mode,
        normalized_brief.url,
        normalized_brief.theme,
        normalized_brief.goal,
        output_dir,
    )

    graph = build_graph()
    initial_state: CampaignState = {
        "run_id": run_id,
        "mode_requested": mode,
        "mode_used": mode,
        "output_dir": output_dir,
        "brief": normalized_brief,
        "repair_history": [],
        "activities": [],
        "repair_attempts": 0,
    }
    final_state = graph.invoke(initial_state)
    logger.info("Campaign run finished run_id={} output_dir={}", run_id, output_dir)
    return final_state["package"]


def build_graph():
    builder = StateGraph(CampaignState)
    builder.add_node("research", _research_node)
    builder.add_node("brand", _brand_node)
    builder.add_node("strategy", _strategy_node)
    builder.add_node("creative", _creative_node)
    builder.add_node("image_asset", _image_asset_node)
    builder.add_node("ui", _ui_node)
    builder.add_node("render", _render_node)
    builder.add_node("qa", _qa_node)
    builder.add_node("repair", _repair_node)
    builder.add_node("package", _package_node)

    builder.add_edge(START, "research")
    builder.add_edge("research", "brand")
    builder.add_edge("brand", "strategy")
    builder.add_edge("strategy", "creative")
    builder.add_edge("creative", "image_asset")
    builder.add_edge("image_asset", "ui")
    builder.add_edge("ui", "render")
    builder.add_edge("render", "qa")
    builder.add_conditional_edges(
        "qa",
        _route_after_qa,
        {"repair": "repair", "package": "package"},
    )
    builder.add_edge("repair", "render")
    builder.add_edge("package", END)
    return builder.compile()


def _research_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: research")
    page = research_page(state["brief"], state["output_dir"], state["mode_requested"])
    activities = _append_activity(
        state,
        "Browser Research Agent",
        f"Collected page evidence from {page.final_url} using {page.source} research.",
        "PageResearch",
    )
    mode_used = (
        "fixture" if page.source in {"fixture", "fallback"} else state["mode_requested"]
    )
    logger.info(
        "Workflow step done: research source={} images={} colors={} screenshots=({}, {})",
        page.source,
        len(page.image_assets),
        len(page.color_candidates),
        page.desktop_screenshot,
        page.mobile_screenshot,
    )
    return {"page_research": page, "activities": activities, "mode_used": mode_used}


def _brand_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: brand")
    brief = state["brief"]
    page = state["page_research"]
    fallback = fixture_brand_kit(brief, page)
    context = json.dumps(
        {"brief": brief.model_dump(), "page": page.model_dump()}, indent=2
    )
    system, user = json_prompt("Brand Analyst Agent", context)
    live = OpenAIModelGateway(state["mode_requested"]).parse(BrandKit, system, user)
    brand = live or fallback
    logger.info(
        "Workflow step done: brand brand={} live_used={} primary_colors={}",
        brand.brand_name,
        bool(live),
        brand.primary_colors,
    )
    activities = _append_activity(
        state,
        "Brand Analyst Agent",
        f"Interpreted {brand.brand_name} as {brand.tone_of_voice.lower()}.",
        "BrandKit",
    )
    return {"brand_kit": brand, "activities": activities}


def _strategy_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: strategy")
    brief = state["brief"]
    brand = state["brand_kit"]
    fallback_options = fixture_strategy_options(brief)
    fallback_selected = choose_strategy(fallback_options)
    fallback_decisions = fixture_decisions(brand, fallback_options, fallback_selected)

    context = json.dumps(
        {"brief": brief.model_dump(), "brand_kit": brand.model_dump()},
        indent=2,
    )
    system, user = json_prompt("Campaign Strategy Debate", context)
    live_options = OpenAIModelGateway(state["mode_requested"]).parse(
        StrategyOptionsOutput, system, user
    )
    options = (
        live_options.options
        if live_options and live_options.options
        else fallback_options
    )
    selected = choose_strategy(options)
    logger.info(
        "Strategy selected angle={} total_score={} live_options_used={}",
        selected.angle,
        selected.scorecard.total,
        bool(live_options),
    )

    decision_context = json.dumps(
        {
            "brief": brief.model_dump(),
            "brand_kit": brand.model_dump(),
            "options": [option.model_dump() for option in options],
            "selected": selected.model_dump(),
        },
        indent=2,
    )
    system, user = json_prompt("Decision Board Agent", decision_context)
    live_decisions = OpenAIModelGateway(state["mode_requested"]).parse(
        DecisionsOutput, system, user
    )
    decisions = (
        live_decisions.decisions
        if live_decisions and live_decisions.decisions
        else fallback_decisions
    )
    activities = state.get("activities", [])
    activities = _append_activity(
        {**state, "activities": activities},
        "Campaign Strategist Agent",
        f"Proposed {len(options)} campaign angles and selected {selected.angle}.",
        "StrategyOption",
    )
    activities = _append_activity(
        {**state, "activities": activities},
        "Brand Guardian Agent",
        "Rejected generic seasonal decoration in favor of brand-consistent holiday cues.",
        "DecisionRecord",
    )
    logger.info(
        "Workflow step done: strategy options={} decisions={}",
        len(options),
        len(decisions),
    )
    return {
        "strategy_options": options,
        "selected_strategy": selected,
        "decisions": decisions,
        "activities": activities,
    }


def _creative_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: creative")
    brief = state["brief"]
    selected = state["selected_strategy"]
    fallback_visual = fixture_visual_concept(brief, selected)
    fallback_copy = fixture_copy(brief)

    context = json.dumps(
        {
            "brief": brief.model_dump(),
            "brand_kit": state["brand_kit"].model_dump(),
            "selected_strategy": selected.model_dump(),
        },
        indent=2,
    )
    system, user = json_prompt("Creative Director Agent", context)
    visual = (
        OpenAIModelGateway(state["mode_requested"]).parse(VisualConcept, system, user)
        or fallback_visual
    )
    system, user = json_prompt("Copywriter Agent", _copywriter_context(context, brief))
    campaign_copy = (
        OpenAIModelGateway(state["mode_requested"]).parse(CampaignCopy, system, user)
        or fallback_copy
    )
    campaign_copy = _polish_campaign_copy(brief, campaign_copy)
    activities = state.get("activities", [])
    activities = _append_activity(
        {**state, "activities": activities},
        "Creative Director Agent",
        f"Defined visual direction: {visual.concept_name}.",
        "VisualConcept",
    )
    activities = _append_activity(
        {**state, "activities": activities},
        "Copywriter Agent",
        f"Selected headline '{campaign_copy.headline}' with CTA '{campaign_copy.cta}'.",
        "CampaignCopy",
    )
    logger.info(
        "Workflow step done: creative visual={} headline={}",
        visual.concept_name,
        campaign_copy.headline,
    )
    return {
        "visual_concept": visual,
        "campaign_copy": campaign_copy,
        "activities": activities,
    }


def _copywriter_context(context: str, brief: CampaignBrief) -> str:
    return (
        f"{context}\n\n"
        "Copy quality requirements:\n"
        "- The headline must be a campaign line, not a category label or navigation title.\n"
        "- Avoid formulaic headlines like "
        f"'The {brief.theme} Gift Edit', '{brief.theme} Gift Guide', "
        f"'{brief.theme} Gift Picks', and 'Shop {brief.theme} Gifts'.\n"
        "- Keep the headline short, concrete, brand-fit, and emotionally specific.\n"
        "- Put merchandising/category language in the subheadline or CTA, not the H1.\n"
        "- Do not repeat the theme literally unless it is essential to the idea.\n"
        "- Provide alternates that are genuinely different, not reordered versions of the same label."
    )


def _polish_campaign_copy(brief: CampaignBrief, copy: CampaignCopy) -> CampaignCopy:
    if not _is_generic_gift_headline(brief, copy.headline):
        return copy

    replacement = next(
        (
            alternate
            for alternate in copy.alternates
            if not _is_generic_gift_headline(brief, alternate)
        ),
        None,
    )
    if not replacement:
        replacement = _fallback_campaign_headline(brief, copy)

    return copy.model_copy(
        update={
            "headline": replacement,
            "alternates": [
                candidate
                for candidate in [copy.headline, *copy.alternates]
                if candidate != replacement
            ],
            "rationale": (
                f"{copy.rationale} Polished the H1 from a generic gift-edit label "
                "into a stronger campaign headline."
            ),
        }
    )


def _is_generic_gift_headline(brief: CampaignBrief, headline: str) -> bool:
    normalized = " ".join(headline.lower().replace("-", " ").split())
    theme = brief.theme.lower()
    generic_patterns = [
        f"the {theme} gift edit",
        f"{theme} gift edit",
        f"the {theme} gift guide",
        f"{theme} gift guide",
        f"the {theme} gift picks",
        f"{theme} gift picks",
        f"shop {theme} gifts",
        "the holiday gift edit",
        "holiday gift edit",
        "the gift edit",
        "gift edit",
    ]
    if normalized in generic_patterns:
        return True
    words = normalized.split()
    return len(words) <= 4 and words[-2:] == ["gift", "edit"]


def _fallback_campaign_headline(brief: CampaignBrief, copy: CampaignCopy) -> str:
    text = f"{copy.subheadline} {brief.goal} {brief.audience}".lower()
    if any(term in text for term in ["beauty", "glow", "skincare", "fragrance"]):
        return "Gift Beauty, Beautifully"
    if any(term in text for term in ["sport", "athlete", "performance", "shoe"]):
        return "Give the Gift of Movement"
    return "Give Something Loved"


def _image_asset_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: image_asset")
    asset = build_campaign_image_asset(
        state["brief"],
        state["page_research"],
        state["brand_kit"],
        state["visual_concept"],
        state["output_dir"],
        state["mode_requested"],
    )
    message = (
        "Generated a seasonal hero image from brand references."
        if asset.generation_mode == "generated"
        else f"Using {asset.generation_mode.replace('_', ' ')} for hero imagery."
    )
    logger.info(
        "Workflow step done: image_asset mode={} hero={} refs={} fallback={}",
        asset.generation_mode,
        asset.hero_image_path,
        len(asset.reference_image_paths),
        asset.fallback_reason or "-",
    )
    activities = _append_activity(
        state,
        "Seasonal Image Director Agent",
        message,
        "CampaignImageAsset",
    )
    return {"campaign_image_asset": asset, "activities": activities}


def _ui_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: ui")
    html = build_campaign_html(
        state["brief"],
        state["brand_kit"],
        state["visual_concept"],
        state["campaign_copy"],
        state["campaign_image_asset"],
    )
    activities = _append_activity(
        state,
        "UI Expert Agent",
        "Generated responsive split-hero HTML with editable text and a visible CTA.",
        "CampaignHtml",
    )
    logger.info(
        "Workflow step done: ui html_chars={} layout={}",
        len(html.html),
        html.layout,
    )
    return {"campaign_html": html, "activities": activities}


def _render_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: render")
    html_path, desktop, mobile = render_campaign_html(
        state["campaign_html"].html, state["output_dir"]
    )
    activities = _append_activity(
        state,
        "Browser Renderer Tool",
        "Rendered desktop and mobile campaign screenshots for visual QA.",
        "Screenshots",
    )
    logger.info(
        "Workflow step done: render html={} desktop={} mobile={}",
        html_path,
        desktop,
        mobile,
    )
    return {
        "preview_html_path": html_path,
        "desktop_screenshot": desktop,
        "mobile_screenshot": mobile,
        "activities": activities,
    }


def _qa_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: qa")
    report = evaluate_campaign(
        state["campaign_html"],
        state.get("desktop_screenshot"),
        state.get("mobile_screenshot"),
        state.get("repair_attempts", 0),
    )
    history = [*state.get("repair_history", []), report]
    message = (
        f"Approved campaign with score {report.overall_score}."
        if report.approved
        else f"Found {len(report.issues)} issue(s); score {report.overall_score}."
    )
    activities = _append_activity(state, "Visual QA Agent", message, "QaReport")
    logger.info(
        "Workflow step done: qa approved={} score={} issues={}",
        report.approved,
        report.overall_score,
        len(report.issues),
    )
    return {"qa_report": report, "repair_history": history, "activities": activities}


def _repair_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: repair attempt={}", state.get("repair_attempts", 0) + 1)
    notes = [
        issue.recommended_fix
        for issue in state["qa_report"].issues
        if issue.severity in {"high", "medium"}
    ]
    repaired = build_campaign_html(
        state["brief"],
        state["brand_kit"],
        state["visual_concept"],
        state["campaign_copy"],
        state["campaign_image_asset"],
        repair_notes=notes or ["Applied visual QA feedback."],
    )
    attempts = state.get("repair_attempts", 0) + 1
    activities = _append_activity(
        state,
        "UI Expert Agent",
        "Applied QA repair instructions and regenerated the campaign HTML.",
        "CampaignHtml",
    )
    logger.info("Workflow step done: repair attempt={} notes={}", attempts, len(notes))
    return {
        "campaign_html": repaired,
        "repair_attempts": attempts,
        "activities": activities,
    }


def _package_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: package")
    package = CampaignPackage(
        run_id=state["run_id"],
        created_at=datetime.now(UTC),
        mode_used=state["mode_used"],
        brief=state["brief"],
        page_research=state["page_research"],
        brand_kit=state["brand_kit"],
        strategy_options=state["strategy_options"],
        selected_strategy=state["selected_strategy"],
        decisions=state["decisions"],
        visual_concept=state["visual_concept"],
        campaign_image_asset=state["campaign_image_asset"],
        campaign_copy=state["campaign_copy"],
        campaign_html=state["campaign_html"],
        qa_report=state["qa_report"],
        repair_history=state.get("repair_history", []),
        activities=state.get("activities", []),
        output_dir=str(state["output_dir"]),
        preview_html_path=state["preview_html_path"],
        desktop_screenshot=state.get("desktop_screenshot"),
        mobile_screenshot=state.get("mobile_screenshot"),
    )
    package_path = state["output_dir"] / "campaign_package.json"
    package_path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Workflow step done: package path={}", package_path)
    return {"package": package}


def _route_after_qa(state: CampaignState) -> Literal["repair", "package"]:
    if should_repair(state["qa_report"], state.get("repair_attempts", 0)):
        logger.info(
            "Workflow route: qa -> repair score={} attempts={}",
            state["qa_report"].overall_score,
            state.get("repair_attempts", 0),
        )
        return "repair"
    logger.info(
        "Workflow route: qa -> package score={} attempts={}",
        state["qa_report"].overall_score,
        state.get("repair_attempts", 0),
    )
    return "package"


def _append_activity(
    state: CampaignState,
    agent: str,
    message: str,
    artifact: str | None = None,
) -> list[AgentActivity]:
    return [
        *state.get("activities", []),
        AgentActivity(agent=agent, message=message, artifact=artifact),
    ]
