from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


_configured_key: tuple[str | None, str] | None = None


def configure_logging(
    *,
    output_dir: Path | None = None,
    run_id: str | None = None,
    level: str = "INFO",
) -> Path | None:
    """Configure Loguru once per run and optionally write a per-run log file."""

    global _configured_key
    key = (str(output_dir) if output_dir else None, level.upper())
    if _configured_key == key:
        return output_dir / "adfoundry.log" if output_dir else None

    logger.remove()
    logger.add(
        sys.stderr,
        level=level.upper(),
        colorize=True,
        format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    )

    log_path: Path | None = None
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        log_path = output_dir / "adfoundry.log"
        logger.add(
            log_path,
            level=level.upper(),
            rotation="2 MB",
            retention=5,
            enqueue=False,
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        )

    _configured_key = key
    logger.info(
        "Logging configured run_id={} level={} file={}",
        run_id or "-",
        level.upper(),
        str(log_path) if log_path else "-",
    )
    return log_path
