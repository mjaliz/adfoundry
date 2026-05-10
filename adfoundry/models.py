from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl


RunMode = Literal["hybrid", "live", "fixture"]


class CampaignBrief(BaseModel):
    url: str = Field(default="https://www.nike.com", description="Landing page URL to inspect.")
    campaign_type: str = "Landing hero"
    goal: str = "Drive holiday gift purchases"
    theme: str = "Christmas"
    audience: str = "Holiday shoppers buying athletic gifts"
    tone: str = "Premium and energetic"
    offer: str = "Holiday gift edit"
    cta_preference: str = "Shop Gifts"


class PageImage(BaseModel):
    url: str
    alt: str = ""
    width: int | None = None
    height: int | None = None
    role: str = "asset"
    source: str = "html"
    score: int = 0
    local_path: str | None = None
    score_reason: str = ""


class PageResearch(BaseModel):
    final_url: str
    title: str = ""
    meta_description: str = ""
    headings: list[str] = Field(default_factory=list)
    buttons: list[str] = Field(default_factory=list)
    visible_text_sample: str = ""
    color_candidates: list[str] = Field(default_factory=list)
    logo_candidates: list[str] = Field(default_factory=list)
    image_assets: list[PageImage] = Field(default_factory=list)
    desktop_screenshot: str | None = None
    mobile_screenshot: str | None = None
    source: Literal["live", "fixture", "fallback"] = "fixture"
    notes: list[str] = Field(default_factory=list)


class ConfidenceScores(BaseModel):
    brand_name: float = 0.0
    logo: float = 0.0
    primary_color: float = 0.0
    tone_of_voice: float = 0.0
    product_category: float = 0.0


class BrandKit(BaseModel):
    brand_name: str
    industry: str
    primary_colors: list[str]
    accent_colors: list[str]
    logo_candidates: list[str]
    font_style: str
    tone_of_voice: str
    visual_style: str
    detected_products: list[str]
    brand_constraints: list[str]
    confidence: ConfidenceScores


class Scorecard(BaseModel):
    brand_fit: int = Field(ge=0, le=10)
    seasonal_relevance: int = Field(ge=0, le=10)
    conversion_potential: int = Field(ge=0, le=10)
    visual_distinctiveness: int = Field(ge=0, le=10)
    implementation_risk: int = Field(ge=0, le=10)

    @property
    def total(self) -> int:
        return (
            self.brand_fit
            + self.seasonal_relevance
            + self.conversion_potential
            + self.visual_distinctiveness
            + (10 - self.implementation_risk)
        )


class StrategyOption(BaseModel):
    name: str
    angle: str
    rationale: str
    target_emotion: str
    scorecard: Scorecard


class DecisionRecord(BaseModel):
    agent: str
    decision: str
    selected: str
    rejected: list[str] = Field(default_factory=list)
    reason: str
    score: int | None = None


class CampaignCopy(BaseModel):
    headline: str
    subheadline: str
    cta: str
    alternates: list[str] = Field(default_factory=list)
    rationale: str


class VisualConcept(BaseModel):
    concept_name: str
    image_direction: str
    layout_direction: str
    color_usage: str
    constraints: list[str]


class CampaignImageAsset(BaseModel):
    source_image_urls: list[str] = Field(default_factory=list)
    downloaded_image_paths: list[str] = Field(default_factory=list)
    reference_image_paths: list[str] = Field(default_factory=list)
    generation_prompt: str
    generated_image_path: str | None = None
    hero_image_path: str | None = None
    generation_mode: Literal["generated", "source_fallback", "fixture_fallback"]
    fallback_reason: str | None = None
    revised_prompt: str | None = None
    selected_images: list[PageImage] = Field(default_factory=list)


class CampaignHtml(BaseModel):
    html: str
    css_summary: str
    layout: str
    repair_notes: list[str] = Field(default_factory=list)
    generation_mode: Literal["llm", "fixture", "fallback"] = "fixture"
    attempt: int = 0
    rationale: str = ""


