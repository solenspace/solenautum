import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { MissionSummary } from "@/features/run-mission";
import { I18nTestWrapper } from "@/shared/i18n";

import { AggregateHeader } from "./aggregate-header";

function _summary(overrides: Partial<MissionSummary> = {}): MissionSummary {
  return {
    total: 5,
    succeeded: 1,
    running: 3,
    failed: 1,
    cancelled: 0,
    pending: 0,
    elapsedMs: 90_000,
    isConnected: true,
    reconnecting: false,
    ...overrides,
  };
}

describe("AggregateHeader", () => {
  it("renders the four fields with their counts and elapsed mm:ss", () => {
    render(
      <I18nTestWrapper>
        <AggregateHeader summary={_summary()} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("1/5")).toBeDefined();
    expect(screen.getByText("3")).toBeDefined();
    expect(screen.getByText("1")).toBeDefined();
    expect(screen.getByText("01:30")).toBeDefined();
    expect(screen.getByText("done")).toBeDefined();
    expect(screen.getByText("streaming")).toBeDefined();
    expect(screen.getByText("errored")).toBeDefined();
    expect(screen.getByText("elapsed")).toBeDefined();
  });

  it("formats sub-minute elapsed times correctly", () => {
    render(
      <I18nTestWrapper>
        <AggregateHeader summary={_summary({ elapsedMs: 7_400 })} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("00:07")).toBeDefined();
  });

  it("shows the reconnect chip when reconnecting=true", () => {
    render(
      <I18nTestWrapper>
        <AggregateHeader summary={_summary({ reconnecting: true })} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("Reconnecting…")).toBeDefined();
  });

  it("hides the reconnect chip when reconnecting=false", () => {
    render(
      <I18nTestWrapper>
        <AggregateHeader summary={_summary({ reconnecting: false })} />
      </I18nTestWrapper>,
    );
    expect(screen.queryByText("Reconnecting…")).toBeNull();
  });
});
