from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from adfoundry.fixtures import fixture_page_research
from adfoundry.image_assets import dedupe_and_score_images, extract_image_candidates_from_html
from adfoundry.models import (
    CampaignBrief,
    ElementBox,
    PageImage,
    PageResearch,
    RenderDiagnostics,
    RunMode,
    ViewportRenderDiagnostics,
    normalize_url,
)
from adfoundry.settings import Settings, get_settings


DESKTOP_VIEWPORT = {"width": 1440, "height": 960}
MOBILE_VIEWPORT = {"width": 390, "height": 844}


def research_page(brief: CampaignBrief, output_dir: Path, mode: RunMode) -> PageResearch:
    if mode == "fixture":
        page = fixture_page_research(brief)
        return _write_fixture_page_screenshots(page, output_dir)

    try:
        return _research_page_live(brief, output_dir)
    except Exception as exc:
        page = fixture_page_research(brief)
        page.source = "fallback"
        page.notes.append(f"Live browser research failed: {exc}")
        return _write_fixture_page_screenshots(page, output_dir)


def _research_page_live(brief: CampaignBrief, output_dir: Path) -> PageResearch:
    from playwright.sync_api import sync_playwright

    url = normalize_url(brief.url)
    desktop_path = output_dir / "source_desktop.png"
    mobile_path = output_dir / "source_mobile.png"
    settings = get_settings()
    timeout_ms = settings.browser_timeout_ms

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_launch_options(settings))
        page = browser.new_page(viewport=DESKTOP_VIEWPORT)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        _dismiss_common_overlays(page)
        page.wait_for_timeout(800)
        final_url = page.url
        html = page.content()
        page.screenshot(path=str(desktop_path), full_page=False)

        mobile = browser.new_page(viewport=MOBILE_VIEWPORT, is_mobile=True)
        mobile.goto(final_url, wait_until="domcontentloaded", timeout=timeout_ms)
        _dismiss_common_overlays(mobile)
        mobile.wait_for_timeout(500)
        mobile.screenshot(path=str(mobile_path), full_page=False)

        colors = page.evaluate(
            """
            () => {
              const colors = new Map();
              const props = ['color','backgroundColor','borderTopColor'];
              for (const el of Array.from(document.querySelectorAll('*')).slice(0, 900)) {
                const style = getComputedStyle(el);
                for (const prop of props) {
                  const value = style[prop];
                  if (value && value !== 'rgba(0, 0, 0, 0)' && value !== 'transparent') {
                    colors.set(value, (colors.get(value) || 0) + 1);
                  }
                }
              }
              return Array.from(colors.entries())
                .sort((a, b) => b[1] - a[1])
                .slice(0, 12)
                .map(([value]) => value);
            }
            """
        )
        visible_images = page.evaluate(
            """
            () => Array.from(document.images).slice(0, 80).map((img) => {
              const rect = img.getBoundingClientRect();
              return {
                url: img.currentSrc || img.src,
                alt: img.alt || "",
                width: img.naturalWidth || Math.round(rect.width),
                height: img.naturalHeight || Math.round(rect.height),
                role: rect.width > 500 || rect.height > 300 ? "hero" : "asset",
                source: "browser"
              };
            }).filter((img) => img.url)
            """
        )
        background_urls = page.evaluate(
            """
            () => {
              const urls = new Set();
              for (const el of Array.from(document.querySelectorAll('*')).slice(0, 900)) {
                const bg = getComputedStyle(el).backgroundImage;
                if (!bg || bg === 'none') continue;
                for (const match of bg.matchAll(/url\\(["']?(.*?)["']?\\)/g)) {
                  if (match[1] && !match[1].startsWith('data:')) urls.add(match[1]);
                }
              }
              return Array.from(urls).slice(0, 32);
            }
            """
        )
        browser.close()

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.string or "").strip() if soup.title else ""
    meta = soup.find("meta", attrs={"name": "description"})
    meta_description = meta.get("content", "").strip() if meta else ""
    headings = [tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2"])][:12]
    buttons = [
        tag.get_text(" ", strip=True)
        for tag in soup.find_all(["button", "a"])
        if tag.get_text(" ", strip=True)
    ][:16]
    text = " ".join(soup.get_text(" ", strip=True).split())[:1200]
    html_images = extract_image_candidates_from_html(html, final_url, background_urls)
    browser_images = [
        PageImage(
            url=item.get("url", ""),
            alt=item.get("alt", ""),
            width=_safe_int(item.get("width")),
            height=_safe_int(item.get("height")),
            role=item.get("role", "asset"),
            source=item.get("source", "browser"),
        )
        for item in visible_images
    ]
    images = dedupe_and_score_images([*html_images, *browser_images])
    logos = [
        img.url
        for img in images
        if "logo" in img.alt.lower() or "logo" in img.url.lower() or "swoosh" in img.url.lower()
    ][:5]

    return PageResearch(
        final_url=final_url,
        title=title,
        meta_description=meta_description,
        headings=headings,
        buttons=buttons,
        visible_text_sample=text,
        color_candidates=[_rgb_to_hex(color) for color in colors],
        logo_candidates=logos,
        image_assets=images[:8],
        desktop_screenshot=str(desktop_path),
        mobile_screenshot=str(mobile_path),
        source="live",
        notes=["Live Playwright research completed."],
    )


def _safe_int(value: object) -> int | None:
    try:
        return int(str(value))
    except Exception:
        return None


def _dismiss_common_overlays(page) -> None:
    labels = ["Accept", "Accept All", "I agree", "Got it", "Close", "No thanks"]
    for label in labels:
        try:
            button = page.get_by_role("button", name=label)
            if button.count() > 0:
                button.first.click(timeout=600)
        except Exception:
            continue


def _rgb_to_hex(value: str) -> str:
    if value.startswith("#"):
        return value
    if not value.startswith("rgb"):
        return value
    parts = value[value.find("(") + 1 : value.find(")")].split(",")[:3]
    try:
        return "#" + "".join(f"{int(float(part.strip())):02x}" for part in parts)
    except Exception:
        return value


def write_campaign_html(html: str, output_dir: Path) -> Path:
    path = output_dir / "index.html"
    path.write_text(html, encoding="utf-8")
    return path


def render_campaign_html(
    html: str,
    output_dir: Path,
    attempt: int | None = None,
) -> RenderDiagnostics:
    html_path = write_campaign_html(html, output_dir)
    suffix = f"_attempt_{attempt}" if attempt is not None else ""
    desktop_path = output_dir / f"campaign_desktop{suffix}.png"
    mobile_path = output_dir / f"campaign_mobile{suffix}.png"
    desktop_diagnostics = ViewportRenderDiagnostics(
        viewport=DESKTOP_VIEWPORT,
        screenshot_path=str(desktop_path),
    )
    mobile_diagnostics = ViewportRenderDiagnostics(
        viewport=MOBILE_VIEWPORT,
        screenshot_path=str(mobile_path),
    )
    error: str | None = None

    try:
        from playwright.sync_api import sync_playwright

        settings = get_settings()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**_chromium_launch_options(settings))
            desktop = browser.new_page(viewport=DESKTOP_VIEWPORT)
            desktop.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            desktop.screenshot(path=str(desktop_path), full_page=False)
            desktop_diagnostics = _collect_render_diagnostics(
                desktop, DESKTOP_VIEWPORT, str(desktop_path)
            )

            mobile = browser.new_page(viewport=MOBILE_VIEWPORT, is_mobile=True)
            mobile.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            mobile.screenshot(path=str(mobile_path), full_page=False)
            mobile_diagnostics = _collect_render_diagnostics(
                mobile, MOBILE_VIEWPORT, str(mobile_path)
            )
            browser.close()
    except Exception as exc:
        error = str(exc)
        _placeholder_screenshot(desktop_path, "Desktop preview fallback", str(exc), (1440, 960))
        _placeholder_screenshot(mobile_path, "Mobile preview fallback", str(exc), (390, 844))
        desktop_diagnostics.notes.append(f"Render fallback: {exc}")
        mobile_diagnostics.notes.append(f"Render fallback: {exc}")

    return RenderDiagnostics(
        html_path=str(html_path),
        desktop_screenshot=str(desktop_path),
        mobile_screenshot=str(mobile_path),
        desktop=desktop_diagnostics,
        mobile=mobile_diagnostics,
        error=error,
    )


