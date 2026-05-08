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

function _seedMission(id: string, status: string) {
  _mockMissions.rows = [
    {
      id,
      prompt: "x",
      mode: "url",
      status,
      cost_cents: 0,
      created_at: new Date().toISOString(),
      finished_at: null,
    },
  ];
}

function _renderFor(id: string) {
  return render(
    <I18nTestWrapper>
      <CancelMissionButton missionId={id} />
    </I18nTestWrapper>,
  );
}

describe("CancelMissionButton", () => {
  it("renders the button when the mission is running", () => {
    _seedMission("m-1", "running");
    _renderFor("m-1");
    expect(screen.getByRole("button", { name: "Cancel mission" })).toBeDefined();
  });

  it("renders nothing when the mission is terminal", () => {
    _seedMission("m-1", "succeeded");
    const { container } = _renderFor("m-1");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission is pending", () => {
    _seedMission("m-1", "pending");
    const { container } = _renderFor("m-1");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission id is unknown", () => {
    _seedMission("m-1", "running");
    const { container } = _renderFor("m-other");
    expect(container.firstChild).toBeNull();
  });

  it("issues DELETE /api/missions/{id} on click", async () => {
    _seedMission("m-1", "running");
    _renderFor("m-1");
    fireEvent.click(screen.getByRole("button", { name: "Cancel mission" }));
    await Promise.resolve();
    expect(_fetchMock).toHaveBeenCalledWith("/api/missions/m-1", { method: "DELETE" });
  });
});
