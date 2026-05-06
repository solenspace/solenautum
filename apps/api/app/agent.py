"""Multi-tier scraping agent.

Three tools (`scrape_http`, `scrape_stealth`, `scrape_dynamic`)
register against one `Agent[MissionDeps, MissionResult]`. The agent
chooses escalation based on the `reason` of each tier's typed
`*Failure`, per the system prompt below. The runner reads
`mission_result.error_code` and the most recent successful tool result
(via `runner_helpers._last_ok_tool_call`) to write the SSE error event
and the `tasks` row.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.tools.dynamic import (
    DynamicDeps,
    DynamicScrapeArgs,
    DynamicScrapeResult,
    scrape_dynamic as scrape_dynamic_impl,
)
from app.tools.http import (
    HttpScrapeArgs,
    HttpScrapeResult,
    HttpToolDeps,
    scrape_http as scrape_http_impl,
)
from app.tools.stealth import (
    StealthDeps,
    StealthScrapeArgs,
    StealthScrapeResult,
    scrape_stealth as scrape_stealth_impl,
)

_SYSTEM_PROMPT = """\
You are Autumn, a web-scraping agent. The user gives you a URL.

Tool selection:
- Always start with `scrape_http`. It is the cheapest tier.
- If `scrape_http` returns reason=protected_cloudflare, retry with
  `scrape_stealth`.
- If `scrape_http` or `scrape_stealth` returns reason=javascript_required,
  retry with `scrape_dynamic`.
- If any tool returns reason=site_not_supported, return a MissionResult
  with status='error', error_code='site_not_supported', and the detected
  protections in detected_protections. Do not retry.
- If a tool returns reason=not_found, return MissionResult with
  status='error', error_code='not_found'.
- If a tool returns reason=upstream_error or render_timeout, return
  MissionResult with status='error' and the matching error_code.

On success: return MissionResult with status='ok', primary_url set
to the final URL, markdown_excerpt set to the first ~500 chars of
the markdown, and a one-paragraph summary in `summary`.

Call exactly one tool successfully per mission. After ok, do not call
more tools.
"""


class MissionResult(BaseModel):
    """Typed agent output. Validated by Pydantic AI on every run."""

    status: Literal["ok", "error"]
    summary: str = Field(..., min_length=1, max_length=2000)
    primary_url: str | None = Field(default=None, max_length=2048)
    markdown_excerpt: str | None = Field(default=None, max_length=600)
    error_code: (
        Literal[
            "site_not_supported",
            "upstream_error",
            "not_found",
            "render_timeout",
            "agent_failed",
        ]
        | None
    ) = None
    detected_protections: list[str] = Field(default_factory=list)


class MissionDeps(BaseModel):
    """Mission-scoped dependencies passed via Pydantic AI's `RunContext`.

    Each tier tool re-projects these into its own per-tool deps shape
    (`HttpToolDeps` / `StealthDeps` / `DynamicDeps`) so the tool
    surfaces remain self-contained for unit testing.
    """

    user_id: str
    mission_id: UUID
    task_id: UUID
    robots_override: bool = False


def build_agent() -> Agent[MissionDeps, MissionResult]:
    """Construct the multi-tier agent.

    The model is bound at run-time via `agent.run(url, model=model,
    deps=...)` so the LLM-fallback chain in `runner.py` can swap
    providers without rebuilding the agent.

    Deviates from the spec's `build_agent(model_factory)` signature
    (Spec 09 line 536) to preserve Spec 07's `defer_model_check`
    pattern. Equivalent semantics; avoids re-allocating the agent on
    each LLM-fallback attempt.
    """
    agent = Agent[MissionDeps, MissionResult](
        deps_type=MissionDeps,
        output_type=MissionResult,
        system_prompt=_SYSTEM_PROMPT,
        retries=2,
        defer_model_check=True,
    )

    @agent.tool
    async def scrape_http(ctx: RunContext[MissionDeps], url: str) -> HttpScrapeResult:
        """Fetch via HTTP. Cheapest tier; use first."""
        # The `@observe` decorator on the impl strips return-type info, so we
        # re-bind through an annotated local for mypy.
        result: HttpScrapeResult = await scrape_http_impl(
            HttpToolDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            HttpScrapeArgs(url=url),
        )
        return result

    @agent.tool
    async def scrape_stealth(ctx: RunContext[MissionDeps], url: str) -> StealthScrapeResult:
        """Fetch with the Cloudflare-bypass stealth browser. Use when
        HTTP returns reason=protected_cloudflare.
        """
        result: StealthScrapeResult = await scrape_stealth_impl(
            StealthDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            StealthScrapeArgs(url=url),
        )
        return result

    @agent.tool
    async def scrape_dynamic(
        ctx: RunContext[MissionDeps],
        url: str,
        wait_for_selector: str | None = None,
    ) -> DynamicScrapeResult:
        """Fetch with the full Playwright browser. Use when prior tiers
        returned reason=javascript_required.
        """
        result: DynamicScrapeResult = await scrape_dynamic_impl(
            DynamicDeps(
                user_id=ctx.deps.user_id,
                mission_id=ctx.deps.mission_id,
                task_id=ctx.deps.task_id,
                robots_override=ctx.deps.robots_override,
            ),
            DynamicScrapeArgs(url=url, wait_for_selector=wait_for_selector),
        )
        return result

    return agent
