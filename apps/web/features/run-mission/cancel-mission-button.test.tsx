import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { CancelMissionButton } from "./cancel-mission-button";

const _mockMissions = vi.hoisted(() => ({ rows: [] as Array<Record<string, unknown>> }));

vi.mock("./use-missions", () => ({
  useMissions: () => ({ missions: _mockMissions.rows, byStatus: {}, isLoading: false }),
}));

const _fetchMock = vi.fn(async () => new Response(null, { status: 204 }));

beforeEach(() => {
  global.fetch = _fetchMock as unknown as typeof fetch;
  _fetchMock.mockClear();
  _mockMissions.rows = [];
});

afterEach(() => {
  vi.restoreAllMocks();
});

function _renderWithMission(status: string) {
  _mockMissions.rows = [
    {
      id: "m-1",
      prompt: "x",
      mode: "url",
      status,
      cost_cents: 0,
      created_at: new Date().toISOString(),
      finished_at: null,
    },
  ];
  return render(
    <I18nTestWrapper>
      <CancelMissionButton missionId="m-1" />
    </I18nTestWrapper>,
  );
}

describe("CancelMissionButton", () => {
  it("renders the button when the mission is running", () => {
    _renderWithMission("running");
    expect(screen.getByRole("button", { name: "Cancel mission" })).toBeDefined();
  });

  it("renders nothing when the mission is terminal", () => {
    const { container } = _renderWithMission("succeeded");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission is pending", () => {
    const { container } = _renderWithMission("pending");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission is unknown", () => {
    const { container } = render(
      <I18nTestWrapper>
        <CancelMissionButton missionId="m-other" />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("issues DELETE /api/missions/{id} on click", async () => {
    _renderWithMission("running");
    fireEvent.click(screen.getByRole("button", { name: "Cancel mission" }));
    // microtask drain
    await Promise.resolve();
    expect(_fetchMock).toHaveBeenCalledWith("/api/missions/m-1", { method: "DELETE" });
  });
});
