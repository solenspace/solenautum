"""Structured logging configuration.

`configure_logging` must run before FastAPI is constructed so the first
`structlog.get_logger()` call site picks up the configured renderer.
`mission_id` / `task_id` propagation across async chains is handled at
the call site via `structlog.contextvars.bound_contextvars` — see
`app/runner.py::_run_task`.
"""

from __future__ import annotations

import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: structlog.types.Processor
    if settings.log_format == "console":
        renderer = structlog.dev.ConsoleRenderer(colors=False)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.getLogger("uvicorn.access").disabled = True
