from __future__ import annotations

import base64
from contextlib import ExitStack
from io import BytesIO
import mimetypes
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from adfoundry.models import (
    BrandKit,
    CampaignBrief,
    CampaignImageAsset,
    PageImage,
    PageResearch,
    RunMode,
    VisualConcept,
)
from adfoundry.settings import Settings, get_settings


BACKGROUND_URL_RE = re.compile(r"url\((['\"]?)(.*?)\1\)")
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_EDIT_MAX_BYTES = 4 * 1024 * 1024
IMAGE_EDIT_REFERENCE_SIZE = 1024


@dataclass
class GeneratedImageResult:
    image_path: Path
    revised_prompt: str | None = None
    fallback_reason: str | None = None


def extract_image_candidates_from_html(
    html: str,
    final_url: str,
    background_urls: list[str] | None = None,
) -> list[PageImage]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[PageImage] = []

    for meta_selector in [
        {"property": "og:image"},
        {"property": "og:image:secure_url"},
        {"name": "twitter:image"},
    ]:
        for meta in soup.find_all("meta", attrs=meta_selector):
            content = meta.get("content")
            if content:
                candidates.append(
                    PageImage(
                        url=urljoin(final_url, content),
                        role="hero",
                        source="metadata",
                    )
                )

    for img in soup.find_all("img"):
        alt = img.get("alt", "")
        for src in _urls_from_srcset(img.get("srcset")):
            candidates.append(
                PageImage(
                    url=urljoin(final_url, src),
                    alt=alt,
                    width=_safe_int(img.get("width")),
                    height=_safe_int(img.get("height")),
                    role=_infer_role(src, alt),
                    source="srcset",
                )
            )
        src = img.get("src") or img.get("data-src") or img.get("data-original")
        if src:
            candidates.append(
                PageImage(
                    url=urljoin(final_url, src),
                    alt=alt,
                    width=_safe_int(img.get("width")),
                    height=_safe_int(img.get("height")),
                    role=_infer_role(src, alt),
                    source="img",
                )
            )

    for source in soup.find_all("source"):
        for src in _urls_from_srcset(source.get("srcset")):
            candidates.append(
                PageImage(
                    url=urljoin(final_url, src),
                    alt="",
                    role="asset",
                    source="picture",
                )
            )

    for tag in soup.find_all(style=True):
        for _, raw_url in BACKGROUND_URL_RE.findall(tag.get("style", "")):
            if raw_url and not raw_url.startswith("data:"):
                candidates.append(
                    PageImage(
                        url=urljoin(final_url, raw_url),
                        role="hero",
                        source="css",
                    )
                )

    for raw_url in background_urls or []:
        if raw_url and not raw_url.startswith("data:"):
            candidates.append(
                PageImage(
                    url=urljoin(final_url, raw_url),
                    role="hero",
                    source="css",
                )
            )

    return dedupe_and_score_images(candidates)


def dedupe_and_score_images(images: list[PageImage]) -> list[PageImage]:
    deduped: dict[str, PageImage] = {}
    for image in images:
        if not image.url or image.url.startswith("data:"):
            continue
        existing = deduped.get(image.url)
        scored = score_image_candidate(image)
        if existing is None or scored.score > existing.score:
            deduped[image.url] = scored
    return sorted(deduped.values(), key=lambda item: item.score, reverse=True)


def score_image_candidate(image: PageImage) -> PageImage:
    score = 20
    reasons: list[str] = []
    url_lower = image.url.lower()
    alt_lower = image.alt.lower()
    role_lower = image.role.lower()
    parsed = urlparse(image.url)
    ext = Path(parsed.path).suffix.lower()

    if role_lower in {"hero", "product"}:
        score += 30
        reasons.append("hero/product role")
    if any(term in alt_lower or term in url_lower for term in ["hero", "product", "shoe", "campaign", "model", "collection"]):
        score += 25
        reasons.append("brand visual keyword")
    if image.source in {"metadata", "css"}:
        score += 15
        reasons.append(f"{image.source} source")
    if image.width and image.height:
        area = image.width * image.height
        if area >= 900_000:
            score += 35
            reasons.append("large dimensions")
        elif area >= 250_000:
            score += 20
            reasons.append("medium dimensions")
        elif area < 20_000:
            score -= 45
            reasons.append("tiny asset")
    if ext in IMAGE_EXTENSIONS:
        score += 8
        reasons.append("raster image")
    if ext == ".svg":
        score -= 25
        reasons.append("svg/icon-like")
    if any(term in alt_lower or term in url_lower for term in ["logo", "icon", "sprite", "favicon", "tracking", "pixel"]):
        score -= 55
        reasons.append("logo/icon/tracking signal")
    if parsed.scheme not in {"http", "https", "file", "fixture"}:
        score -= 50
        reasons.append("unsupported scheme")

    return image.model_copy(
        update={
            "score": max(0, score),
            "score_reason": ", ".join(reasons) or "generic image candidate",
        }
    )


