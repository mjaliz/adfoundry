from pathlib import Path

from adfoundry.browser import _chromium_launch_options, _image_fit_metrics
from adfoundry.settings import Settings


def test_chromium_launch_options_support_headed_demo_mode() -> None:
    settings = Settings(
        browser_headless=False,
        browser_slow_mo_ms=150,
        playwright_chromium_executable_path=Path("/tmp/chromium"),
    )

    options = _chromium_launch_options(settings)

    assert options == {
        "headless": False,
        "slow_mo": 150,
        "executable_path": Path("/tmp/chromium"),
    }


def test_chromium_launch_options_default_to_headless() -> None:
    settings = Settings(_env_file=None)

    options = _chromium_launch_options(settings)

    assert options["headless"] is True
    assert "slow_mo" not in options


def test_image_fit_metrics_flag_wide_banner_cropped_into_narrow_box() -> None:
    metrics = _image_fit_metrics(
        natural_width=3000,
        natural_height=675,
        box_width=777,
        box_height=960,
        object_fit="cover",
    )

    assert metrics["crop_risk"] is True
    assert metrics["visible_width_ratio"] < 0.25
    assert metrics["visible_height_ratio"] == 1.0


def test_image_fit_metrics_allow_contained_wide_banner() -> None:
    metrics = _image_fit_metrics(
        natural_width=3000,
        natural_height=675,
        box_width=777,
        box_height=960,
        object_fit="contain",
    )

    assert metrics["crop_risk"] is False
    assert metrics["visible_width_ratio"] == 1.0
    assert metrics["visible_height_ratio"] == 1.0
