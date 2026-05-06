import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { BulkToolbar } from "./bulk-toolbar";

function _renderToolbar(overrides: Partial<React.ComponentProps<typeof BulkToolbar>> = {}) {
  const props: React.ComponentProps<typeof BulkToolbar> = {
    selectedCount: 0,
    totalCount: 5,
    canSubmit: false,
    skipApproval: false,
    onSkipApprovalChange: vi.fn(),
    onSubmit: vi.fn(),
    onToggleAll: vi.fn(),
    submitting: false,
    ...overrides,
  };
  return {
    ...props,
    ...render(
      <I18nTestWrapper>
        <BulkToolbar {...props} />
      </I18nTestWrapper>,
    ),
  };
}

describe("BulkToolbar", () => {
  it("disables the approve button when canSubmit is false", () => {
    _renderToolbar({ selectedCount: 0, canSubmit: false });
    const button = screen.getByRole("button", { name: /Approve/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
  });

  it("enables the approve button when canSubmit is true and selection > 0", () => {
    _renderToolbar({ selectedCount: 3, canSubmit: true });
    const button = screen.getByRole("button", { name: /Approve 3 URLs/ });
    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("renders the singular plural form at selectedCount=1", () => {
    _renderToolbar({ selectedCount: 1, canSubmit: true });
    // Accessible name composes the button text with the trailing Kbd hint;
    // matching the prefix is sufficient to verify plural resolution.
    const button = screen.getByRole("button", { name: /^Approve 1 URL/ });
    expect(button.textContent).toContain("Approve 1 URL");
    expect(button.textContent).not.toContain("URLs");
  });

  it("toggles the label between deselectAll/selectAll based on selection state", () => {
    const r1 = _renderToolbar({ selectedCount: 0, totalCount: 5 });
    expect(screen.getByRole("button", { name: "Select all" })).toBeDefined();
    r1.unmount();
    _renderToolbar({ selectedCount: 5, totalCount: 5 });
    expect(screen.getByRole("button", { name: "Deselect all" })).toBeDefined();
  });

  it("propagates the skip-approval checkbox change", () => {
    const onSkipApprovalChange = vi.fn();
    _renderToolbar({ skipApproval: false, onSkipApprovalChange });
    const checkbox = screen.getByRole("checkbox");
    fireEvent.click(checkbox);
    expect(onSkipApprovalChange).toHaveBeenCalledWith(true);
  });

  it("calls onSubmit when the approve button is clicked", () => {
    const onSubmit = vi.fn();
    _renderToolbar({ selectedCount: 2, canSubmit: true, onSubmit });
    fireEvent.click(screen.getByRole("button", { name: /Approve 2 URLs/ }));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("calls onToggleAll when the select-all label button is clicked", () => {
    const onToggleAll = vi.fn();
    _renderToolbar({ selectedCount: 0, totalCount: 5, onToggleAll });
    fireEvent.click(screen.getByRole("button", { name: "Select all" }));
    expect(onToggleAll).toHaveBeenCalledTimes(1);
  });

  it("renders the selected-of-total counter", () => {
    _renderToolbar({ selectedCount: 2, totalCount: 5 });
    expect(screen.getByText("2 of 5")).toBeDefined();
  });
});