def build_campaign_image_asset(
    brief: CampaignBrief,
    page: PageResearch,
    brand: BrandKit,
    visual: VisualConcept,
    output_dir: Path,
    mode: RunMode,
    generator=None,
    settings: Settings | None = None,
) -> CampaignImageAsset:
    settings = settings or get_settings()
    scored_images = dedupe_and_score_images(page.image_assets)
    source_assets_dir = output_dir / "source_assets"
    downloaded = download_reference_images(
        scored_images,
        source_assets_dir,
        max_references=settings.image_max_references,
    )
    selected = downloaded[: settings.image_max_references]
    prompt = build_image_generation_prompt(brief, brand, visual, selected)
    source_urls = [image.url for image in scored_images]
    downloaded_paths = [image.local_path for image in downloaded if image.local_path]
    reference_paths = [image.local_path for image in selected if image.local_path]

    generated_path = output_dir / f"generated_hero.{settings.image_format}"
    if (
        settings.enable_image_generation
        and mode != "fixture"
        and settings.openai_api_key
    ):
        try:
            result = (generator or generate_openai_campaign_image)(
                prompt=prompt,
                reference_paths=[Path(path) for path in reference_paths],
                output_path=generated_path,
                settings=settings,
            )
            return CampaignImageAsset(
                source_image_urls=source_urls,
                downloaded_image_paths=downloaded_paths,
                reference_image_paths=reference_paths,
                generation_prompt=prompt,
                generated_image_path=str(result.image_path),
                hero_image_path=str(result.image_path),
                generation_mode="generated",
                fallback_reason=getattr(result, "fallback_reason", None),
                revised_prompt=result.revised_prompt,
                selected_images=selected,
            )
        except Exception as exc:
            fallback_reason = f"OpenAI image generation failed: {exc}"
    elif not settings.enable_image_generation:
        fallback_reason = "Image generation disabled by ADFOUNDRY_ENABLE_IMAGE_GENERATION."
    elif mode == "fixture":
        fallback_reason = "Fixture mode skips live image generation."
    else:
        fallback_reason = "OPENAI_API_KEY is not configured."

    if reference_paths:
        return CampaignImageAsset(
            source_image_urls=source_urls,
            downloaded_image_paths=downloaded_paths,
            reference_image_paths=reference_paths,
            generation_prompt=prompt,
            generated_image_path=None,
            hero_image_path=reference_paths[0],
            generation_mode="source_fallback",
            fallback_reason=fallback_reason,
            selected_images=selected,
        )

    fixture_path = create_fixture_hero_image(output_dir, brief, brand)
    return CampaignImageAsset(
        source_image_urls=source_urls,
        downloaded_image_paths=downloaded_paths,
        reference_image_paths=[],
        generation_prompt=prompt,
        generated_image_path=None,
        hero_image_path=str(fixture_path),
        generation_mode="fixture_fallback",
        fallback_reason=fallback_reason,
        selected_images=[],
    )


def build_image_generation_prompt(
    brief: CampaignBrief,
    brand: BrandKit,
    visual: VisualConcept,
    references: list[PageImage],
) -> str:
    image_direction = visual.image_direction.rstrip(".")
    reference_note = (
        "Use the provided reference images to preserve authentic brand style, product cues, materials, proportions, and composition language."
        if references
        else "No usable source reference images were available; generate a brand-consistent campaign hero from the brand kit and brief evidence."
    )
    return (
        f"Create or edit a premium landscape campaign hero image for {brand.brand_name}. "
        "Use polished commercial art direction suitable for a responsive landing-page hero. "
        f"Campaign occasion: {brief.theme}. Goal: {brief.goal}. Tone: {brief.tone}. "
        f"Brand style: {brand.visual_style}. Creative direction: {image_direction}. "
        f"{reference_note} Express the occasion subtly through mood, palette, styling, environment, or composition rather than literal repeated motifs. "
        "Keep a clean landscape composition with usable negative space for editable HTML headline copy and a CTA overlay. "
        "Do not include embedded headline text, CTA text, fake discounts, fake badges, fake endorsements, watermarks, unsupported claims, or logos not present in the references."
    )


