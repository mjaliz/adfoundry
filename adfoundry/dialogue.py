from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from adfoundry.browser import render_campaign_html
from adfoundry.events import RunEventBus
from adfoundry.html_generation import build_generator_user_content
from adfoundry.html_generation import (
    generate_campaign_html as fallback_generate_campaign_html,
)
from adfoundry.llm import OpenAIModelGateway
from adfoundry.models import (
    BrandKit,
    CampaignBrief,
    CampaignCopy,
    CampaignHtml,
    CampaignImageAsset,
    DialogueMessage,
    HtmlAttempt,
    HtmlGeneratorTurn,
    PageResearch,
    QaReport,
    RenderDiagnostics,
    RunMode,
    StrategyOption,
    VisualConcept,
    VisualQaTurn,
)
from adfoundry.qa import evaluate_campaign
from adfoundry.settings import Settings, get_settings


GENERATOR_SYSTEM = (
    "You are the HTML Generator Agent in AdFoundry, in a multi-turn dialogue with the Visual QA Agent. "
    "You produce a complete standalone HTML document for the campaign and discuss it with QA. "
    "On every turn, return a JSON object matching the schema. Always set chat_message — speak directly to QA: explain a choice, "
    "acknowledge a critique, defend a decision when justified, or ask a clarifying question via questions_for_qa. "
    "When the previous QA turn raised issues or requested fixes, return updated html/css_summary/layout/rationale; otherwise you may "
    "leave html empty to continue the conversation without regenerating. Treat QA's prior critiques as authoritative on visual evidence."
)

QA_SYSTEM = (
    "You are the Visual QA Agent in AdFoundry, in a multi-turn dialogue with the HTML Generator Agent. "
    "On every turn after a render, return a JSON object matching the schema with a complete QaReport for the latest HTML, plus a chat_message. "
    "Speak directly to the Generator: cite specific evidence from the rendered screenshots and diagnostics, answer any questions_for_qa via answers_to_generator, "
    "and only set report.approved=true when the rendered output truly meets the bar. When raising issues, write actionable regeneration_instruction values."
)


@dataclass
class DialogueResult:
    final_html: CampaignHtml
    final_report: QaReport
    final_diagnostics: RenderDiagnostics
    desktop_screenshot: str | None
    mobile_screenshot: str | None
    messages: list[DialogueMessage]
    html_attempts: list[HtmlAttempt]
    repair_history: list[QaReport] = field(default_factory=list)


