from __future__ import annotations

from dataclasses import dataclass

from crawl4ai import (
    AsyncWebCrawler,
    CacheMode,
    CrawlerRunConfig,
    DefaultMarkdownGenerator,
)
from crawl4ai.async_crawler_strategy import AsyncHTTPCrawlerStrategy


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    markdown: str
    raw_html: bytes
    final_url: str


class MarkdownExtractor:
    """Crawl4AI in markdown-only mode. Scrapling has already handled the
    network fetch + UA rotation (it returns a decoded `str`), so we feed the
    body through the `raw://` URL scheme and `AsyncHTTPCrawlerStrategy` — no
    Playwright spawn, no second LLM call.
    """

    async def extract(self, *, html: str, source_url: str) -> ExtractedPage:
        run = CrawlerRunConfig(
            markdown_generator=DefaultMarkdownGenerator(),
            cache_mode=CacheMode.BYPASS,
            base_url=source_url,
        )
        async with AsyncWebCrawler(crawler_strategy=AsyncHTTPCrawlerStrategy()) as crawler:
            container = await crawler.arun(url=f"raw://{html}", config=run)
        result = container[0] if hasattr(container, "__getitem__") else container
        markdown = ""
        if result.markdown is not None:
            markdown = result.markdown.raw_markdown or ""
        # Scrapling already decoded the wire bytes into `str`; we re-encode to
        # UTF-8 so downstream R2 snapshot uploads (Spec 09/10) get a uniform
        # bytes type regardless of source charset. `str.encode("utf-8")` is
        # lossless — Python `str` is unicode and round-trips through UTF-8.
        return ExtractedPage(
            markdown=markdown,
            raw_html=html.encode("utf-8"),
            final_url=source_url,
        )
