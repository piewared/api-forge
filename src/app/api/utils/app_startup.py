import logging
import sys
from pathlib import Path
from typing import Any

from loguru import logger


def configure_logging() -> None:
    from src.app.runtime.context import get_config
    main_config = get_config()
    cfg = main_config.logging
    env = main_config.app.environment

    # 0) Reset Loguru and guarantee a default request_id
    logger.remove()
    logger.configure(extra={"request_id": "-"})

    # Ensure {extra[request_id]} always exists
    def _ensure_request_id(record: Any) -> None:
        record["extra"].setdefault("request_id", "-")

    log = logger.patch(_ensure_request_id)

    # 1) Formats
    fmt_plain = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "[<cyan>{extra[request_id]}</cyan>] | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    fmt_json_placeholder = "{message}"  # used only to satisfy type checkers
    is_json_file = cfg.format == "json"

    backtrace_on = env != "production"
    diagnose_on = env != "production"

    # 2) Loguru sinks
    # Console: always colorized, human-readable
    log.add(
        sys.stderr,
        level=cfg.level,
        format=fmt_plain,
        colorize=True,
        serialize=False,
        backtrace=backtrace_on,
        diagnose=diagnose_on,
        enqueue=False,
    )

    # File: JSON or plain
    if cfg.file:
        path = Path(cfg.file)
        path.parent.mkdir(parents=True, exist_ok=True)
        log.add(
            str(path),
            level=cfg.level,
            format=fmt_json_placeholder if is_json_file else fmt_plain,
            serialize=is_json_file,
            rotation=f"{cfg.max_size_mb} MB",
            retention=cfg.backup_count,
            compression="zip",
            enqueue=True,
            backtrace=backtrace_on,
            diagnose=diagnose_on,
        )

    # 3) Intercept stdlib logging and forward into Loguru
    class InterceptHandler(logging.Handler):
        """Redirect standard 'logging' records to Loguru, with selective drops."""

        def emit(self, record: logging.LogRecord) -> None:
            # Drop uvicorn access logs (your middleware handles request logs)
            if record.name == "uvicorn.access":
                return

            # If you *really* want to suppress uvicorn error tracebacks because
            # your middleware logs exceptions, keep the next two lines.
            # Comment them out if you want both.
            if record.name == "uvicorn.error" and record.levelno >= logging.ERROR:
                return

            try:
                level = logger.level(record.levelname).name
            except Exception:
                level = str(record.levelno) # fallback to numeric

            # Make Loguru show the original caller (not this handler)
            # depth=2 is usually correct from stdlib -> our handler -> user code
            logger.opt(
                depth=2,
                exception=record.exc_info,  # preserve traceback if present
            ).bind(
                logger_name=record.name  # keep original logger name if you want it in JSON
            ).log(level, record.getMessage())

    # 4) Replace stdlib handlers with our interceptor
    # 'force=True' clears existing handlers; level=0 lets all records through
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # Make all existing loggers propagate to root (where InterceptHandler sits)
    for name in list(logging.root.manager.loggerDict.keys()):
        stdlog = logging.getLogger(name)
        stdlog.handlers = []  # ensure no direct handlers remain (avoid duplicates)
        stdlog.propagate = True  # bubble up to root -> InterceptHandler

    # 5) Tune noise
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)

    # Uvicorn tuning:
    # - Base uvicorn logger (rare)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    # - Lifecycle logs (startup/shutdown/errors). Keep INFO so you see server messages.
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    # - Access logs (we're dropping them in InterceptHandler)
    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)

    # 6) Startup message (pass structured fields as kwargs, not extra={})
    log.info(
        "Logging configured",
        app_level=cfg.level,
        app_format=cfg.format,
        app_file=cfg.file,
        environment=env,
    )