def run_html_qa_dialogue(
    *,
    brief: CampaignBrief,
    page_research: PageResearch,
    brand_kit: BrandKit,
    selected_strategy: StrategyOption,
    visual_concept: VisualConcept,
    campaign_copy: CampaignCopy,
    campaign_image_asset: CampaignImageAsset,
    output_dir: Path,
    mode: RunMode,
    settings: Settings | None = None,
    gateway: OpenAIModelGateway | None = None,
    event_bus: RunEventBus | None = None,
    prior_messages: list[DialogueMessage] | None = None,
    prior_attempts: list[HtmlAttempt] | None = None,
    prior_repair_history: list[QaReport] | None = None,
    human_feedback: str | None = None,
    attempt_offset: int = 0,
) -> DialogueResult:
    def _pub(type: str, data: dict) -> None:
        if event_bus is not None:
            event_bus.publish(type, data)

    settings = settings or get_settings()
    gateway = gateway or OpenAIModelGateway(mode, settings=settings)
    max_attempts = max(1, settings.html_max_attempts)

    # Seed the running history with any prior context the caller passed in.
    # Revisions use this to extend an earlier run's dialogue rather than
    # starting fresh; copy so the caller's lists are not mutated.
    messages: list[DialogueMessage] = list(prior_messages or [])
    html_attempts: list[HtmlAttempt] = list(prior_attempts or [])
    repair_history: list[QaReport] = list(prior_repair_history or [])

    # Per-agent message views for the OpenAI Responses API.
    # Each agent sees a system message plus the running conversation projected
    # so its own outputs are "assistant" turns and the other agent's are "user" turns.
    generator_view: list[dict[str, Any]] = [
        {"role": "system", "content": GENERATOR_SYSTEM}
    ]
    qa_view: list[dict[str, Any]] = [{"role": "system", "content": QA_SYSTEM}]

    # When we have prior attempts (a revision), preseed the "final" state so the
    # generator's "keep prior HTML and continue chatting" branch reuses the
    # actual prior HTML instead of falling back to fixture.
    final_html: CampaignHtml | None = None
    final_diagnostics: RenderDiagnostics | None = None
    final_report: QaReport | None = None
    if html_attempts:
        last = html_attempts[-1]
        final_html = last.campaign_html
        final_diagnostics = last.render_diagnostics
        final_report = last.qa_report

    # Emit a human "Director" bubble at the start of a revision so the UI
    # shows the feedback turn alongside the agent turns. Also append a
    # DialogueMessage with role="human" so future revisions (or replay) see it.
    feedback_text = (human_feedback or "").strip() or None
    if feedback_text is not None:
        _pub(
            "agent_message_started",
            {"role": "human", "attempt": attempt_offset},
        )
        _pub(
            "agent_message_delta",
            {"role": "human", "attempt": attempt_offset, "text": feedback_text},
        )
        _pub(
            "agent_message_completed",
            {
                "role": "human",
                "attempt": attempt_offset,
                "chat_message": feedback_text,
            },
        )
        messages.append(
            DialogueMessage(
                role="human",
                content=feedback_text,
                attempt=attempt_offset,
            )
        )

    def fallback_html_for(attempt_idx: int) -> CampaignHtml:
        return fallback_generate_campaign_html(
            brief,
            page_research,
            brand_kit,
            selected_strategy,
            visual_concept,
            campaign_copy,
            campaign_image_asset,
            output_dir,
            "fixture",
            html_attempts,
            settings,
        ).model_copy(update={"attempt": attempt_idx})

    def _call_streaming(
        schema: type, view: list, role: str, attempt: int
    ) -> tuple[Any, bool]:
        """Use streaming when a bus + live gateway are available; else parse_messages.

        Returns (parsed, streamed) — streamed=True means token deltas were already
        published, so the caller should NOT emit a synthetic full-text delta.
        """
        if event_bus is None or not gateway.should_call_live:
            return gateway.parse_messages(schema, view), False

        def on_delta(text: str) -> None:
            event_bus.publish(
                "agent_message_delta",
                {"role": role, "attempt": attempt, "text": text},
            )

        parsed = gateway.stream_messages(schema, view, on_chat_delta=on_delta)
        return parsed, True

    for loop_index in range(max_attempts):
        attempt = attempt_offset + loop_index
        logger.info("Dialogue turn start: generator attempt={}", attempt)
        _pub("agent_message_started", {"role": "html_generator", "attempt": attempt})

        prior_screenshots = _last_screenshots(html_attempts)
        additional = _additional_generator_instructions(attempt, html_attempts)
        if feedback_text and loop_index == 0:
            director_block = (
                "Director instruction from the human reviewing the prior result. "
                "Treat this as the latest authoritative direction; where it "
                "conflicts with earlier QA feedback, follow the Director.\n"
                f"  > {feedback_text}\n"
            )
            additional = (
                director_block + "\n\n" + additional if additional else director_block
            )
        gen_user_content = build_generator_user_content(
            brief,
            page_research,
            brand_kit,
            selected_strategy,
            visual_concept,
            campaign_copy,
            campaign_image_asset,
            output_dir,
            prior_attempts=html_attempts,
            attempt=attempt,
            prior_screenshots=prior_screenshots,
            additional_instructions=additional,
        )
        generator_view.append({"role": "user", "content": gen_user_content})

        gen_turn_raw, gen_streamed = _call_streaming(
            HtmlGeneratorTurn, generator_view, "html_generator", attempt
        )
        used_fallback_html = gen_turn_raw is None or (
            not gen_turn_raw.html.strip() and attempt == 0
        )
        gen_turn = _ensure_generator_turn(
            gen_turn_raw,
            attempt=attempt,
            fallback_html=fallback_html_for,
        )
        generator_view.append(
            {
                "role": "assistant",
                "content": _generator_assistant_text(gen_turn),
            }
        )

        new_html_provided = bool(gen_turn.html.strip())
        if new_html_provided:
            if used_fallback_html:
                generation_mode = "fallback" if gateway.should_call_live else "fixture"
            else:
                generation_mode = "llm"
            campaign_html = CampaignHtml(
                html=gen_turn.html,
                css_summary=gen_turn.css_summary,
                layout=gen_turn.layout,
                generation_mode=generation_mode,
                attempt=attempt,
                rationale=gen_turn.rationale,
                repair_notes=_latest_repair_notes(html_attempts),
            )
        elif final_html is not None:
            # Generator chose to keep the prior HTML and continue chatting.
            campaign_html = final_html.model_copy(update={"attempt": attempt})
        else:
            # Very first turn must produce HTML; fall back to fixture.
            campaign_html = fallback_html_for(attempt)

        gen_chat_text = gen_turn.chat_message or (
            "Submitted updated HTML for review."
            if new_html_provided
            else "Continuing without regenerating HTML."
        )
        if gen_chat_text and not gen_streamed:
            _pub(
                "agent_message_delta",
                {
                    "role": "html_generator",
                    "attempt": attempt,
                    "text": gen_chat_text,
                },
            )
        _pub(
            "agent_message_completed",
            {
                "role": "html_generator",
                "attempt": attempt,
                "chat_message": gen_chat_text,
                "html_provided": new_html_provided,
                "questions_for_qa": list(gen_turn.questions_for_qa),
                "rationale": gen_turn.rationale,
            },
        )
        messages.append(
            DialogueMessage(
                role="html_generator",
                content=gen_chat_text,
                artifact_ref=f"html:attempt={attempt}",
                attempt=attempt,
            )
        )

        # Render only if HTML changed (or first turn). Otherwise reuse previous diagnostics.
        if new_html_provided or final_diagnostics is None:
            _pub("html_render_started", {"attempt": attempt})
            diagnostics = render_campaign_html(
                campaign_html.html,
                output_dir,
                attempt=attempt,
            )
            _pub(
                "html_render_completed",
                {
                    "attempt": attempt,
                    "html_path": diagnostics.html_path,
                    "desktop_screenshot": diagnostics.desktop_screenshot,
                    "mobile_screenshot": diagnostics.mobile_screenshot,
                    "error": diagnostics.error,
                },
            )
        else:
            diagnostics = final_diagnostics

        # Deterministic guard first.
        deterministic_report = evaluate_campaign(
            campaign_html,
            diagnostics.desktop_screenshot,
            diagnostics.mobile_screenshot,
            attempt,
            diagnostics=diagnostics,
            min_score=settings.html_min_score,
        )

        # Build the QA user content from the latest artifacts plus the Generator's message
        # so the QA agent literally sees what the Generator just said.
        qa_user_content = _build_qa_user_content(
            brief=brief,
            campaign_html=campaign_html,
            diagnostics=diagnostics,
            deterministic_report=deterministic_report,
            generator_turn=gen_turn,
            messages=messages,
        )
        qa_view.append({"role": "user", "content": qa_user_content})

        _pub("agent_message_started", {"role": "visual_qa", "attempt": attempt})
        qa_turn, qa_streamed = _run_qa_turn_streaming(
            gateway=gateway,
            qa_view=qa_view,
            deterministic_report=deterministic_report,
            mode=mode,
            settings=settings,
            event_bus=event_bus,
            attempt=attempt,
        )
        qa_view.append(
            {
                "role": "assistant",
                "content": _qa_assistant_text(qa_turn),
            }
        )

        report = qa_turn.report
        qa_chat_text = qa_turn.chat_message or (
            f"Approved attempt {attempt} with score {report.overall_score}."
            if report.approved
            else f"Found {len(report.issues)} issue(s); score {report.overall_score}."
        )
        if qa_chat_text and not qa_streamed:
            _pub(
                "agent_message_delta",
                {"role": "visual_qa", "attempt": attempt, "text": qa_chat_text},
            )
        _pub(
            "agent_message_completed",
            {
                "role": "visual_qa",
                "attempt": attempt,
                "chat_message": qa_chat_text,
                "answers_to_generator": list(qa_turn.answers_to_generator),
            },
        )
        _pub(
            "qa_report_completed",
            {"attempt": attempt, "report": report.model_dump(mode="json")},
        )
        repair_history.append(report)
        html_attempts.append(
            HtmlAttempt(
                attempt=attempt,
                campaign_html=campaign_html,
                render_diagnostics=diagnostics,
                qa_report=report,
            )
        )
        messages.append(
            DialogueMessage(
                role="visual_qa",
                content=qa_chat_text,
                artifact_ref=f"qa_report:attempt={attempt}",
                attempt=attempt,
            )
        )

        final_html = campaign_html
        final_diagnostics = diagnostics
        final_report = report

        logger.info(
            "Dialogue turn done attempt={} approved={} score={} issues={}",
            attempt,
            report.approved,
            report.overall_score,
            len(report.issues),
        )
        _pub(
            "dialogue_turn_completed",
            {
                "attempt": attempt,
                "approved": report.approved,
                "overall_score": report.overall_score,
                "issue_count": len(report.issues),
            },
        )

        if report.approved:
            break

    assert final_html is not None and final_diagnostics is not None and final_report is not None

    return DialogueResult(
        final_html=final_html,
        final_report=final_report,
        final_diagnostics=final_diagnostics,
        desktop_screenshot=final_diagnostics.desktop_screenshot,
        mobile_screenshot=final_diagnostics.mobile_screenshot,
        messages=messages,
        html_attempts=html_attempts,
        repair_history=repair_history,
    )


