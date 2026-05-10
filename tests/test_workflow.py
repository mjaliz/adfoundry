import json
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
from adfoundry.models import (
    AgentTurn,
    CampaignBrief,
    CampaignImageAsset,
    HtmlGeneratorTurn,
    LoopDecision,
    QaIssue,
    QaReport,
    VisualQaTurn,
)
from adfoundry.workflow import _polish_campaign_copy, run_campaign


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
    package_path = Path(package.output_dir, "campaign_package.json")
    assert package_path.exists()
    assert len(package.html_attempts) == 2
    assert package.render_diagnostics is not None

    expected_nodes = [
        "research",
        "brand",
        "strategy",
        "creative",
        "image_asset",
        "html_generate",
        "render",
        "visual_qa",
        "html_generate",
        "render",
        "visual_qa",
        "package",
    ]
    assert [turn.node for turn in package.agent_turns] == expected_nodes
    assert [
        turn.attempt
        for turn in package.agent_turns
        if turn.node in {"html_generate", "render", "visual_qa"}
    ] == [0, 0, 0, 1, 1, 1]
    assert [decision.next_node for decision in package.loop_decisions] == [
        "html_generate",
        "package",
    ]
    assert package.loop_decisions[0].should_repair is True
    assert package.loop_decisions[-1].should_repair is False

    package_json = json.loads(package_path.read_text())
    assert [turn["node"] for turn in package_json["agent_turns"]] == expected_nodes
    assert [decision["next_node"] for decision in package_json["loop_decisions"]] == [
        decision.next_node for decision in package.loop_decisions
    ]


def test_campaign_records_decisions_and_repair_history(tmp_path: Path) -> None:
    package = run_campaign(CampaignBrief(), mode="fixture", output_root=tmp_path)

    decision_agents = {decision.agent for decision in package.decisions}
    assert "Brand Analyst" in decision_agents
    assert "Campaign Strategist" in decision_agents
    assert "Brand Guardian" in decision_agents
    assert len(package.repair_history) == 2
    assert package.repair_history[0].approved is False
    assert package.repair_history[-1].approved is True
    assert package.html_attempts[0].qa_report is not None
    assert package.html_attempts[-1].campaign_html.repair_notes
    assert len(package.loop_decisions) == len(package.repair_history)
    assert package.loop_decisions[0].attempt == 0
    assert package.loop_decisions[-1].attempt == 1
    assert package.loop_decisions[0].next_node == "html_generate"
    assert package.loop_decisions[-1].next_node == "package"
    assert package.loop_decisions[-1].score == package.qa_report.overall_score


def test_trace_models_have_backward_compatible_defaults() -> None:
    assert AgentTurn().node == ""
    assert AgentTurn().attempt is None
    assert LoopDecision().node == "visual_qa"
    assert LoopDecision().next_node == "package"
    assert LoopDecision().should_repair is False


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


def test_campaign_html_uses_brand_color_as_integrated_treatment() -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[0])
    copy = fixture_copy(brief)

    campaign_html = build_campaign_html(brief, brand, visual, copy)

    assert "--brand-primary: #111111;" in campaign_html.html
    assert "min-height: max(720px, 100vh);" in campaign_html.html
    assert "body {\n      margin: 0;\n      background: #111111;" not in campaign_html.html
    assert "linear-gradient(90deg, var(--brand-accent), transparent)" in campaign_html.html


def test_generic_gift_edit_headline_is_polished() -> None:
    copy = fixture_copy(CampaignBrief())
    copy = copy.model_copy(
        update={
            "headline": "The Christmas Gift Edit",
            "alternates": [
                "Gift Beauty, Beautifully",
                "Holiday Beauty Gifts, Curated",
            ],
            "subheadline": "Premium beauty sets, fragrance, and skincare for holiday gifting.",
        }
    )

    polished = _polish_campaign_copy(CampaignBrief(), copy)

    assert polished.headline == "Gift Beauty, Beautifully"
    assert "The Christmas Gift Edit" in polished.alternates


def test_short_mood_gift_edit_headline_is_polished() -> None:
    brief = CampaignBrief(theme="Halloween")
    copy = fixture_copy(brief)
    copy = copy.model_copy(
        update={
            "headline": "The Midnight Gift Edit",
            "alternates": [],
            "subheadline": "After-dark picks for every athlete, including shoes and apparel.",
        }
    )

    polished = _polish_campaign_copy(brief, copy)

    assert polished.headline == "Give the Gift of Movement"
    assert "The Midnight Gift Edit" in polished.alternates


