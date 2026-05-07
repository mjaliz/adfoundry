from __future__ import annotations

from pathlib import Path

from adfoundry.image_assets import image_to_data_url
from adfoundry.models import (
    BrandKit,
    CampaignBrief,
    CampaignCopy,
    CampaignHtml,
    CampaignImageAsset,
    ConfidenceScores,
    DecisionRecord,
    PageImage,
    PageResearch,
    QaIssue,
    QaReport,
    Scorecard,
    StrategyOption,
    VisualConcept,
)


def fixture_page_research(brief: CampaignBrief) -> PageResearch:
    return PageResearch(
        final_url=brief.url,
        title="Nike. Just Do It. Nike.com",
        meta_description="Shop Nike shoes, clothing, and gear for sport and lifestyle.",
        headings=[
            "Nike",
            "New Arrivals",
            "Shop Gifts",
            "Gear Up for the Season",
        ],
        buttons=["Shop", "Shop Gifts", "Explore"],
        visible_text_sample=(
            "Nike uses short, confident messaging, high contrast product imagery, "
            "and direct shopping calls to action."
        ),
        color_candidates=["#111111", "#ffffff", "#f5f5f5", "#c89b3c"],
        logo_candidates=["NIKE wordmark / swoosh candidate"],
        image_assets=[
            PageImage(
                url="fixture://nike-hero-product",
                alt="Athletic product hero with premium lighting",
                role="hero",
            )
        ],
        source="fixture",
        notes=[
            "Fixture fallback keeps the CEO demo reliable.",
            "Use live research when browser/network access is available.",
        ],
    )


def fixture_brand_kit(_: CampaignBrief, page: PageResearch) -> BrandKit:
    return BrandKit(
        brand_name="Nike",
        industry="Sportswear and athletic performance",
        primary_colors=["#111111", "#ffffff"],
        accent_colors=["#c89b3c", "#f5f5f5"],
        logo_candidates=page.logo_candidates,
        font_style="Bold, condensed, modern, high-impact sans serif",
        tone_of_voice="Motivational, concise, energetic, performance-led",
        visual_style="High contrast product photography, large type, dynamic motion cues",
        detected_products=["running shoes", "sportswear", "training gear"],
        brand_constraints=[
            "Keep copy short and confident.",
            "Use strong contrast and generous whitespace.",
            "Avoid cute or overly decorative holiday visuals.",
            "Keep campaign text editable in HTML.",
        ],
        confidence=ConfidenceScores(
            brand_name=0.98,
            logo=0.82,
            primary_color=0.86,
            tone_of_voice=0.78,
            product_category=0.92,
        ),
    )


def fixture_strategy_options(brief: CampaignBrief) -> list[StrategyOption]:
    return [
        StrategyOption(
            name="Safe",
            angle="Minimal premium gifting",
            rationale="Closest to the source brand: restrained, clean, and product-led.",
            target_emotion="Confidence",
            scorecard=Scorecard(
                brand_fit=9,
                seasonal_relevance=7,
                conversion_potential=8,
                visual_distinctiveness=6,
                implementation_risk=2,
            ),
        ),
        StrategyOption(
            name="Balanced",
            angle=f"{brief.theme} performance gifting",
            rationale=(
                "Combines seasonal buying intent with athletic movement, keeping the "
                "theme present without overpowering the brand."
            ),
            target_emotion="Motivation and aspiration",
            scorecard=Scorecard(
                brand_fit=9,
                seasonal_relevance=9,
                conversion_potential=9,
                visual_distinctiveness=8,
                implementation_risk=3,
            ),
        ),
        StrategyOption(
            name="Bold",
            angle="High-energy seasonal drop",
            rationale="More expressive and urgent, useful for a sale-led campaign.",
            target_emotion="Momentum",
            scorecard=Scorecard(
                brand_fit=7,
                seasonal_relevance=8,
                conversion_potential=8,
                visual_distinctiveness=9,
                implementation_risk=5,
            ),
        ),
    ]


def choose_strategy(options: list[StrategyOption]) -> StrategyOption:
    return max(options, key=lambda option: option.scorecard.total)


