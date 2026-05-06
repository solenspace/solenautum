import type { SseError, TaskEnd } from "@autumn/sse-protocol";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { ResultPreview } from "./result-preview";

function _error(content: SseError["content"], seq = 0): SseError {
  return {
    type: "error",
    content,
    mission_id: "m1",
    task_id: "t1",
    seq,
  } as SseError;
}

function _taskEnd(preview: string): TaskEnd {
  return {
    type: "task_end",
    content: { status: "succeeded", preview },
    mission_id: "m1",
    task_id: "t1",
    seq: 1,
  } as TaskEnd;
}

describe("ResultPreview", () => {
  it("renders nothing when no taskEnd and no errors", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={null} />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the task_end preview when taskEnd is present", () => {
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={_taskEnd("hello world")} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("hello world")).toBeDefined();
  });

  it("renders site_not_supported chip with interpolated protections", () => {
    const error = _error({
      code: "site_not_supported",
      message: "fallback should not show",
      detected_protections: ["akamai"],
    });
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={null} errors={[error]} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(/This site uses akamai\./)).toBeDefined();
  });

  it("falls back to a generic protections phrase when none detected", () => {
    const error = _error({
      code: "site_not_supported",
      message: "fallback should not show",
    });
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={null} errors={[error]} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(/This site uses an enterprise WAF\./)).toBeDefined();
  });

  it.each([
    ["not_found", "Page not found at this URL."],
    ["render_timeout", "Page took too long to render."],
    ["upstream_error", "Upstream returned an error."],
  ])("renders the %s chip with the matching i18n copy", (code, expected) => {
    const error = _error({ code, message: "ignored" });
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={null} errors={[error]} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(expected)).toBeDefined();
  });

  it("falls back to error.content.message for unrecognized codes", () => {
    const error = _error({
      code: "ssrf_blocked",
      message: "blocked by SSRF guard",
    });
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={null} errors={[error]} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("blocked by SSRF guard")).toBeDefined();
  });

  it("renders both error chip and preview when both are present", () => {
    const error = _error({
      code: "upstream_error",
      message: "ignored",
    });
    render(
      <I18nTestWrapper>
        <ResultPreview taskEnd={_taskEnd("page body")} errors={[error]} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("Upstream returned an error.")).toBeDefined();
    expect(screen.getByText("page body")).toBeDefined();
  });
});
