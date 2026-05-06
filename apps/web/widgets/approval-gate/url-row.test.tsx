import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DiscoveredUrl } from "@/entities/mission/types";
import { I18nTestWrapper } from "@/shared/i18n";

import { UrlRow } from "./url-row";

function _row(overrides: Partial<DiscoveredUrl> = {}): DiscoveredUrl {
  return {
    url: "https://example.com/path",
    score: 0.85,
    source: "tavily",
    favicon_url: null,
    title: null,
    ...overrides,
  };
}

function _renderRow(
  props: {
    url?: DiscoveredUrl;
    checked?: boolean;
    edited?: string | undefined;
    onToggle?: () => void;
    onEdit?: (next: string | null) => void;
  } = {},
) {
  const url = props.url ?? _row();
  const onToggle = props.onToggle ?? vi.fn();
  const onEdit = props.onEdit ?? vi.fn();
  return render(
    <I18nTestWrapper>
      <UrlRow
        url={url}
        checked={props.checked ?? true}
        edited={props.edited}
        onToggle={onToggle}
        onEdit={onEdit}
      />
    </I18nTestWrapper>,
  );
}

describe("UrlRow", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls onToggle when the checkbox is clicked", () => {
    const onToggle = vi.fn();
    _renderRow({ onToggle });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("renders hostname and path from the URL", () => {
    _renderRow();
    expect(screen.getByText("example.com")).toBeDefined();
    expect(screen.getByText("/path")).toBeDefined();
  });

  it("clicking the hostname enters edit mode and Enter commits a new URL", () => {
    const onEdit = vi.fn();
    _renderRow({ onEdit });
    const hostnameButton = screen.getByText("example.com");
    fireEvent.click(hostnameButton);
    const input = screen.getByDisplayValue("https://example.com/path") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "https://example.com/changed" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input);
    expect(onEdit).toHaveBeenCalledWith("https://example.com/changed");
  });

  it("Escape exits edit mode without calling onEdit", () => {
    const onEdit = vi.fn();
    _renderRow({ onEdit });
    fireEvent.click(screen.getByText("example.com"));
    const input = screen.getByDisplayValue("https://example.com/path") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "https://example.com/changed" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(onEdit).not.toHaveBeenCalled();
  });

  it("renders 'edited' tag when an edit is staged", () => {
    _renderRow({ edited: "https://example.com/edited" });
    expect(screen.getByText("edited")).toBeDefined();
  });

  it("dims the row when score < 0.4", () => {
    _renderRow({ url: _row({ score: 0.3 }) });
    const hostname = screen.getByText("example.com");
    expect(hostname.className).toContain("text-muted-foreground/60");
  });

  it("score pill at >=0.8 uses the success band", () => {
    const { container } = _renderRow({ url: _row({ score: 0.85 }) });
    const dot = container.querySelector(".bg-state-success");
    expect(dot).not.toBeNull();
  });

  it("score pill at 0.5-0.8 uses the warn band", () => {
    const { container } = _renderRow({ url: _row({ score: 0.6 }) });
    const dot = container.querySelector(".bg-state-warn");
    expect(dot).not.toBeNull();
  });

  it("score pill at <0.5 uses the muted band", () => {
    const { container } = _renderRow({ url: _row({ score: 0.3 }) });
    const dot = container.querySelector(".bg-muted-foreground\\/40");
    expect(dot).not.toBeNull();
  });
});