def download_reference_images(
    images: list[PageImage],
    output_dir: Path,
    max_references: int,
) -> list[PageImage]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloaded: list[PageImage] = []
    for image in images:
        if len(downloaded) >= max_references:
            break
        if image.local_path:
            try:
                local_path = validate_image_file(Path(image.local_path))
                width, height = _image_dimensions(local_path)
                downloaded.append(
                    image.model_copy(
                        update={
                            "local_path": str(local_path),
                            "width": width,
                            "height": height,
                        }
                    )
                )
                continue
            except Exception:
                pass
        parsed = urlparse(image.url)
        if parsed.scheme not in {"http", "https"}:
            continue
        ext = Path(parsed.path).suffix.lower()
        if ext not in IMAGE_EXTENSIONS:
            ext = ".png"
        destination = output_dir / f"source_{len(downloaded) + 1}{ext}"
        try:
            local_path = download_public_image(image.url, destination)
            validated = validate_image_file(local_path)
            width, height = _image_dimensions(validated)
            downloaded.append(
                image.model_copy(
                    update={
                        "local_path": str(validated),
                        "width": width,
                        "height": height,
                    }
                )
            )
        except Exception:
            continue
    return downloaded


def download_public_image(url: str, destination: Path) -> Path:
    request = Request(url, headers={"User-Agent": "AdFoundry/0.1"})
    with urlopen(request, timeout=10) as response:
        content_type = response.headers.get("Content-Type", "")
        if content_type and not content_type.startswith("image/"):
            raise ValueError(f"Unsupported content type: {content_type}")
        destination.write_bytes(response.read(8_000_000))
    return validate_image_file(destination)


def validate_image_file(path: Path) -> Path:
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        image_format = (image.format or "").lower()
    if width < 160 or height < 160:
        raise ValueError("Image is too small for campaign use.")
    if (width * height) < 80_000:
        raise ValueError("Image area is too small for campaign use.")
    if image_format not in {"jpeg", "png", "webp"}:
        raise ValueError(f"Unsupported image format: {image_format}")
    return path