def test_dialogue_passes_qa_critique_into_generator_view(tmp_path: Path, monkeypatch) -> None:
    """Generator's second turn must see QA's prior chat_message + issues in its prompt."""
    from adfoundry.dialogue import run_html_qa_dialogue
    from adfoundry.image_assets import build_campaign_image_asset

    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    options = fixture_strategy_options(brief)
    visual = fixture_visual_concept(brief, options[0])
    copy = fixture_copy(brief)
    image_asset = build_campaign_image_asset(brief, page, brand, visual, tmp_path, "fixture")

    qa_chat_messages = [
        "First take: the headline overflows on mobile and the CTA is not visible above the fold.",
        "Approved on the second pass; the CTA is now in the first viewport.",
    ]
    gen_calls: list[list[dict]] = []
    qa_calls: list[list[dict]] = []
    gen_responses = [
        HtmlGeneratorTurn(
            chat_message="Submitting v1. I went with a tall hero on mobile.",
            html="<!doctype html><html><body><h1>v1</h1><a href='#'>Buy</a></body></html>",
            css_summary="v1",
            layout="hero/copy",
            rationale="Initial hero layout.",
            questions_for_qa=["Should the CTA be a button or anchor?"],
        ),
        HtmlGeneratorTurn(
            chat_message="Pulled the CTA above the fold and trimmed the headline as you asked.",
            html="<!doctype html><html><body><h1>v2</h1><a href='#'>Buy</a></body></html>",
            css_summary="v2",
            layout="hero/copy",
            rationale="Tightened first viewport.",
            questions_for_qa=[],
        ),
    ]
    qa_responses = [
        VisualQaTurn(
            chat_message=qa_chat_messages[0],
            answers_to_generator=["Anchor styled as a button is fine."],
            report=QaReport(
                approved=False,
                overall_score=72,
                visual_quality=7,
                brand_consistency=8,
                readability=6,
                cta_visibility=4,
                responsive_layout=6,
                accessibility=8,
                issues=[
                    QaIssue(
                        severity="high",
                        problem="Mobile CTA is below the fold.",
                        recommended_fix="Move the CTA into the first viewport.",
                        suspected_cause="Hero copy block is too tall.",
                        regeneration_instruction="Shrink the hero copy block so the CTA fits in the first 844px on mobile.",
                    )
                ],
                summary="CTA below fold on mobile.",
            ),
        ),
        VisualQaTurn(
            chat_message=qa_chat_messages[1],
            answers_to_generator=[],
            report=QaReport(
                approved=True,
                overall_score=92,
                visual_quality=9,
                brand_consistency=9,
                readability=9,
                cta_visibility=9,
                responsive_layout=9,
                accessibility=9,
                issues=[],
                summary="Approved on second attempt.",
            ),
        ),
    ]

    def fake_parse_messages(self, schema, messages):
        if schema is HtmlGeneratorTurn:
            gen_calls.append(messages)
            return gen_responses[len(gen_calls) - 1]
        if schema is VisualQaTurn:
            qa_calls.append(messages)
            return qa_responses[len(qa_calls) - 1]
        raise AssertionError(f"unexpected schema {schema}")

    monkeypatch.setattr(
        "adfoundry.dialogue.OpenAIModelGateway.parse_messages", fake_parse_messages
    )
    monkeypatch.setattr(
        "adfoundry.dialogue.OpenAIModelGateway.should_call_live",
        property(lambda self: True),
    )
    # Skip the real Playwright render; the test focuses on dialogue plumbing.
    from adfoundry.models import RenderDiagnostics, ViewportRenderDiagnostics

    def fake_render(html, output_dir, attempt=None):
        return RenderDiagnostics(
            html_path=str(output_dir / "index.html"),
            desktop_screenshot="",
            mobile_screenshot="",
            desktop=ViewportRenderDiagnostics(viewport={"width": 1440, "height": 960}),
            mobile=ViewportRenderDiagnostics(viewport={"width": 390, "height": 844}),
        )

    monkeypatch.setattr("adfoundry.dialogue.render_campaign_html", fake_render)
    # Bypass the deterministic-evaluator floor: this test exercises the live
    # dialogue plumbing, not the heuristic guard.
    monkeypatch.setattr(
        "adfoundry.dialogue.evaluate_campaign",
        lambda *args, **kwargs: QaReport(
            approved=False,
            overall_score=80,
            visual_quality=8,
            brand_consistency=8,
            readability=8,
            cta_visibility=8,
            responsive_layout=8,
            accessibility=8,
            issues=[],
            summary="stubbed",
        ),
    )
    monkeypatch.setattr(
        "adfoundry.dialogue.get_settings",
        lambda: __import__("adfoundry.settings", fromlist=["Settings"]).Settings(
            ADFOUNDRY_HTML_MAX_ATTEMPTS=2,
            ADFOUNDRY_HTML_MIN_SCORE=85,
        ),
    )

    result = run_html_qa_dialogue(
        brief=brief,
        page_research=page,
        brand_kit=brand,
        selected_strategy=options[0],
        visual_concept=visual,
        campaign_copy=copy,
        campaign_image_asset=image_asset,
        output_dir=tmp_path,
        mode="live",
    )

    # Two turns each, ended on approval
    assert len(gen_calls) == 2
    assert len(qa_calls) == 2
    assert result.final_report.approved is True
    assert len(result.html_attempts) == 2

    # Generator's second-turn prompt must contain QA's first critique. gen_calls[i]
    # holds a reference to the live generator_view list, so walk it for the most
    # recent user input_text part.
    second_gen_user_text = _latest_user_text(gen_calls[1])
    assert "Mobile CTA is below the fold." in second_gen_user_text

    # And QA's first prompt must include the Generator's chat_message
    qa_user_text = _latest_user_text(qa_calls[0])
    assert "I went with a tall hero on mobile" in qa_user_text

    # The shared transcript captures both sides
    roles = [m.role for m in result.messages]
    assert roles == ["html_generator", "visual_qa", "html_generator", "visual_qa"]