def fixture_decisions(
    brand_kit: BrandKit, options: list[StrategyOption], selected: StrategyOption
) -> list[DecisionRecord]:
    rejected = [option.angle for option in options if option.angle != selected.angle]
    return [
        DecisionRecord(
            agent="Brand Analyst",
            decision="Brand tone",
            selected=brand_kit.tone_of_voice,
            rejected=["Cozy", "Decorative", "Playful-first"],
            reason="The source brand uses direct language, high contrast, and performance imagery.",
            score=9,
        ),
        DecisionRecord(
            agent="Campaign Strategist",
            decision="Campaign angle",
            selected=selected.angle,
            rejected=rejected,
            reason="It balances seasonal intent, brand fit, and conversion potential.",
            score=selected.scorecard.total,
        ),
        DecisionRecord(
            agent="Brand Guardian",
            decision="Seasonal expression",
            selected="Subtle festive lighting and premium gift cues",
            rejected=["Cartoon holiday graphics", "Heavy red and green palette"],
            reason="Literal holiday decoration would weaken the premium athletic tone.",
            score=9,
        ),
    ]


def fixture_visual_concept(brief: CampaignBrief, selected: StrategyOption) -> VisualConcept:
    return VisualConcept(
        concept_name=selected.angle.title(),
        image_direction=(
            "Premium athletic product hero with dark stage lighting, subtle gold holiday "
            "glow, crisp product focus, and no text embedded in the image."
        ),
        layout_direction=(
            "Split hero: copy and CTA on the left, product-focused visual field on the right, "
            "with mobile stacking and CTA kept above the fold."
        ),
        color_usage=(
            "Use black and white as the base palette, gold as a restrained seasonal accent, "
            "and high-contrast CTA treatment."
        ),
        constraints=[
            f"Theme must read as {brief.theme} without becoming generic.",
            "Do not place headline or CTA inside generated imagery.",
            "Keep the campaign usable as responsive HTML.",
        ],
    )


def fixture_copy(brief: CampaignBrief) -> CampaignCopy:
    return CampaignCopy(
        headline="Give the Gift of Movement",
        subheadline="Performance-ready styles for every athlete on your list.",
        cta=brief.cta_preference or "Shop Gifts",
        alternates=[
            "Holiday Gear That Moves Fast",
            "For Every Athlete on Your List",
            "Performance Gifts, Made Easy",
        ],
        rationale="Short, seasonal, action-oriented copy fits a premium athletic brand.",
    )


