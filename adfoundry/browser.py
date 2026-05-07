from __future__ import annotations

from pathlib import Path

from bs4 import BeautifulSoup
from PIL import Image, ImageDraw

from adfoundry.fixtures import fixture_page_research
from adfoundry.image_assets import dedupe_and_score_images, extract_image_candidates_from_html
from adfoundry.models import CampaignBrief, PageImage, PageResearch, RunMode, normalize_url
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


def render_campaign_html(html: str, output_dir: Path) -> tuple[str, str, str]:
    html_path = write_campaign_html(html, output_dir)
    desktop_path = output_dir / "campaign_desktop.png"
    mobile_path = output_dir / "campaign_mobile.png"

    try:
        from playwright.sync_api import sync_playwright

        settings = get_settings()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(**_chromium_launch_options(settings))
            desktop = browser.new_page(viewport=DESKTOP_VIEWPORT)
            desktop.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            desktop.screenshot(path=str(desktop_path), full_page=False)

            mobile = browser.new_page(viewport=MOBILE_VIEWPORT, is_mobile=True)
            mobile.goto(html_path.resolve().as_uri(), wait_until="networkidle")
            mobile.screenshot(path=str(mobile_path), full_page=False)
            browser.close()
    except Exception as exc:
        _placeholder_screenshot(desktop_path, "Desktop preview fallback", str(exc), (1440, 960))
        _placeholder_screenshot(mobile_path, "Mobile preview fallback", str(exc), (390, 844))

    return str(html_path), str(desktop_path), str(mobile_path)


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
    _placeholder_screenshot(desktop, "Source research fixture", "Nike-style campaign evidence", (1440, 960))
    _placeholder_screenshot(mobile, "Source research fixture", "Mobile source evidence", (390, 844))
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
    draw.text((36, size[1] - 74), "AdFoundry fixture-safe preview", fill="#f5f5f5")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
