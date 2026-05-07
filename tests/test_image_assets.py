from pathlib import Path
import sys
from types import SimpleNamespace

from PIL import Image

from adfoundry.fixtures import (
    fixture_brand_kit,
    fixture_page_research,
    fixture_strategy_options,
    fixture_visual_concept,
)
from adfoundry.image_assets import (
    build_campaign_image_asset,
    dedupe_and_score_images,
    extract_image_candidates_from_html,
    validate_image_file,
    generate_openai_campaign_image,
    prepare_image_edit_reference,
    write_images_api_response,
)
from adfoundry.models import CampaignBrief, PageImage, PageResearch
from adfoundry.settings import Settings


def test_image_scoring_prefers_large_hero_over_logo_and_tiny_assets() -> None:
    images = dedupe_and_score_images(
        [
            PageImage(url="https://example.com/logo.svg", alt="Brand logo", width=80, height=40),
            PageImage(url="https://example.com/pixel.png", alt="", width=1, height=1),
            PageImage(
                url="https://example.com/holiday-hero-shoe.jpg",
                alt="Hero product shoe",
                width=1600,
                height=900,
                role="hero",
            ),
        ]
    )

    assert images[0].url.endswith("holiday-hero-shoe.jpg")
    assert images[0].score > images[-1].score


def test_extracts_image_candidates_from_html_sources() -> None:
    html = """
    <html>
      <head>
        <meta property="og:image" content="/og-hero.jpg">
      </head>
      <body>
        <img src="/small-logo.svg" alt="logo" width="80" height="40">
        <img src="/product.jpg" srcset="/product-large.jpg 2x, /product-small.jpg 1x" alt="product shoe" width="1200" height="900">
        <div style="background-image: url('/background-hero.webp')"></div>
      </body>
    </html>
    """

    images = extract_image_candidates_from_html(
        html,
        "https://brand.example/landing",
        background_urls=["/browser-bg.jpg"],
    )
    urls = {image.url for image in images}

    assert "https://brand.example/og-hero.jpg" in urls
    assert "https://brand.example/product-large.jpg" in urls
    assert "https://brand.example/background-hero.webp" in urls
    assert "https://brand.example/browser-bg.jpg" in urls


def test_validate_image_file_accepts_real_image_and_rejects_invalid(tmp_path: Path) -> None:
    image_path = tmp_path / "hero.png"
    Image.new("RGB", (400, 300), "#111111").save(image_path)
    invalid_path = tmp_path / "not-image.png"
    invalid_path.write_text("not image data", encoding="utf-8")

    assert validate_image_file(image_path) == image_path
    try:
        validate_image_file(invalid_path)
    except Exception as exc:
        assert exc
    else:
        raise AssertionError("invalid image should fail validation")


def test_mock_openai_generation_writes_generated_asset(tmp_path: Path) -> None:
    brief = CampaignBrief()
    page = fixture_page_research(brief)
    brand = fixture_brand_kit(brief, page)
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[1])
    source = tmp_path / "source.png"
    Image.new("RGB", (500, 400), "#222222").save(source)
    page.image_assets = [
        PageImage(
            url="https://example.com/source.png",
            alt="hero product",
            width=500,
            height=400,
            role="hero",
            local_path=str(source),
        )
    ]

    def fake_generator(prompt, reference_paths, output_path, settings):
        Image.new("RGB", (1536, 1024), "#333333").save(output_path)
        return SimpleNamespace(image_path=output_path, revised_prompt="Revised seasonal prompt")

    settings = Settings(
        openai_api_key="test",
        enable_image_generation=True,
        image_max_references=1,
    )

    asset = build_campaign_image_asset(
        brief,
        page,
        brand,
        visual,
        tmp_path,
        "live",
        generator=fake_generator,
        settings=settings,
    )

    assert asset.generation_mode == "generated"
    assert asset.generated_image_path
    assert Path(asset.generated_image_path).exists()
    assert asset.revised_prompt == "Revised seasonal prompt"


def test_images_api_base64_response_is_decoded_to_file(tmp_path: Path) -> None:
    image_path = tmp_path / "generated.png"
    image_bytes = b"fake-png-bytes"
    response = SimpleNamespace(
        data=[
            SimpleNamespace(
                b64_json=__import__("base64").b64encode(image_bytes).decode("ascii"),
                revised_prompt="revised",
            )
        ]
    )

    revised_prompt = write_images_api_response(response, image_path)

    assert image_path.read_bytes() == image_bytes
    assert revised_prompt == "revised"