def _collect_render_diagnostics(
    page,
    viewport: dict[str, int],
    screenshot_path: str,
) -> ViewportRenderDiagnostics:
    raw = page.evaluate(
        """
        () => {
          const box = (el) => {
            if (!el) return null;
            const rect = el.getBoundingClientRect();
            return {
              x: rect.x, y: rect.y, width: rect.width, height: rect.height,
              top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left
            };
          };
          const hero = document.querySelector('main, .hero, [role="main"]') || document.body;
          const copy = document.querySelector('.copy, [data-role="copy"], section') || null;
          const image = document.querySelector('.hero-img, main img, img') || null;
          const heading = document.querySelector('h1') || null;
          const cta = document.querySelector('a[href], button, [role="button"]') || null;
          const style = image ? getComputedStyle(image) : null;
          const textOverflows = Array.from(document.querySelectorAll('h1, h2, p, a, button'))
            .filter((el) => el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2)
            .map((el) => `${el.tagName.toLowerCase()}: ${el.textContent.trim().slice(0, 80)}`);
          return {
            viewport: { width: window.innerWidth, height: window.innerHeight },
            heroBox: box(hero),
            copyBox: box(copy),
            imageBox: box(image),
            headingBox: box(heading),
            ctaBox: box(cta),
            naturalImageWidth: image ? image.naturalWidth || null : null,
            naturalImageHeight: image ? image.naturalHeight || null : null,
            objectFit: style ? style.objectFit : "",
            objectPosition: style ? style.objectPosition : "",
            horizontalOverflow: Math.max(0, document.documentElement.scrollWidth - window.innerWidth),
            verticalOverflow: Math.max(0, document.documentElement.scrollHeight - window.innerHeight),
            ctaAboveFold: cta ? cta.getBoundingClientRect().bottom <= window.innerHeight : false,
            textOverflows
          };
        }
        """
    )
    image_box = _box_from_raw(raw.get("imageBox"))
    fit = _image_fit_metrics(
        raw.get("naturalImageWidth"),
        raw.get("naturalImageHeight"),
        image_box.width if image_box else None,
        image_box.height if image_box else None,
        raw.get("objectFit") or "",
    )
    return ViewportRenderDiagnostics(
        viewport=raw.get("viewport") or viewport,
        screenshot_path=screenshot_path,
        hero_box=_box_from_raw(raw.get("heroBox")),
        copy_box=_box_from_raw(raw.get("copyBox")),
        image_box=image_box,
        heading_box=_box_from_raw(raw.get("headingBox")),
        cta_box=_box_from_raw(raw.get("ctaBox")),
        natural_image_width=_safe_int(raw.get("naturalImageWidth")),
        natural_image_height=_safe_int(raw.get("naturalImageHeight")),
        object_fit=raw.get("objectFit") or "",
        object_position=raw.get("objectPosition") or "",
        image_visible_width_ratio=fit["visible_width_ratio"],
        image_visible_height_ratio=fit["visible_height_ratio"],
        image_crop_risk=fit["crop_risk"],
        horizontal_overflow=float(raw.get("horizontalOverflow") or 0),
        vertical_overflow=float(raw.get("verticalOverflow") or 0),
        cta_above_fold=bool(raw.get("ctaAboveFold")),
        text_overflows=list(raw.get("textOverflows") or []),
    )


