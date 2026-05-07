import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { CancelMissionButton } from "./cancel-mission-button";
import { useMissionStore } from "./store";

const _mockMissions = vi.hoisted(() => ({ rows: [] as Array<Record<string, unknown>> }));

vi.mock("./use-missions", () => ({
  useMissions: () => ({ missions: _mockMissions.rows, byStatus: {}, isLoading: false }),
}));

const _fetchMock = vi.fn(async () => new Response(null, { status: 204 }));

beforeEach(() => {
  global.fetch = _fetchMock as unknown as typeof fetch;
  _fetchMock.mockClear();
  _mockMissions.rows = [];
  useMissionStore.setState({ openMissionId: null });
});

afterEach(() => {
  vi.restoreAllMocks();
  useMissionStore.setState({ openMissionId: null });
});

function _openMission(id: string, status: string) {
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
  useMissionStore.setState({ openMissionId: id });
  return render(
    <I18nTestWrapper>
      <CancelMissionButton />
    </I18nTestWrapper>,
  );
}

describe("CancelMissionButton", () => {
  it("renders the button when the mission is running", () => {
    _openMission("m-1", "running");
    expect(screen.getByRole("button", { name: "Cancel mission" })).toBeDefined();
  });

  it("renders nothing when the mission is terminal", () => {
    const { container } = _openMission("m-1", "succeeded");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission is pending", () => {
    const { container } = _openMission("m-1", "pending");
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when no mission is open", () => {
    const { container } = render(
      <I18nTestWrapper>
        <CancelMissionButton />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders nothing when the mission id is unknown", () => {
    useMissionStore.setState({ openMissionId: "m-other" });
    const { container } = render(
      <I18nTestWrapper>
        <CancelMissionButton />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("issues DELETE /api/missions/{id} on click", async () => {
    _openMission("m-1", "running");
    fireEvent.click(screen.getByRole("button", { name: "Cancel mission" }));
    await Promise.resolve();
    expect(_fetchMock).toHaveBeenCalledWith("/api/missions/m-1", { method: "DELETE" });
  });
});
