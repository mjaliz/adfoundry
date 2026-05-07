from pathlib import Path

from adfoundry.browser import _chromium_launch_options
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
