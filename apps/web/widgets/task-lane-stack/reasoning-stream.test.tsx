import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { ReasoningStream } from "./reasoning-stream";

const _LONG = "x".repeat(120);

describe("ReasoningStream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(10_000));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when text is empty", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ReasoningStream text="" isFocused={false} lastTokenAt={9_000} />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the full text when focused, no truncation", () => {
    render(
      <I18nTestWrapper>
        <ReasoningStream text={_LONG} isFocused={true} lastTokenAt={9_000} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText(_LONG)).toBeDefined();
  });

  it("renders only the last 80 chars when unfocused and active", () => {
    // 1.5s since last token: not idle, not focused → tail mode.
    render(
      <I18nTestWrapper>
        <ReasoningStream text={_LONG} isFocused={false} lastTokenAt={8_500} />
      </I18nTestWrapper>,
    );
    const tail = _LONG.slice(-80);
    expect(screen.getByText(tail)).toBeDefined();
  });

  it("renders the …thinking chip when unfocused and idle for ≥ 5s", () => {
    // 6s since last token: idle.
    render(
      <I18nTestWrapper>
        <ReasoningStream text={_LONG} isFocused={false} lastTokenAt={4_000} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("…thinking")).toBeDefined();
  });

  it("flips from tail to thinking after the 5s threshold trips", () => {
    // 4s since last token: tail. Advancing by 2s crosses the 5s line.
    render(
      <I18nTestWrapper>
        <ReasoningStream text={_LONG} isFocused={false} lastTokenAt={6_000} />
      </I18nTestWrapper>,
    );
    expect(screen.queryByText("…thinking")).toBeNull();
    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(screen.getByText("…thinking")).toBeDefined();
  });
});
