import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DiscoveredUrl } from "@/entities/mission/types";

import { useApprovalState } from "./use-approval-state";

function _urls(): DiscoveredUrl[] {
  return [
    { url: "https://a.example/", score: 0.9, source: "tavily", favicon_url: null, title: null },
    { url: "https://b.example/", score: 0.5, source: "tavily", favicon_url: null, title: null },
    { url: "https://c.example/", score: 0.3, source: "tavily", favicon_url: null, title: null },
  ];
}

describe("useApprovalState", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("seeds selection with URLs whose score >= 0.4", () => {
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    expect(result.current.selected.has("https://a.example/")).toBe(true);
    expect(result.current.selected.has("https://b.example/")).toBe(true);
    expect(result.current.selected.has("https://c.example/")).toBe(false);
  });

  it("toggle adds and removes a URL", () => {
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    act(() => result.current.toggle("https://c.example/"));
    expect(result.current.selected.has("https://c.example/")).toBe(true);
    act(() => result.current.toggle("https://c.example/"));
    expect(result.current.selected.has("https://c.example/")).toBe(false);
  });

  it("toggleAll fills the selection from a partial seed, then empties on the next press", () => {
    const urls = _urls();
    const { result } = renderHook(() => useApprovalState("m1", urls));
    // Default seed is 2/3 (a + b above the 0.4 threshold). First toggle fills.
    act(() => result.current.toggleAll());
    expect(result.current.selected.size).toBe(urls.length);
    act(() => result.current.toggleAll());
    expect(result.current.selected.size).toBe(0);
  });

  it("setEdit updates and clears the edits map", () => {
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    act(() => result.current.setEdit("https://a.example/", "https://a.example/edited"));
    expect(result.current.edits["https://a.example/"]).toBe("https://a.example/edited");
    act(() => result.current.setEdit("https://a.example/", null));
    expect(result.current.edits["https://a.example/"]).toBeUndefined();
  });

  it("submit POSTs the edited URL list and skip_approval flag", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useApprovalState("mission-7", _urls()));
    act(() => result.current.setEdit("https://a.example/", "https://a.example/edited"));
    act(() => result.current.setSkipApproval(true));
    await act(async () => {
      await result.current.submit();
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/missions/mission-7/approve");
    const body = JSON.parse(init.body as string) as { urls: string[]; skip_approval: boolean };
    expect(body.skip_approval).toBe(true);
    // Default seed includes a (>=0.4) and b (>=0.4); a's URL comes through edited.
    expect(body.urls.sort()).toEqual(["https://a.example/edited", "https://b.example/"].sort());
  });

  it("submit sets submitError when the fetch returns non-ok", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }));
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    await act(async () => {
      await result.current.submit();
    });
    await waitFor(() => {
      expect(result.current.submitError).toBe(true);
    });
  });

  it("submit no-ops with submitError when no URLs are selected", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    // Empty the seed by toggling each pre-selected URL off.
    act(() => result.current.toggle("https://a.example/"));
    act(() => result.current.toggle("https://b.example/"));
    expect(result.current.selected.size).toBe(0);
    await act(async () => {
      await result.current.submit();
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(result.current.submitError).toBe(true);
  });

  it("setDomainFilter and setSortBy round-trip", () => {
    const { result } = renderHook(() => useApprovalState("m1", _urls()));
    act(() => result.current.setDomainFilter("a.example"));
    expect(result.current.domainFilter).toBe("a.example");
    act(() => result.current.setSortBy("domain"));
    expect(result.current.sortBy).toBe("domain");
  });
});