def test_generate_uses_configured_images_api_model(tmp_path: Path, monkeypatch) -> None:
    image_bytes = b"fake-image"
    calls = {}

    class FakeImages:
        def generate(self, **kwargs):
            calls["generate"] = kwargs
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=__import__("base64").b64encode(image_bytes).decode("ascii"),
                        revised_prompt=None,
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    settings = Settings(
        openai_api_key="avalai-key",
        openai_base_url="https://api.avalai.ir/v1",
        openai_image_model="gpt-image-1.5",
        image_size="1536x1024",
        image_quality="medium",
        image_format="png",
    )

    result = generate_openai_campaign_image(
        prompt="seasonal hero",
        reference_paths=[],
        output_path=tmp_path / "generated.png",
        settings=settings,
    )

    assert result.image_path.read_bytes() == image_bytes
    assert calls["client"]["base_url"] == "https://api.avalai.ir/v1"
    assert calls["generate"]["model"] == "gpt-image-1.5"
    assert calls["generate"]["response_format"] == "b64_json"


def test_edit_reference_is_normalized_to_square_png(tmp_path: Path) -> None:
    source = tmp_path / "source.jpg"
    prepared = tmp_path / "prepared.png"
    Image.new("RGB", (1440, 700), "#111111").save(source)

    result = prepare_image_edit_reference(source, prepared)

    assert result == prepared
    assert prepared.stat().st_size < 4 * 1024 * 1024
    with Image.open(prepared) as image:
        assert image.format == "PNG"
        assert image.size == (1024, 1024)


def test_generation_retries_without_references_when_edit_is_rejected(tmp_path: Path, monkeypatch) -> None:
    reference = tmp_path / "reference.jpg"
    output = tmp_path / "generated.png"
    Image.new("RGB", (1440, 700), "#222222").save(reference)
    image_bytes = b"fallback-generated-image"
    calls = {}

    class FakeImages:
        def edit(self, **kwargs):
            calls["edit"] = kwargs
            image_arg = kwargs["image"]
            first_image = image_arg[0] if isinstance(image_arg, list) else image_arg
            calls["edit_image_name"] = first_image.name
            raise ValueError("Unsupported or incomplete input image")

        def generate(self, **kwargs):
            calls["generate"] = kwargs
            return SimpleNamespace(
                data=[
                    SimpleNamespace(
                        b64_json=__import__("base64").b64encode(image_bytes).decode("ascii"),
                        revised_prompt="text-only revised prompt",
                    )
                ]
            )

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.images = FakeImages()

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    settings = Settings(
        openai_api_key="avalai-key",
        openai_base_url="https://api.avalai.ir/v1",
        openai_image_model="gpt-image-1.5",
    )

    result = generate_openai_campaign_image(
        prompt="seasonal hero",
        reference_paths=[reference],
        output_path=output,
        settings=settings,
    )

    assert output.read_bytes() == image_bytes
    assert result.revised_prompt == "text-only revised prompt"
    assert result.fallback_reason
    assert "Unsupported or incomplete input image" in result.fallback_reason
    assert calls["edit"]["model"] == "gpt-image-1.5"
    assert calls["edit_image_name"].endswith(".png")
    assert calls["generate"]["prompt"] == "seasonal hero"


def test_source_fallback_uses_downloaded_reference_when_generation_disabled(tmp_path: Path) -> None:
    brief = CampaignBrief()
    brand = fixture_brand_kit(brief, fixture_page_research(brief))
    visual = fixture_visual_concept(brief, fixture_strategy_options(brief)[1])
    local = tmp_path / "downloaded.png"
    Image.new("RGB", (500, 400), "#444444").save(local)
    page = PageResearch(
        final_url=brief.url,
        image_assets=[
            PageImage(
                url="https://example.com/downloaded.png",
                alt="hero product",
                width=500,
                height=400,
                role="hero",
                local_path=str(local),
            )
        ],
    )
    settings = Settings(enable_image_generation=False, image_max_references=1)

    asset = build_campaign_image_asset(
        brief,
        page,
        brand,
        visual,
        tmp_path,
        "live",
        settings=settings,
    )

    assert asset.generation_mode == "source_fallback"
    assert asset.hero_image_path == str(local)
