from __future__ import annotations

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from app.tools.http import HttpScrapeArgs, HttpScrapeResult, HttpToolDeps, scrape_http

_SYSTEM_PROMPT = """\
You are Autumn, a web-scraping agent. The user gives you a single URL.
Call the `scrape` tool exactly once to fetch and extract that page, then
return a `MissionResult` with:
- `summary`: one paragraph describing what the page contains.
- `primary_url`: the final URL after redirects (use the URL the tool returned).
- `markdown_excerpt`: the first ~500 characters of the parsed markdown.

Do not call the tool more than once. If the tool fails, return a MissionResult
with `summary` describing the failure and an empty `markdown_excerpt`.
"""


class MissionResult(BaseModel):
    """Typed agent output. Validated by Pydantic AI on every run."""

    summary: str = Field(..., min_length=1, max_length=2000)
    primary_url: str = Field(..., max_length=2048)
    markdown_excerpt: str = Field(default="", max_length=600)


def build_agent() -> tuple[Agent[HttpToolDeps, MissionResult], list[HttpScrapeResult]]:
    """Construct a single-task agent. The returned `last_scrape` list is the
    closure into which the registered `scrape` tool appends each invocation —
    the runner reads `last_scrape[-1].markdown` to persist the full markdown
    (the typed output only carries a 500-char excerpt).
    """
    last_scrape: list[HttpScrapeResult] = []

    agent = Agent[HttpToolDeps, MissionResult](
        deps_type=HttpToolDeps,
        output_type=MissionResult,
        system_prompt=_SYSTEM_PROMPT,
        retries=2,
        defer_model_check=True,
    )

    @agent.tool
    async def scrape(ctx: RunContext[HttpToolDeps], url: str) -> HttpScrapeResult:
        result: HttpScrapeResult = await scrape_http(ctx.deps, HttpScrapeArgs(url=url))
        last_scrape.append(result)
        return result

    return agent, last_scrape
