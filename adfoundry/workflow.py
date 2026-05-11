from __future__ import annotations

import json
import warnings
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, TypedDict
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

from adfoundry.browser import research_page
from adfoundry.dialogue import DialogueResult, run_html_qa_dialogue
from adfoundry.events import EventType, RunEventBus
from adfoundry.fixtures import (
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
    AgentTurn,
    BrandKit,
    CampaignBrief,
    CampaignCopy,
    CampaignHtml,
    CampaignImageAsset,
    CampaignPackage,
    DecisionRecord,
    DialogueMessage,
    HtmlAttempt,
    LoopDecision,
    PageResearch,
    QaReport,
    RenderDiagnostics,
    RunMode,
    StrategyOption,
    VisualConcept,
    ensure_http_url,
)
from adfoundry.qa import should_repair
from adfoundry.settings import Settings, get_settings


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
    html_attempts: list[HtmlAttempt]
    activities: list[AgentActivity]
    agent_turns: list[AgentTurn]
    loop_decisions: list[LoopDecision]
    dialogue_messages: list[DialogueMessage]
    preview_html_path: str
    desktop_screenshot: str
    mobile_screenshot: str
    render_diagnostics: RenderDiagnostics
    repair_attempts: int
    package: CampaignPackage
    event_bus: RunEventBus | None
    runtime_settings: Settings


def _pub(state: CampaignState, type: EventType, data: dict | None = None) -> None:
    bus = state.get("event_bus")
    if bus is not None:
        bus.publish(type, data or {})


def _progress_delta_emitter(state: CampaignState, node: str) -> Callable[[str], None]:
    """Return an on_chat_delta callback that publishes node_progress delta events."""

    def _emit(text: str) -> None:
        if not text:
            return
        _pub(state, "node_progress", {"node": node, "text": text, "kind": "delta"})

    return _emit


def _progress_status(state: CampaignState, node: str, text: str) -> None:
    _pub(state, "node_progress", {"node": node, "text": text, "kind": "status"})


class StrategyOptionsOutput(BaseModel):
    chat_message: str = ""
    options: list[StrategyOption]


class DecisionsOutput(BaseModel):
    chat_message: str = ""
    decisions: list[DecisionRecord]