def build_campaign_html(
    brief: CampaignBrief,
    brand_kit: BrandKit,
    visual: VisualConcept,
    copy: CampaignCopy,
    campaign_image_asset: CampaignImageAsset | None = None,
    repair_notes: list[str] | None = None,
) -> CampaignHtml:
    repair_notes = repair_notes or []
    primary = brand_kit.primary_colors[0]
    light = brand_kit.primary_colors[1]
    accent = brand_kit.accent_colors[0]
    extra_class = " repaired" if repair_notes else ""
    hero_image_url = _hero_image_url(campaign_image_asset)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{brand_kit.brand_name} Campaign Hero</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: {primary};
      color: {light};
      font-family: Inter, Arial, Helvetica, sans-serif;
    }}
    .hero {{
      min-height: 720px;
      display: grid;
      grid-template-columns: minmax(320px, 0.92fr) minmax(360px, 1.08fr);
      overflow: hidden;
      background:
        radial-gradient(circle at 82% 18%, rgba(200, 155, 60, 0.36), transparent 24rem),
        linear-gradient(135deg, #050505 0%, #111111 52%, #242424 100%);
    }}
    .copy {{
      padding: clamp(36px, 7vw, 96px);
      display: flex;
      flex-direction: column;
      justify-content: center;
      min-width: 0;
    }}
    .brand {{
      font-size: 0.86rem;
      font-weight: 800;
      letter-spacing: 0;
      text-transform: uppercase;
      margin-bottom: 28px;
    }}
    h1 {{
      max-width: 680px;
      margin: 0;
      font-size: clamp(3rem, 7vw, 6.8rem);
      line-height: 0.93;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    p {{
      max-width: 520px;
      margin: 28px 0 0;
      color: #eeeeee;
      font-size: clamp(1.05rem, 2vw, 1.38rem);
      line-height: 1.45;
    }}
    .cta {{
      width: fit-content;
      margin-top: 34px;
      padding: 15px 24px;
      border-radius: 999px;
      border: 0;
      background: {light};
      color: {primary};
      font-weight: 800;
      text-decoration: none;
      box-shadow: 0 16px 42px rgba(0, 0, 0, 0.28);
    }}
    .visual {{
      position: relative;
      min-height: 560px;
      overflow: hidden;
      background: #202020;
      isolation: isolate;
    }}
    .visual::after {{
      content: "";
      position: absolute;
      inset: 0;
      background:
        linear-gradient(90deg, rgba(17,17,17,0.82) 0%, rgba(17,17,17,0.18) 46%, rgba(17,17,17,0.56) 100%),
        radial-gradient(circle at 76% 20%, rgba(200,155,60,0.38), transparent 28rem);
      z-index: 1;
    }}
    .hero-img {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      object-fit: cover;
      object-position: center;
      transform: scale(1.02);
    }}
    .caption {{
      position: absolute;
      z-index: 2;
      right: clamp(24px, 5vw, 70px);
      bottom: clamp(28px, 5vw, 76px);
      padding: 10px 13px;
      color: {primary};
      background: {accent};
      font-size: 0.84rem;
      font-weight: 800;
      text-transform: uppercase;
    }}
    .repaired .copy {{
      padding-top: clamp(32px, 5vw, 72px);
    }}
    .repaired .cta {{
      margin-top: 28px;
    }}
    @media (max-width: 780px) {{
      .hero {{
        min-height: 100vh;
        grid-template-columns: 1fr;
      }}
      .copy {{
        padding: 32px 24px 22px;
        justify-content: end;
      }}
      .brand {{
        margin-bottom: 18px;
      }}
      h1 {{
        font-size: clamp(2.5rem, 15vw, 4.5rem);
      }}
      p {{
        margin-top: 18px;
        font-size: 1rem;
      }}
      .cta {{
        margin-top: 22px;
      }}
      .visual {{
        min-height: 300px;
        order: -1;
      }}
      .visual::after {{
        background:
          linear-gradient(180deg, rgba(17,17,17,0.20) 0%, rgba(17,17,17,0.72) 100%),
          radial-gradient(circle at 70% 18%, rgba(200,155,60,0.32), transparent 18rem);
      }}
      .caption {{
        right: 22px;
        bottom: 24px;
      }}
    }}
  </style>
</head>
<body>
  <main class="hero{extra_class}">
    <section class="copy" aria-label="{brief.theme} campaign message">
      <div class="brand">{brand_kit.brand_name}</div>
      <h1>{copy.headline}</h1>
      <p>{copy.subheadline}</p>
      <a class="cta" href="{brief.url}">{copy.cta}</a>
    </section>
    <section class="visual" aria-label="{visual.concept_name}">
      <img class="hero-img" src="{hero_image_url}" alt="{visual.image_direction}">
      <div class="caption">{brief.theme} edit</div>
    </section>
  </main>
</body>
</html>
"""
    return CampaignHtml(
        html=html,
        css_summary="Responsive split hero with black/white brand base and gold seasonal accent.",
        layout="Responsive split landing hero",
        repair_notes=repair_notes,
    )


def _hero_image_url(campaign_image_asset: CampaignImageAsset | None) -> str:
    if not campaign_image_asset or not campaign_image_asset.hero_image_path:
        return ""
    path = campaign_image_asset.hero_image_path
    if path.startswith(("http://", "https://", "data:")):
        return path
    local_path = Path(path.removeprefix("file://"))
    if local_path.exists():
        return image_to_data_url(local_path)
    return path


def fixture_initial_qa() -> QaReport:
    return QaReport(
        approved=False,
        overall_score=78,
        visual_quality=8,
        brand_consistency=9,
        readability=7,
        cta_visibility=7,
        responsive_layout=7,
        accessibility=8,
        summary="Strong campaign direction, but mobile CTA and headline spacing need improvement.",
        issues=[
            QaIssue(
                severity="high",
                problem="CTA may sit too low on smaller mobile screens.",
                recommended_fix="Move CTA closer to the headline and reduce vertical pressure in the hero.",
            ),
            QaIssue(
                severity="medium",
                problem="Hero visual competes with the headline on compact layouts.",
                recommended_fix="Stack visual first and tighten copy spacing on mobile.",
            ),
        ],
    )


def fixture_final_qa() -> QaReport:
    return QaReport(
        approved=True,
        overall_score=91,
        visual_quality=9,
        brand_consistency=9,
        readability=9,
        cta_visibility=9,
        responsive_layout=9,
        accessibility=9,
        summary="Approved after repair: CTA is visible, layout is balanced, and brand fit is strong.",
        issues=[],
    )
