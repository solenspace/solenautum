import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useSubmitMission } from "./use-submit-mission";

const _routerPush = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: _routerPush, replace: _routerPush }),
}));

afterEach(() => {
  vi.restoreAllMocks();
  _routerPush.mockClear();
});

describe("useSubmitMission", () => {
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

  it("navigates to the mission detail route on a successful submit", async () => {
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
      expect(_routerPush).toHaveBeenCalledWith("/missions/abc-123");
    });
    expect(result.current.error).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/missions",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("posts a `urls` array (single-element) on submit", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mission_id: "abc-123" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("https://example.com/");
    });

    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({
      mode: "url",
      urls: ["https://example.com/"],
    });
  });

  it("returns missionFailed on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    const { result } = renderHook(() => useSubmitMission());
    await act(async () => {
      await result.current.submit("https://example.com/");
    });
    expect(result.current.error).toBe("missionFailed");
  });

  describe("submitMany (multi-URL)", () => {
    it("posts the array as `urls` and navigates to the mission detail", async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ mission_id: "multi-1" }),
      });
      vi.stubGlobal("fetch", fetchMock);

      const urls = ["https://a.example/", "https://b.example/"];
      const { result } = renderHook(() => useSubmitMission());
      await act(async () => {
        await result.current.submitMany(urls);
      });

      const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
      expect(JSON.parse(init.body as string)).toEqual({ mode: "url", urls });
      await waitFor(() => {
        expect(_routerPush).toHaveBeenCalledWith("/missions/multi-1");
      });
      expect(result.current.error).toBeNull();
    });

    it("surfaces missionFailed on non-2xx", async () => {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
      const { result } = renderHook(() => useSubmitMission());
      await act(async () => {
        await result.current.submitMany(["https://a.example/"]);
      });
      expect(result.current.error).toBe("missionFailed");
    });
  });
});