def _image_dimensions(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.width, image.height


def generate_openai_campaign_image(
    prompt: str,
    reference_paths: list[Path],
    output_path: Path,
    settings: Settings,
) -> GeneratedImageResult:
    """Generate or edit campaign imagery through the OpenAI-compatible Images API."""
    from openai import OpenAI

    client_kwargs: dict[str, object] = {
        "api_key": settings.openai_api_key,
        "timeout": settings.openai_timeout_seconds,
    }
    if settings.openai_base_url:
        client_kwargs["base_url"] = settings.openai_base_url
    client = OpenAI(**client_kwargs)

    if reference_paths:
        try:
            prepared_paths = prepare_image_edit_references(
                reference_paths,
                output_path.parent / "image_edit_references",
            )
            with ExitStack() as stack:
                files = [stack.enter_context(path.open("rb")) for path in prepared_paths]
                image_arg = files if len(files) > 1 else files[0]
                response = client.images.edit(
                    model=settings.openai_image_model,
                    image=image_arg,
                    prompt=prompt,
                    size=settings.image_size,
                    quality=settings.image_quality,
                    output_format=settings.image_format,
                    response_format="b64_json",
                )
            revised_prompt = write_images_api_response(response, output_path)
            return GeneratedImageResult(image_path=output_path, revised_prompt=revised_prompt)
        except Exception as exc:
            response = create_campaign_image_without_references(client, prompt, settings)
            revised_prompt = write_images_api_response(response, output_path)
            return GeneratedImageResult(
                image_path=output_path,
                revised_prompt=revised_prompt,
                fallback_reason=f"Reference image edit failed; generated without references: {exc}",
            )

    response = create_campaign_image_without_references(client, prompt, settings)
    revised_prompt = write_images_api_response(response, output_path)
    return GeneratedImageResult(image_path=output_path, revised_prompt=revised_prompt)


def create_campaign_image_without_references(client, prompt: str, settings: Settings):
    return client.images.generate(
        model=settings.openai_image_model,
        prompt=prompt,
        size=settings.image_size,
        quality=settings.image_quality,
        output_format=settings.image_format,
        response_format="b64_json",
    )


def prepare_image_edit_references(reference_paths: list[Path], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    prepared: list[Path] = []
    for index, path in enumerate(reference_paths, start=1):
        prepared.append(
            prepare_image_edit_reference(path, output_dir / f"reference_{index}.png")
        )
    return prepared


def prepare_image_edit_reference(source_path: Path, output_path: Path) -> Path:
    with Image.open(source_path) as image:
        image.thumbnail(
            (IMAGE_EDIT_REFERENCE_SIZE, IMAGE_EDIT_REFERENCE_SIZE),
            Image.Resampling.LANCZOS,
        )
        canvas = Image.new(
            "RGB",
            (IMAGE_EDIT_REFERENCE_SIZE, IMAGE_EDIT_REFERENCE_SIZE),
            "#ffffff",
        )
        if image.mode in {"RGBA", "LA"}:
            alpha = image.getchannel("A")
            paste_image = image.convert("RGBA")
            x = (IMAGE_EDIT_REFERENCE_SIZE - paste_image.width) // 2
            y = (IMAGE_EDIT_REFERENCE_SIZE - paste_image.height) // 2
            canvas.paste(paste_image.convert("RGB"), (x, y), alpha)
        else:
            paste_image = image.convert("RGB")
            x = (IMAGE_EDIT_REFERENCE_SIZE - paste_image.width) // 2
            y = (IMAGE_EDIT_REFERENCE_SIZE - paste_image.height) // 2
            canvas.paste(paste_image, (x, y))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    if output_path.stat().st_size > IMAGE_EDIT_MAX_BYTES:
        buffer = BytesIO()
        canvas.resize((768, 768), Image.Resampling.LANCZOS).save(
            buffer,
            format="PNG",
            optimize=True,
        )
        output_path.write_bytes(buffer.getvalue())
    return validate_image_file(output_path)


def write_images_api_response(response, output_path: Path) -> str | None:
    for item in getattr(response, "data", []) or []:
        image_base64 = getattr(item, "b64_json", None)
        if image_base64:
            output_path.write_bytes(base64.b64decode(image_base64))
            return getattr(item, "revised_prompt", None)
    raise ValueError("Images API response did not include b64_json image data.")


def image_to_data_url(path: Path) -> str:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime_type};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def create_fixture_hero_image(output_dir: Path, brief: CampaignBrief, brand: BrandKit) -> Path:
    path = output_dir / "fixture_hero.png"
    image = Image.new("RGB", (1536, 1024), brand.primary_colors[0])
    draw = ImageDraw.Draw(image)
    accent = brand.accent_colors[0] if brand.accent_colors else "#c89b3c"
    draw.rectangle((0, 0, 1536, 1024), fill="#111111")
    draw.ellipse((820, 120, 1480, 790), fill="#242424", outline=accent, width=8)
    draw.polygon([(720, 650), (1320, 450), (1410, 560), (820, 790)], fill="#eeeeee")
    draw.polygon([(760, 650), (1220, 505), (1260, 555), (820, 710)], fill="#6b6b6b")
    draw.text((70, 70), f"{brand.brand_name} campaign visual", fill="#ffffff")
    draw.text((70, 112), "Curated brand-safe hero composition.", fill=accent)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    return path


def _urls_from_srcset(srcset: str | None) -> list[str]:
    if not srcset:
        return []
    urls: list[str] = []
    for part in srcset.split(","):
        value = part.strip().split(" ")[0]
        if value:
            urls.append(value)
    return urls


def _infer_role(url: str, alt: str) -> str:
    value = f"{url} {alt}".lower()
    if "logo" in value:
        return "logo"
    if any(term in value for term in ["hero", "product", "shoe", "collection", "campaign"]):
        return "hero"
    return "asset"


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except Exception:
        return None
