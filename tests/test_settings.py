from pathlib import Path

from adfoundry.settings import Settings


def test_settings_loads_openai_base_url_from_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=test-key",
                "OPENAI_BASE_URL=https://api.example.test/v1",
                "OPENAI_MODEL=gpt-test",
                "OPENAI_IMAGE_MODEL=gpt-image-test",
                "ADFOUNDRY_RUN_MODE=fixture",
                "ADFOUNDRY_OUTPUT_ROOT=demo-outputs",
                "ADFOUNDRY_BROWSER_TIMEOUT_MS=9000",
                "ADFOUNDRY_BROWSER_HEADLESS=false",
                "ADFOUNDRY_BROWSER_SLOW_MO_MS=150",
                "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/tmp/chromium",
                "ADFOUNDRY_ENABLE_IMAGE_GENERATION=false",
                "ADFOUNDRY_IMAGE_SIZE=1024x1024",
                "ADFOUNDRY_IMAGE_QUALITY=low",
                "ADFOUNDRY_IMAGE_FORMAT=webp",
                "ADFOUNDRY_IMAGE_MAX_REFERENCES=2",
                "ADFOUNDRY_LOG_LEVEL=DEBUG",
            ]
        ),
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.openai_api_key == "test-key"
    assert settings.openai_base_url == "https://api.example.test/v1"
    assert settings.openai_model == "gpt-test"
    assert settings.openai_image_model == "gpt-image-test"
    assert settings.default_run_mode == "fixture"
    assert settings.output_root == Path("demo-outputs")
    assert settings.browser_timeout_ms == 9000
    assert settings.browser_headless is False
    assert settings.browser_slow_mo_ms == 150
    assert settings.playwright_chromium_executable_path == Path("/tmp/chromium")
    assert settings.enable_image_generation is False
    assert settings.image_size == "1024x1024"
    assert settings.image_quality == "low"
    assert settings.image_format == "webp"
    assert settings.image_max_references == 2
    assert settings.log_level == "DEBUG"


def test_settings_supports_opeai_base_url_typo_alias(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPEAI_BASE_URL=https://typo.example.test/v1\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.openai_base_url == "https://typo.example.test/v1"


def test_settings_expands_manual_chromium_path(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=~/home\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.playwright_chromium_executable_path == Path.home() / "home"