def _additional_generator_instructions(
    attempt: int,
    prior_attempts: list[HtmlAttempt],
) -> str:
    if attempt == 0 or not prior_attempts:
        return ""
    last = prior_attempts[-1]
    qa = last.qa_report
    if qa is None:
        return ""
    bullets: list[str] = []
    for issue in qa.issues:
        instruction = issue.regeneration_instruction or issue.recommended_fix
        bullets.append(f"- ({issue.severity}) {issue.problem} -> {instruction}")
    if not bullets:
        return ""
    return (
        "Continue the dialogue with the Visual QA Agent. The previous attempt was not approved. "
        "Prior QA critique to address (do not regress resolved issues):\n"
        + "\n".join(bullets)
        + "\nRespond with chat_message acknowledging or pushing back, and return updated html/css_summary/layout/rationale "
        "that fixes the listed issues. You may also include questions_for_qa if a critique is ambiguous."
    )


def _build_qa_user_content(
    *,
    brief: CampaignBrief,
    campaign_html: CampaignHtml,
    diagnostics: RenderDiagnostics,
    deterministic_report: QaReport,
    generator_turn: HtmlGeneratorTurn,
    messages: list[DialogueMessage],
) -> list[dict[str, str]]:
    payload: dict[str, Any] = {
        "brief": brief.model_dump(),
        "campaign_html": {
            "html": campaign_html.html,
            "layout": campaign_html.layout,
            "css_summary": campaign_html.css_summary,
            "rationale": campaign_html.rationale,
            "attempt": campaign_html.attempt,
        },
        "render_diagnostics": diagnostics.model_dump(),
        "deterministic_report": deterministic_report.model_dump(),
        "generator_turn": {
            "chat_message": generator_turn.chat_message,
            "questions_for_qa": generator_turn.questions_for_qa,
        },
        "dialogue_so_far": [m.model_dump() for m in messages[-8:]],
    }
    text = (
        json.dumps(payload, indent=2, ensure_ascii=False)
        + "\n\nVisual QA dialogue requirements:\n"
        "- Judge the rendered work as a senior visual design QA reviewer using the attached screenshots and diagnostics.\n"
        "- Return a complete QaReport for this attempt and a chat_message addressed to the Generator.\n"
        "- Cite specific evidence from screenshots/diagnostics; do not approve work that contradicts them.\n"
        "- If the Generator asked questions_for_qa, answer each one in answers_to_generator.\n"
        "- Make every issue's regeneration_instruction concrete and actionable for the next HTML attempt."
    )
    parts: list[dict[str, str]] = [{"type": "input_text", "text": text}]
    for path in (diagnostics.desktop_screenshot, diagnostics.mobile_screenshot):
        url = _safe_image_data_url(path)
        if url:
            parts.append({"type": "input_image", "image_url": url})
    return parts


