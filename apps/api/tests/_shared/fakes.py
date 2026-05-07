"""Shared test doubles for the agent pipeline.

Lives under `tests/_shared/` (leading underscore so pytest does not collect
it as a test module). Used by the integration suite; the existing
per-file unit-test copies (`tests/test_run_mission_route.py`,
`tests/test_description_runner.py`) predate this module and are left
in place to keep the Spec 15 diff surgical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.messages import ModelRequest, ToolReturnPart

from app.agent import DiscoveryDeps, DiscoveryMissionResult, MissionDeps, MissionResult
from app.tools.http import HttpScrapeArgs, HttpScrapeOk, HttpToolDeps


@dataclass
class FakeAgentResult:
    output: Any
    messages: list[ModelRequest] = field(default_factory=list)

    def all_messages(self) -> list[ModelRequest]:
        return self.messages


def make_http_scrape_stub(*, markdown: str, key_template: str) -> Any:
    """Returns an async callable suitable for monkeypatching
    `app.tools.http.scrape_http`. Produces a deterministic `HttpScrapeOk`
    keyed by the deps' user/mission/task ids so the snapshot key matches
    the production shape.
    """

    async def _stub(deps: HttpToolDeps, args: HttpScrapeArgs) -> HttpScrapeOk:
        return HttpScrapeOk(
            url=args.url,
            markdown=markdown,
            snapshot_key=key_template.format(
                user_id=deps.user_id,
                mission_id=deps.mission_id,
                task_id=deps.task_id,
            ),
            snapshot_truncated=False,
            latency_ms=11,
        )

    return _stub


class FakeScrapeAgent:
    """Stub Pydantic AI `Agent` for URL-mode missions. Calls the stubbed
    `scrape_http` once and packages the result so `last_ok_tool_call`
    recovers the same fields it would in production.
    """

    async def run(self, url: str, *, model: Any, deps: MissionDeps) -> FakeAgentResult:
        from app.tools import http as http_tool

        http_deps = HttpToolDeps(
            user_id=deps.user_id,
            mission_id=deps.mission_id,
            task_id=deps.task_id,
            robots_override=deps.robots_override,
        )
        tool_result = await http_tool.scrape_http(http_deps, HttpScrapeArgs(url=url))
        message = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="scrape_http",
                    content=tool_result,
                    tool_call_id="call_1",
                ),
            ],
        )
        return FakeAgentResult(
            output=MissionResult(
                status="ok",
                summary="Fixture page parsed.",
                primary_url=tool_result.url if tool_result.status == "ok" else url,
                markdown_excerpt=(tool_result.markdown[:500] if tool_result.status == "ok" else ""),
            ),
            messages=[message],
        )


@dataclass
class FakeDiscoveryAgent:
    result: DiscoveryMissionResult

    async def run(self, prompt: str, *, model: Any, deps: DiscoveryDeps) -> FakeAgentResult:
        return FakeAgentResult(output=self.result)


class FakeChain:
    """Replaces `LLMProviderChain` so tests do not depend on
    `OPENROUTER_API_KEY` / `GROQ_API_KEY`. Runs the callable with a
    sentinel model object.
    """

    async def with_fallback(self, run: Any) -> Any:
        return await run(object())
