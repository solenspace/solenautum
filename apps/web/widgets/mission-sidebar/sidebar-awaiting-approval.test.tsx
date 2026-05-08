import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarProvider } from "@/components/ui/sidebar";
import type { MissionRow } from "@/entities/mission/types";
import { I18nTestWrapper } from "@/shared/i18n";

const _mockMissions = vi.hoisted(() => ({
  byStatus: {
    pending: [] as MissionRow[],
    running: [] as MissionRow[],
    awaiting_approval: [] as MissionRow[],
    succeeded: [] as MissionRow[],
    failed: [] as MissionRow[],
    cancelled: [] as MissionRow[],
  },
}));

vi.mock("@/features/run-mission", async (importActual) => {
  const actual = await importActual<typeof import("@/features/run-mission")>();
  return {
    ...actual,
    useMissions: () => ({
      missions: Object.values(_mockMissions.byStatus).flat(),
      byStatus: _mockMissions.byStatus,
      isLoading: false,
    }),
  };
});

import { MissionSidebar } from "./index";

function _row(overrides: Partial<MissionRow>): MissionRow {
  return {
    id: "m-1",
    prompt: "fetch the page",
    mode: "url",
    status: "running",
    cost_cents: 0,
    created_at: new Date().toISOString(),
    finished_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  _mockMissions.byStatus = {
    pending: [],
    running: [],
    awaiting_approval: [],
    succeeded: [],
    failed: [],
    cancelled: [],
  };
  // jsdom doesn't ship `matchMedia`; the SidebarProvider's mobile-detect
  // hook reads it on mount. Stub it to a passive desktop default.
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("MissionSidebar — Spec 14 awaiting_approval bucket + cost", () => {
  it("renders the awaiting_approval group when a mission is parked", () => {
    _mockMissions.byStatus.awaiting_approval = [
      _row({ id: "m-park", status: "running", phase: "awaiting_approval" }),
    ];
    render(
      <I18nTestWrapper>
        <SidebarProvider>
          <MissionSidebar />
        </SidebarProvider>
      </I18nTestWrapper>,
    );
    expect(screen.getByText("Awaiting approval")).toBeDefined();
  });

  it("renders the cost as $X.XXX when cost_cents is positive", () => {
    _mockMissions.byStatus.succeeded = [
      _row({ id: "m-paid", status: "succeeded", cost_cents: 12 }),
    ];
    render(
      <I18nTestWrapper>
        <SidebarProvider>
          <MissionSidebar />
        </SidebarProvider>
      </I18nTestWrapper>,
    );
    expect(screen.getByText("$0.120")).toBeDefined();
  });

  it("renders no cost cell when terminal mission has cost_cents == 0", () => {
    // Free-tier missions land here. The previous behavior of rendering
    // `?` placed a noisy sentinel on every row and hid the actual
    // `$X.XXX` it was meant to highlight; the row simply omits the
    // cost cell when there is no spend to report.
    _mockMissions.byStatus.succeeded = [_row({ id: "m-zero", status: "succeeded", cost_cents: 0 })];
    render(
      <I18nTestWrapper>
        <SidebarProvider>
          <MissionSidebar />
        </SidebarProvider>
      </I18nTestWrapper>,
    );
    expect(screen.queryByText("?")).toBeNull();
    expect(screen.queryByText(/\$/)).toBeNull();
  });

  it("renders no cost cell while the mission is still running", () => {
    _mockMissions.byStatus.running = [_row({ id: "m-live", status: "running", cost_cents: 0 })];
    render(
      <I18nTestWrapper>
        <SidebarProvider>
          <MissionSidebar />
        </SidebarProvider>
      </I18nTestWrapper>,
    );
    expect(screen.queryByText("?")).toBeNull();
    expect(screen.queryByText(/\$/)).toBeNull();
  });
});
