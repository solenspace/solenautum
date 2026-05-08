import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMissionStore } from "@/features/run-mission";
import { I18nTestWrapper } from "@/shared/i18n";

import { MultiUrlSlideover } from "./index";

function _open() {
  useMissionStore.setState({ multiUrlOpen: true });
}

function _renderOpen() {
  _open();
  return render(
    <I18nTestWrapper>
      <MultiUrlSlideover />
    </I18nTestWrapper>,
  );
}

function _typeUrls(textarea: HTMLTextAreaElement, urls: string[]): void {
  fireEvent.change(textarea, { target: { value: urls.join("\n") } });
}

describe("MultiUrlSlideover", () => {
  beforeEach(() => {
    useMissionStore.setState({ openMissionId: null, multiUrlOpen: false });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the help copy and the keyboard hint", () => {
    _renderOpen();
    expect(screen.getByText("One URL per line. 1 to 20 URLs.")).toBeDefined();
    expect(screen.getByText("⌘↩")).toBeDefined();
  });

  it("flags missionUrlsRequired when the textarea is empty on submit", () => {
    _renderOpen();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    expect(screen.getByText("Add at least one URL")).toBeDefined();
  });

  it("flags missionUrlsTooMany when more than 20 URLs are pasted", () => {
    _renderOpen();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    const tooMany = Array.from({ length: 21 }, (_, idx) => `https://example.com/${idx}`);
    _typeUrls(textarea, tooMany);
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    expect(screen.getByText("Maximum 20 URLs per mission")).toBeDefined();
  });

  it("flags missionUrlsInvalid when a URL is malformed", () => {
    _renderOpen();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    _typeUrls(textarea, ["https://ok.example/", "not-a-url"]);
    fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });
    expect(screen.getByText("One or more URLs are invalid")).toBeDefined();
  });

  it("submits via Cmd+Enter when 1–20 valid URLs are entered, then closes", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ mission_id: "multi-7" }),
    });
    vi.stubGlobal("fetch", fetchMock);

    _renderOpen();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    const urls = ["https://a.example/", "https://b.example/"];
    _typeUrls(textarea, urls);

    await fireEvent.keyDown(textarea, { key: "Enter", metaKey: true });

    // The hook updates state asynchronously; wait for the close.
    await vi.waitFor(() => {
      expect(useMissionStore.getState().multiUrlOpen).toBe(false);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/missions",
      expect.objectContaining({ method: "POST" }),
    );
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(JSON.parse(init.body as string)).toEqual({ mode: "url", urls });
    expect(useMissionStore.getState().openMissionId).toBe("multi-7");
  });

  it("renders pluralized URL count (singular vs. plural)", () => {
    _renderOpen();
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    _typeUrls(textarea, ["https://a.example/"]);
    expect(screen.getByText(/^1 URL$/)).toBeDefined();
    _typeUrls(textarea, ["https://a.example/", "https://b.example/"]);
    expect(screen.getByText(/^2 URLs$/)).toBeDefined();
  });
});
