import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMissionStore } from "./store";
import { useSubmitMission } from "./use-submit-mission";

describe("useSubmitMission", () => {
  beforeEach(() => {
    useMissionStore.setState({ openMissionId: null });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns urlRequired when input is empty", async () => {
    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("");
    });
    expect(result.current.error).toBe("urlRequired");
  });

  it("returns urlInvalid when scheme is missing", async () => {
    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("not-a-url");
    });
    expect(result.current.error).toBe("urlInvalid");
  });

  it("returns urlTooLong above 2048 chars", async () => {
    const long = `https://example.com/${"a".repeat(2050)}`;
    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit(long);
    });
    expect(result.current.error).toBe("urlTooLong");
  });

  it("opens the slide-over on a successful submit", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mission_id: "abc-123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("https://example.com/");
    });

    await waitFor(() => {
      expect(useMissionStore.getState().openMissionId).toBe("abc-123");
    });
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/missions",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("returns missionFailed on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("https://example.com/");
    });
    expect(result.current.error).toBe("missionFailed");
  });
});