def _box_from_raw(raw: dict[str, object] | None) -> ElementBox | None:
    if not raw:
        return None
    return ElementBox(**{key: float(raw.get(key) or 0) for key in ElementBox.model_fields})


def _image_fit_metrics(
    natural_width: int | str | None,
    natural_height: int | str | None,
    box_width: float | None,
    box_height: float | None,
    object_fit: str,
) -> dict[str, float | bool | None]:
    try:
        natural_w = float(natural_width or 0)
        natural_h = float(natural_height or 0)
        rendered_w = float(box_width or 0)
        rendered_h = float(box_height or 0)
    except (TypeError, ValueError):
        natural_w = natural_h = rendered_w = rendered_h = 0

    if min(natural_w, natural_h, rendered_w, rendered_h) <= 0:
        return {
            "visible_width_ratio": None,
            "visible_height_ratio": None,
            "crop_risk": False,
        }

    fit = object_fit.strip().lower()
    if fit in {"contain", "scale-down"}:
        return {
            "visible_width_ratio": 1.0,
            "visible_height_ratio": 1.0,
            "crop_risk": False,
        }

    if fit == "cover":
        scale = max(rendered_w / natural_w, rendered_h / natural_h)
        visible_w = min(1.0, rendered_w / scale / natural_w)
        visible_h = min(1.0, rendered_h / scale / natural_h)
    else:
        visible_w = min(1.0, rendered_w / natural_w)
        visible_h = min(1.0, rendered_h / natural_h)

    crop_risk = visible_w < 0.55 or visible_h < 0.65
    return {
        "visible_width_ratio": round(visible_w, 3),
        "visible_height_ratio": round(visible_h, 3),
        "crop_risk": crop_risk,
    }


def _chromium_launch_options(settings: Settings) -> dict[str, object]:
    options: dict[str, object] = {"headless": settings.browser_headless}
    if settings.browser_slow_mo_ms > 0:
        options["slow_mo"] = settings.browser_slow_mo_ms
    if settings.playwright_chromium_executable_path:
        options["executable_path"] = settings.playwright_chromium_executable_path
    return options


def _write_fixture_page_screenshots(page: PageResearch, output_dir: Path) -> PageResearch:
    desktop = output_dir / "source_desktop.png"
    mobile = output_dir / "source_mobile.png"
    _placeholder_screenshot(desktop, "Source research", "Nike-style campaign evidence", (1440, 960))
    _placeholder_screenshot(mobile, "Source research", "Mobile source evidence", (390, 844))
    page.desktop_screenshot = str(desktop)
    page.mobile_screenshot = str(mobile)
    return page


def _placeholder_screenshot(path: Path, title: str, subtitle: str, size: tuple[int, int]) -> None:
    image = Image.new("RGB", size, "#111111")
    draw = ImageDraw.Draw(image)
    accent = "#c89b3c"
    draw.rectangle((0, 0, size[0], size[1]), fill="#111111")
    draw.rectangle((int(size[0] * 0.58), 0, size[0], size[1]), fill="#202020")
    draw.ellipse(
        (
            int(size[0] * 0.64),
            int(size[1] * 0.18),
            int(size[0] * 1.04),
            int(size[1] * 0.78),
        ),
        fill="#2b2b2b",
        outline=accent,
        width=3,
    )
    draw.text((36, 48), title, fill="#ffffff")
    draw.text((36, 82), subtitle[:96], fill=accent)
    draw.text((36, size[1] - 74), "AdFoundry campaign preview", fill="#f5f5f5")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