def test_dialogue_stops_at_turn_budget_when_qa_never_approves(tmp_path: Path, monkeypatch) -> None:
    from adfoundry.dialogue import run_html_qa_dialogue
    from adfoundry.image_assets import build_campaign_image_asset
    from adfoundry.models import RenderDiagnostics, ViewportRenderDiagnostics

    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    options = fixture_strategy_options(brief)
    visual = fixture_visual_concept(brief, options[0])
    copy = fixture_copy(brief)
    image_asset = build_campaign_image_asset(brief, page, brand, visual, tmp_path, "fixture")

    rejection = QaReport(
        approved=False,
        overall_score=60,
        visual_quality=5,
        brand_consistency=5,
        readability=5,
        cta_visibility=5,
        responsive_layout=5,
        accessibility=5,
        issues=[
            QaIssue(
                severity="high",
                problem="Still failing.",
                recommended_fix="Try again.",
                suspected_cause="cause",
                regeneration_instruction="redo it",
            )
        ],
        summary="Rejected.",
    )

    def fake_parse_messages(self, schema, messages):
        if schema is HtmlGeneratorTurn:
            return HtmlGeneratorTurn(
                chat_message="Trying.",
                html="<!doctype html><html><body><h1>x</h1></body></html>",
                css_summary="x",
                layout="x",
                rationale="x",
            )
        return VisualQaTurn(chat_message="Still failing.", report=rejection)

    monkeypatch.setattr(
        "adfoundry.dialogue.OpenAIModelGateway.parse_messages", fake_parse_messages
    )
    monkeypatch.setattr(
        "adfoundry.dialogue.OpenAIModelGateway.should_call_live",
        property(lambda self: True),
    )
    monkeypatch.setattr(
        "adfoundry.dialogue.render_campaign_html",
        lambda html, output_dir, attempt=None: RenderDiagnostics(
            html_path=str(output_dir / "index.html"),
            desktop_screenshot="",
            mobile_screenshot="",
            desktop=ViewportRenderDiagnostics(viewport={"width": 1440, "height": 960}),
            mobile=ViewportRenderDiagnostics(viewport={"width": 390, "height": 844}),
        ),
    )
    monkeypatch.setattr(
        "adfoundry.dialogue.get_settings",
        lambda: __import__("adfoundry.settings", fromlist=["Settings"]).Settings(
            ADFOUNDRY_HTML_MAX_ATTEMPTS=2,
            ADFOUNDRY_HTML_MIN_SCORE=85,
        ),
    )

    result = run_html_qa_dialogue(
        brief=brief,
        page_research=page,
        brand_kit=brand,
        selected_strategy=options[0],
        visual_concept=visual,
        campaign_copy=copy,
        campaign_image_asset=image_asset,
        output_dir=tmp_path,
        mode="live",
    )

    assert len(result.html_attempts) == 2
    assert result.final_report.approved is False


def _latest_user_text(messages: list[dict]) -> str:
    """Return the input_text content of the most recent user message in a Responses-API view."""
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "input_text":
                    return part.get("text", "")
    return ""
