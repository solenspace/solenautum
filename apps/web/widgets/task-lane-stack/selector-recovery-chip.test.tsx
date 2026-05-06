import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { SelectorRecoveryChip } from "./selector-recovery-chip";

describe("SelectorRecoveryChip", () => {
  it("renders the singular form when count is 1", () => {
    render(
      <I18nTestWrapper>
        <SelectorRecoveryChip count={1} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("1 selector recovered")).toBeDefined();
  });

  it("renders the plural form for count > 1", () => {
    render(
      <I18nTestWrapper>
        <SelectorRecoveryChip count={4} />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("4 selectors recovered")).toBeDefined();
  });

  it("exposes the recovery hint as a tooltip", () => {
    render(
      <I18nTestWrapper>
        <SelectorRecoveryChip count={2} />
      </I18nTestWrapper>,
    );
    expect(
      screen.getByTitle("Saved selectors matched after the site's DOM shifted."),
    ).toBeDefined();
  });
});
