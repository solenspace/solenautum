import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { InlineErrorChip } from "./inline-error-chip";

describe("InlineErrorChip", () => {
  it("renders site_not_supported with interpolated protections", () => {
    render(
      <I18nTestWrapper>
        <InlineErrorChip
          code="site_not_supported"
          message="fallback should not show"
          detectedProtections={["akamai"]}
        />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(/This site uses akamai\./)).toBeDefined();
  });

  it("falls back to a generic protections phrase when none detected", () => {
    render(
      <I18nTestWrapper>
        <InlineErrorChip code="site_not_supported" message="fallback should not show" />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(/This site uses an enterprise WAF\./)).toBeDefined();
  });

  it.each([
    ["not_found", "Page not found at this URL."],
    ["render_timeout", "Page took too long to render."],
    ["upstream_error", "Upstream returned an error."],
  ])("renders the %s chip with the matching i18n copy", (code, expected) => {
    render(
      <I18nTestWrapper>
        <InlineErrorChip code={code} message="ignored" />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(expected)).toBeDefined();
  });

  it("falls back to the message for unrecognised codes", () => {
    // Unrecognised codes flow through the `errorGeneric` template
    // (`Scrape failed. {message}`) with the upstream message
    // truncated to a single line so a multi-line stack trace cannot
    // overrun the lane log.
    render(
      <I18nTestWrapper>
        <InlineErrorChip code="ssrf_blocked" message="blocked by SSRF guard" />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("Scrape failed. blocked by SSRF guard")).toBeDefined();
  });
});