def run_campaign(
    brief: CampaignBrief,
    mode: RunMode | None = None,
    output_root: Path | str | None = None,
    event_bus: RunEventBus | None = None,
    run_id: str | None = None,
    settings: Settings | None = None,
) -> CampaignPackage:
    settings = settings or get_settings()
    mode = mode or settings.default_run_mode
    output_root = output_root or settings.output_root
    normalized_brief = brief.model_copy(update={"url": ensure_http_url(brief.url)})
    if run_id is None:
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

    owns_bus = event_bus is None
    if owns_bus:
        event_bus = RunEventBus(run_id, output_dir)

    graph = build_graph()
    initial_state: CampaignState = {
        "run_id": run_id,
        "mode_requested": mode,
        "mode_used": mode,
        "output_dir": output_dir,
        "brief": normalized_brief,
        "repair_history": [],
        "html_attempts": [],
        "activities": [],
        "agent_turns": [],
        "loop_decisions": [],
        "dialogue_messages": [],
        "repair_attempts": 0,
        "event_bus": event_bus,
        "runtime_settings": settings,
    }
    try:
        event_bus.publish(
            "run_started",
            {
                "run_id": run_id,
                "mode": mode,
                "brief": normalized_brief.model_dump(mode="json"),
                "output_dir": str(output_dir),
            },
        )
        final_state = graph.invoke(initial_state)
        package = final_state["package"]
        event_bus.publish(
            "run_completed",
            {
                "run_id": run_id,
                "output_dir": str(output_dir),
                "approved": package.qa_report.approved,
                "overall_score": package.qa_report.overall_score,
            },
        )
        logger.info("Campaign run finished run_id={} output_dir={}", run_id, output_dir)
        return package
    except Exception as exc:
        try:
            event_bus.publish(
                "run_failed",
                {
                    "run_id": run_id,
                    "error": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
        except Exception:  # pragma: no cover - bus might already be closed
            pass
        raise
    finally:
        if owns_bus:
            event_bus.close()


def run_revision(
    *,
    run_id: str,
    feedback: str,
    output_dir: Path,
    event_bus: RunEventBus,
    settings: Settings | None = None,
) -> CampaignPackage:
    """Re-engage the HTML/QA dialogue with a human Director turn.

    Loads the completed run's `campaign_package.json`, calls
    `run_html_qa_dialogue` with the prior messages/attempts pre-seeded plus
    the new human feedback, then merges the new turns back into the package
    file on disk. Streams events through the provided (append-mode) bus so
    SSE clients see the new turns inline with the original run.
    """
    settings = settings or get_settings()
    package_path = Path(output_dir) / "campaign_package.json"
    package = CampaignPackage.model_validate_json(
        package_path.read_text(encoding="utf-8")
    )

    revision_index = sum(
        1 for m in package.dialogue_messages if m.role == "human"
    ) + 1
    attempt_offset = (
        max((a.attempt for a in package.html_attempts), default=-1) + 1
    )

    event_bus.publish(
        "revision_started",
        {
            "run_id": run_id,
            "revision_index": revision_index,
            "feedback": feedback,
            "attempt_offset": attempt_offset,
        },
    )

    configure_logging(
        output_dir=Path(output_dir),
        run_id=run_id,
        level=settings.log_level,
    )

    result = run_html_qa_dialogue(
        brief=package.brief,
        page_research=package.page_research,
        brand_kit=package.brand_kit,
        selected_strategy=package.selected_strategy,
        visual_concept=package.visual_concept,
        campaign_copy=package.campaign_copy,
        campaign_image_asset=package.campaign_image_asset,
        output_dir=Path(output_dir),
        mode=package.mode_used,
        settings=settings,
        event_bus=event_bus,
        prior_messages=list(package.dialogue_messages),
        prior_attempts=list(package.html_attempts),
        prior_repair_history=list(package.repair_history),
        human_feedback=feedback,
        attempt_offset=attempt_offset,
    )

    merged = package.model_copy(
        update={
            "campaign_html": result.final_html,
            "qa_report": result.final_report,
            "render_diagnostics": result.final_diagnostics,
            "dialogue_messages": result.messages,
            "html_attempts": result.html_attempts,
            "repair_history": result.repair_history,
            "preview_html_path": result.final_diagnostics.html_path,
            "desktop_screenshot": result.desktop_screenshot,
            "mobile_screenshot": result.mobile_screenshot,
        }
    )
    package_path.write_text(merged.model_dump_json(indent=2), encoding="utf-8")

    event_bus.publish(
        "revision_completed",
        {
            "run_id": run_id,
            "revision_index": revision_index,
            "approved": result.final_report.approved,
            "overall_score": result.final_report.overall_score,
        },
    )
    event_bus.publish(
        "run_completed",
        {
            "run_id": run_id,
            "output_dir": str(output_dir),
            "approved": result.final_report.approved,
            "overall_score": result.final_report.overall_score,
        },
    )
    return merged


def build_graph():
    builder = StateGraph(CampaignState)
    builder.add_node("research", _research_node)
    builder.add_node("brand", _brand_node)
    builder.add_node("strategy", _strategy_node)
    builder.add_node("creative", _creative_node)
    builder.add_node("image_asset", _image_asset_node)
    builder.add_node("dialogue", _dialogue_node)
    builder.add_node("package", _package_node)

    builder.add_edge(START, "research")
    builder.add_edge("research", "brand")
    builder.add_edge("brand", "strategy")
    builder.add_edge("strategy", "creative")
    builder.add_edge("creative", "image_asset")
    builder.add_edge("image_asset", "dialogue")
    builder.add_edge("dialogue", "package")
    builder.add_edge("package", END)
    return builder.compile()


def _research_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: research")
    _pub(state, "node_started", {"node": "research"})
    _progress_status(state, "research", f"Fetching landing page {state['brief'].url}…")
    page = research_page(state["brief"], state["output_dir"], state["mode_requested"])
    _progress_status(state, "research", "Sampling colors and screenshots…")
    activities = _append_activity(
        state,
        "Browser Research Agent",
        f"Collected page evidence from {page.final_url} using {page.source} research.",
        "PageResearch",
    )
    agent_turns = _append_agent_turn(
        state,
        "research",
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
    _pub(
        state,
        "node_completed",
        {
            "node": "research",
            "final_url": page.final_url,
            "title": page.title,
            "source": page.source,
            "desktop_screenshot": page.desktop_screenshot,
            "mobile_screenshot": page.mobile_screenshot,
            "color_candidates": page.color_candidates,
            "image_count": len(page.image_assets),
        },
    )
    return {
        "page_research": page,
        "activities": activities,
        "agent_turns": agent_turns,
        "mode_used": mode_used,
    }


def _brand_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: brand")
    _pub(state, "node_started", {"node": "brand"})
    brief = state["brief"]
    page = state["page_research"]
    fallback = fixture_brand_kit(brief, page)
    context = json.dumps(
        {"brief": brief.model_dump(), "page": page.model_dump()}, indent=2
    )
    context = _agent_context(
        context,
        "Brand analysis requirements",
        [
            "Extract brand facts only from the supplied page evidence and brief.",
            "Prefer concrete products, colors, voice, and visual cues over generic category assumptions.",
            "Calibrate confidence honestly; lower confidence when evidence is thin or conflicting.",
            "Capture brand constraints that protect authenticity, rights, claims, and visual consistency.",
            "Use chat_message to narrate what you are producing as one short, user-facing sentence (e.g. 'Reading the palette to ground the brand voice…'). The UI streams this field token-by-token.",
        ],
    )
    system, user = json_prompt("Brand Analyst Agent", context)
    live = OpenAIModelGateway(state["mode_requested"], settings=state["runtime_settings"]).stream_messages(
        BrandKit,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        on_chat_delta=_progress_delta_emitter(state, "brand"),
    )
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
    agent_turns = _append_agent_turn(
        state,
        "brand",
        "Brand Analyst Agent",
        f"Interpreted {brand.brand_name} as {brand.tone_of_voice.lower()}.",
        "BrandKit",
    )
    _pub(
        state,
        "node_completed",
        {
            "node": "brand",
            "brand_name": brand.brand_name,
            "industry": brand.industry,
            "primary_colors": brand.primary_colors,
            "tone_of_voice": brand.tone_of_voice,
        },
    )
    return {"brand_kit": brand, "activities": activities, "agent_turns": agent_turns}


def _strategy_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: strategy")
    _pub(state, "node_started", {"node": "strategy"})
    brief = state["brief"]
    brand = state["brand_kit"]
    fallback_options = fixture_strategy_options(brief)
    fallback_selected = choose_strategy(fallback_options)
    fallback_decisions = fixture_decisions(brand, fallback_options, fallback_selected)

    context = json.dumps(
        {"brief": brief.model_dump(), "brand_kit": brand.model_dump()},
        indent=2,
    )
    context = _agent_context(
        context,
        "Strategy debate requirements",
        [
            "Develop meaningfully different strategic territories, not reordered versions of one seasonal idea.",
            "Prioritize brand fit, audience relevance, conversion potential, and visual distinctiveness.",
            "Avoid generic holiday, gift-guide, luxury, and discount-led angles unless the evidence supports them.",
            "Score implementation risk honestly and explain trade-offs in decision-grade language.",
            "Use chat_message to narrate the angle you are exploring as one short, user-facing sentence (e.g. 'Sketching three strategic territories…'). The UI streams this field token-by-token.",
        ],
    )
    system, user = json_prompt("Campaign Strategy Debate", context)
    live_options = OpenAIModelGateway(state["mode_requested"], settings=state["runtime_settings"]).stream_messages(
        StrategyOptionsOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        on_chat_delta=_progress_delta_emitter(state, "strategy"),
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
    decision_context = _agent_context(
        decision_context,
        "Decision board requirements",
        [
            "Make the selected and rejected reasoning audit-ready for an executive review.",
            "Explain why the chosen option is stronger for the brand, audience, and campaign goal.",
            "Reject generic or unsupported directions explicitly when they weaken brand credibility.",
            "Keep each decision concise, specific, and tied to the supplied scorecard evidence.",
            "Use chat_message to narrate the decision you are recording as one short, user-facing sentence (e.g. 'Recording why the chosen angle wins…'). The UI streams this field token-by-token.",
        ],
    )
    system, user = json_prompt("Decision Board Agent", decision_context)
    _progress_status(state, "strategy", "Recording strategy decisions…")
    live_decisions = OpenAIModelGateway(state["mode_requested"], settings=state["runtime_settings"]).stream_messages(
        DecisionsOutput,
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        on_chat_delta=_progress_delta_emitter(state, "strategy"),
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
    agent_turns = _append_agent_turn(
        state,
        "strategy",
        "Campaign Strategy Debate",
        f"Selected {selected.angle} from {len(options)} strategy option(s).",
        "StrategyOption",
    )
    logger.info(
        "Workflow step done: strategy options={} decisions={}",
        len(options),
        len(decisions),
    )
    _pub(
        state,
        "node_completed",
        {
            "node": "strategy",
            "selected_angle": selected.angle,
            "selected_name": selected.name,
            "options_count": len(options),
            "decisions_count": len(decisions),
        },
    )
    return {
        "strategy_options": options,
        "selected_strategy": selected,
        "decisions": decisions,
        "activities": activities,
        "agent_turns": agent_turns,
    }


def _creative_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: creative")
    _pub(state, "node_started", {"node": "creative"})
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
    visual_context = _agent_context(
        context,
        "Creative direction requirements",
        [
            "Create a premium campaign visual concept that can be executed in both image generation and responsive HTML.",
            "Translate the strategy into layout, image, color, and composition choices with clear constraints.",
            "Use brand colors as integrated accents unless the evidence supports a more immersive treatment.",
            "Avoid decorative seasonality that competes with product, brand, or conversion clarity.",
            "Use chat_message to narrate the creative direction you are forming as one short, user-facing sentence (e.g. 'Sketching the hero composition…'). The UI streams this field token-by-token.",
        ],
    )
    system, user = json_prompt("Creative Director Agent", visual_context)
    visual = (
        OpenAIModelGateway(state["mode_requested"], settings=state["runtime_settings"]).stream_messages(
            VisualConcept,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            on_chat_delta=_progress_delta_emitter(state, "creative"),
        )
        or fallback_visual
    )
    _progress_status(state, "creative", "Writing campaign copy…")
    system, user = json_prompt("Copywriter Agent", _copywriter_context(context, brief))
    campaign_copy = (
        OpenAIModelGateway(state["mode_requested"], settings=state["runtime_settings"]).stream_messages(
            CampaignCopy,
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            on_chat_delta=_progress_delta_emitter(state, "creative"),
        )
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
    agent_turns = _append_agent_turn(
        state,
        "creative",
        "Creative Team",
        f"Defined {visual.concept_name} and selected headline '{campaign_copy.headline}'.",
        "VisualConcept",
    )
    logger.info(
        "Workflow step done: creative visual={} headline={}",
        visual.concept_name,
        campaign_copy.headline,
    )
    _pub(
        state,
        "node_completed",
        {
            "node": "creative",
            "concept_name": visual.concept_name,
            "headline": campaign_copy.headline,
            "subheadline": campaign_copy.subheadline,
            "cta": campaign_copy.cta,
        },
    )
    return {
        "visual_concept": visual,
        "campaign_copy": campaign_copy,
        "activities": activities,
        "agent_turns": agent_turns,
    }


def _agent_context(context: str, title: str, requirements: list[str]) -> str:
    return f"{context}\n\n{title}:\n" + "\n".join(
        f"- {requirement}" for requirement in requirements
    )


def _copywriter_context(context: str, brief: CampaignBrief) -> str:
    return (
        f"{context}\n\n"
        "Copy quality requirements:\n"
        "- Write like a senior brand campaign copywriter: polished, specific, and commercially useful.\n"
        "- The headline must be a campaign idea, not a category label, navigation title, or SEO phrase.\n"
        "- Avoid formulaic headlines like "
        f"'The {brief.theme} Gift Edit', '{brief.theme} Gift Guide', "
        f"'{brief.theme} Gift Picks', and 'Shop {brief.theme} Gifts'.\n"
        "- Avoid vague luxury, holiday magic, elevated, unforgettable, and perfect-gift clichés.\n"
        "- Keep the headline short, concrete, brand-fit, and emotionally specific.\n"
        "- Put merchandising/category language in the subheadline or CTA, not the H1.\n"
        "- Make the CTA honor the brief's preferred action when it is plausible and brand-safe.\n"
        "- Do not invent discounts, claims, product capabilities, exclusivity, or endorsements.\n"
        "- Do not repeat the theme literally unless it is essential to the idea.\n"
        "- Provide alternates that explore different creative territories, not reordered versions of the same label.\n"
        "- Use chat_message to narrate the headline you are testing as one short, user-facing sentence (e.g. 'Trying a quieter, brand-forward H1…'). The UI streams this field token-by-token."
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
    _pub(state, "node_started", {"node": "image_asset"})
    _progress_status(state, "image_asset", "Preparing references and generating hero…")
    asset = build_campaign_image_asset(
        state["brief"],
        state["page_research"],
        state["brand_kit"],
        state["visual_concept"],
        state["output_dir"],
        state["mode_requested"],
        settings=state["runtime_settings"],
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
    agent_turns = _append_agent_turn(
        state,
        "image_asset",
        "Seasonal Image Director Agent",
        message,
        "CampaignImageAsset",
    )
    _pub(
        state,
        "node_completed",
        {
            "node": "image_asset",
            "generation_mode": asset.generation_mode,
            "hero_image_path": asset.hero_image_path,
            "reference_count": len(asset.reference_image_paths),
            "fallback_reason": asset.fallback_reason,
        },
    )
    return {
        "campaign_image_asset": asset,
        "activities": activities,
        "agent_turns": agent_turns,
    }


def _dialogue_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: dialogue")
    _pub(state, "node_started", {"node": "dialogue"})
    settings = state["runtime_settings"]
    result: DialogueResult = run_html_qa_dialogue(
        brief=state["brief"],
        page_research=state["page_research"],
        brand_kit=state["brand_kit"],
        selected_strategy=state["selected_strategy"],
        visual_concept=state["visual_concept"],
        campaign_copy=state["campaign_copy"],
        campaign_image_asset=state["campaign_image_asset"],
        output_dir=state["output_dir"],
        mode=state["mode_requested"],
        settings=settings,
        event_bus=state.get("event_bus"),
    )

    activities = state.get("activities", [])
    agent_turns = state.get("agent_turns", [])
    loop_decisions = state.get("loop_decisions", [])
    max_repairs = max(0, settings.html_max_attempts - 1)

    for index, item in enumerate(result.html_attempts):
        report = item.qa_report
        attempt_idx = item.attempt
        gen_message = (
            "Generated a new standalone campaign HTML composition."
            if attempt_idx == 0
            else "Regenerated the full campaign HTML from visual QA feedback."
        )
        activities = [
            *activities,
            AgentActivity(agent="HTML Generator Agent", message=gen_message, artifact="CampaignHtml"),
        ]
        agent_turns = [
            *agent_turns,
            AgentTurn(
                node="html_generate",
                agent="HTML Generator Agent",
                message=gen_message,
                artifact="CampaignHtml",
                attempt=attempt_idx,
            ),
        ]
        render_message = "Rendered desktop and mobile screenshots and collected DOM layout diagnostics."
        activities = [
            *activities,
            AgentActivity(agent="Browser Renderer Tool", message=render_message, artifact="RenderDiagnostics"),
        ]
        agent_turns = [
            *agent_turns,
            AgentTurn(
                node="render",
                agent="Browser Renderer Tool",
                message=render_message,
                artifact="RenderDiagnostics",
                attempt=attempt_idx,
            ),
        ]
        if report is None:
            qa_message = "Visual QA was skipped."
        elif report.approved:
            qa_message = f"Approved campaign with score {report.overall_score}."
        else:
            qa_message = f"Found {len(report.issues)} issue(s); score {report.overall_score}."
        activities = [
            *activities,
            AgentActivity(agent="Visual QA Agent", message=qa_message, artifact="QaReport"),
        ]
        agent_turns = [
            *agent_turns,
            AgentTurn(
                node="visual_qa",
                agent="Visual QA Agent",
                message=qa_message,
                artifact="QaReport",
                attempt=attempt_idx,
            ),
        ]
        if report is not None:
            is_last = index == len(result.html_attempts) - 1
            repair = (
                should_repair(
                    report,
                    attempt_idx,
                    max_attempts=max_repairs,
                    min_score=settings.html_min_score,
                )
                and not (is_last and report.approved)
            )
            next_node = "html_generate" if repair else "package"
            reason = (
                "QA failed repair criteria and another HTML attempt is available."
                if repair
                else "QA approved or repair budget is exhausted."
            )
            loop_decisions = [
                *loop_decisions,
                LoopDecision(
                    node="visual_qa",
                    next_node=next_node,
                    should_repair=repair,
                    attempt=attempt_idx,
                    score=report.overall_score,
                    approved=report.approved,
                    min_score=settings.html_min_score,
                    html_max_attempts=settings.html_max_attempts,
                    max_repairs=max_repairs,
                    reason=reason,
                ),
            ]

    diagnostics = result.final_diagnostics
    logger.info(
        "Workflow step done: dialogue approved={} score={} attempts={} messages={}",
        result.final_report.approved,
        result.final_report.overall_score,
        len(result.html_attempts),
        len(result.messages),
    )
    _pub(
        state,
        "node_completed",
        {
            "node": "dialogue",
            "approved": result.final_report.approved,
            "overall_score": result.final_report.overall_score,
            "attempts": len(result.html_attempts),
            "messages": len(result.messages),
        },
    )

    return {
        "campaign_html": result.final_html,
        "qa_report": result.final_report,
        "repair_history": result.repair_history,
        "html_attempts": result.html_attempts,
        "repair_attempts": result.final_html.attempt,
        "render_diagnostics": diagnostics,
        "preview_html_path": diagnostics.html_path,
        "desktop_screenshot": result.desktop_screenshot,
        "mobile_screenshot": result.mobile_screenshot,
        "activities": activities,
        "agent_turns": agent_turns,
        "loop_decisions": loop_decisions,
        "dialogue_messages": result.messages,
    }


def _package_node(state: CampaignState) -> CampaignState:
    logger.info("Workflow step start: package")
    _pub(state, "node_started", {"node": "package"})
    _progress_status(state, "package", "Assembling campaign_package.json…")
    agent_turns = _append_agent_turn(
        state,
        "package",
        "Packaging Agent",
        "Assembled final campaign package and wrote campaign_package.json.",
        "CampaignPackage",
    )
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
        html_attempts=state.get("html_attempts", []),
        render_diagnostics=state.get("render_diagnostics"),
        activities=state.get("activities", []),
        agent_turns=agent_turns,
        loop_decisions=state.get("loop_decisions", []),
        dialogue_messages=state.get("dialogue_messages", []),
        output_dir=str(state["output_dir"]),
        preview_html_path=state["preview_html_path"],
        desktop_screenshot=state.get("desktop_screenshot"),
        mobile_screenshot=state.get("mobile_screenshot"),
    )
    package_path = state["output_dir"] / "campaign_package.json"
    package_path.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Workflow step done: package path={}", package_path)
    _pub(
        state,
        "node_completed",
        {
            "node": "package",
            "package_path": str(package_path),
            "preview_html_path": str(state["preview_html_path"]),
        },
    )
    return {"package": package, "agent_turns": agent_turns}


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


def _append_agent_turn(
    state: CampaignState,
    node: str,
    agent: str,
    message: str,
    artifact: str | None = None,
    attempt: int | None = None,
) -> list[AgentTurn]:
    return [
        *state.get("agent_turns", []),
        AgentTurn(
            node=node,
            agent=agent,
            message=message,
            artifact=artifact,
            attempt=attempt,
        ),
    ]