def _run_qa_turn(
    *,
    gateway: OpenAIModelGateway,
    qa_view: list[dict[str, Any]],
    deterministic_report: QaReport,
    mode: RunMode,
    settings: Settings,
) -> VisualQaTurn:
    turn, _ = _run_qa_turn_streaming(
        gateway=gateway,
        qa_view=qa_view,
        deterministic_report=deterministic_report,
        mode=mode,
        settings=settings,
        event_bus=None,
        attempt=0,
    )
    return turn


def _run_qa_turn_streaming(
    *,
    gateway: OpenAIModelGateway,
    qa_view: list[dict[str, Any]],
    deterministic_report: QaReport,
    mode: RunMode,
    settings: Settings,
    event_bus: RunEventBus | None,
    attempt: int,
) -> tuple[VisualQaTurn, bool]:
    """Run the QA agent's LLM call. Returns (turn, streamed_chat_message)."""
    if not gateway.should_call_live or mode == "fixture":
        return _deterministic_qa_turn(deterministic_report), False

    if event_bus is not None:
        def on_delta(text: str) -> None:
            event_bus.publish(
                "agent_message_delta",
                {"role": "visual_qa", "attempt": attempt, "text": text},
            )
        live = gateway.stream_messages(VisualQaTurn, qa_view, on_chat_delta=on_delta)
        streamed = True
    else:
        live = gateway.parse_messages(VisualQaTurn, qa_view)
        streamed = False

    if live is None:
        return _deterministic_qa_turn(deterministic_report), False
    # If live QA produced an apparently-approved report despite deterministic
    # heuristics flagging issues, trust the deterministic floor.
    if live.report.approved and deterministic_report.issues:
        return (
            VisualQaTurn(
                chat_message=live.chat_message,
                report=deterministic_report,
                answers_to_generator=live.answers_to_generator,
            ),
            streamed,
        )
    return live, streamed