class QaIssue(BaseModel):
    severity: Literal["low", "medium", "high"]
    problem: str
    recommended_fix: str
    suspected_cause: str = ""
    regeneration_instruction: str = ""


class QaReport(BaseModel):
    approved: bool
    overall_score: int = Field(ge=0, le=100)
    visual_quality: int = Field(ge=0, le=10)
    brand_consistency: int = Field(ge=0, le=10)
    readability: int = Field(ge=0, le=10)
    cta_visibility: int = Field(ge=0, le=10)
    responsive_layout: int = Field(ge=0, le=10)
    accessibility: int = Field(ge=0, le=10)
    issues: list[QaIssue] = Field(default_factory=list)
    summary: str


class ElementBox(BaseModel):
    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    left: float = 0.0


class ViewportRenderDiagnostics(BaseModel):
    viewport: dict[str, int] = Field(default_factory=dict)
    screenshot_path: str | None = None
    hero_box: ElementBox | None = None
    copy_box: ElementBox | None = None
    image_box: ElementBox | None = None
    heading_box: ElementBox | None = None
    cta_box: ElementBox | None = None
    natural_image_width: int | None = None
    natural_image_height: int | None = None
    object_fit: str = ""
    object_position: str = ""
    image_visible_width_ratio: float | None = None
    image_visible_height_ratio: float | None = None
    image_crop_risk: bool = False
    horizontal_overflow: float = 0.0
    vertical_overflow: float = 0.0
    cta_above_fold: bool = True
    text_overflows: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class RenderDiagnostics(BaseModel):
    html_path: str
    desktop_screenshot: str
    mobile_screenshot: str
    desktop: ViewportRenderDiagnostics
    mobile: ViewportRenderDiagnostics
    error: str | None = None


class HtmlAttempt(BaseModel):
    attempt: int
    campaign_html: CampaignHtml
    render_diagnostics: RenderDiagnostics | None = None
    qa_report: QaReport | None = None


class AgentActivity(BaseModel):
    agent: str
    message: str
    artifact: str | None = None


class AgentTurn(BaseModel):
    node: str = ""
    agent: str = ""
    message: str = ""
    artifact: str | None = None
    attempt: int | None = None


class LoopDecision(BaseModel):
    node: str = "visual_qa"
    next_node: Literal["html_generate", "package", "dialogue"] = "package"
    should_repair: bool = False
    attempt: int = 0
    score: int = 0
    approved: bool = False
    min_score: int = 0
    html_max_attempts: int = 0
    max_repairs: int = 0
    reason: str = ""


class DialogueMessage(BaseModel):
    role: Literal["system", "html_generator", "visual_qa"]
    content: str
    artifact_ref: str | None = None
    attempt: int | None = None


class HtmlGeneratorTurn(BaseModel):
    chat_message: str
    html: str = ""
    css_summary: str = ""
    layout: str = ""
    rationale: str = ""
    questions_for_qa: list[str] = Field(default_factory=list)


class VisualQaTurn(BaseModel):
    chat_message: str
    report: QaReport
    answers_to_generator: list[str] = Field(default_factory=list)


class CampaignPackage(BaseModel):
    run_id: str
    created_at: datetime
    mode_used: RunMode
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
    repair_history: list[QaReport] = Field(default_factory=list)
    html_attempts: list[HtmlAttempt] = Field(default_factory=list)
    render_diagnostics: RenderDiagnostics | None = None
    activities: list[AgentActivity] = Field(default_factory=list)
    agent_turns: list[AgentTurn] = Field(default_factory=list)
    loop_decisions: list[LoopDecision] = Field(default_factory=list)
    dialogue_messages: list[DialogueMessage] = Field(default_factory=list)
    output_dir: str
    preview_html_path: str
    desktop_screenshot: str | None = None
    mobile_screenshot: str | None = None


def normalize_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def ensure_http_url(url: str) -> str:
    # Keep this as a lightweight validator for form input without forcing HttpUrl
    # into the public brief schema.
    return str(HttpUrl(normalize_url(url)))