def _deterministic_qa_turn(report: QaReport) -> VisualQaTurn:
    if report.approved:
        message = f"Deterministic QA approved this attempt with score {report.overall_score}."
    else:
        problems = "; ".join(issue.problem for issue in report.issues[:3]) or "score below threshold"
        message = f"Deterministic QA found issues: {problems}."
    return VisualQaTurn(chat_message=message, report=report, answers_to_generator=[])


def _generator_assistant_text(turn: HtmlGeneratorTurn) -> str:
    return json.dumps(
        {
            "chat_message": turn.chat_message,
            "html": turn.html,
            "css_summary": turn.css_summary,
            "layout": turn.layout,
            "rationale": turn.rationale,
            "questions_for_qa": turn.questions_for_qa,
        },
        ensure_ascii=False,
    )


def _qa_assistant_text(turn: VisualQaTurn) -> str:
    return json.dumps(
        {
            "chat_message": turn.chat_message,
            "report": turn.report.model_dump(),
            "answers_to_generator": turn.answers_to_generator,
        },
        ensure_ascii=False,
    )


def _ensure_generator_turn(
    turn: HtmlGeneratorTurn | None,
    *,
    attempt: int,
    fallback_html: Callable[[int], CampaignHtml],
) -> HtmlGeneratorTurn:
    if turn is not None and (turn.html.strip() or attempt > 0):
        return turn
    fallback = fallback_html(attempt)
    return HtmlGeneratorTurn(
        chat_message=(
            "Live HTML generation unavailable; submitted deterministic fallback HTML for review."
        ),
        html=fallback.html,
        css_summary=fallback.css_summary,
        layout=fallback.layout,
        rationale=fallback.rationale,
        questions_for_qa=[],
    )


def _last_screenshots(prior_attempts: list[HtmlAttempt]) -> list[str]:
    if not prior_attempts:
        return []
    last = prior_attempts[-1].render_diagnostics
    if last is None:
        return []
    return [
        path
        for path in (last.desktop_screenshot, last.mobile_screenshot)
        if path
    ]


def _latest_repair_notes(prior_attempts: list[HtmlAttempt]) -> list[str]:
    if not prior_attempts or not prior_attempts[-1].qa_report:
        return []
    return [
        issue.regeneration_instruction or issue.recommended_fix
        for issue in prior_attempts[-1].qa_report.issues
        if issue.severity in {"high", "medium"}
    ]


def _safe_image_data_url(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    try:
        from adfoundry.image_assets import image_to_data_url

        return image_to_data_url(p)
    except Exception:
        return None
