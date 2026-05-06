import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { ResultPreview } from "./result-preview";

describe("ResultPreview", () => {
  it("renders nothing when preview is undefined", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview preview={undefined} />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the preview text when present", () => {
    render(
      <I18nTestWrapper>
        <ResultPreview preview="hello world" />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("hello world")).toBeDefined();
  });

  it("renders an empty preview without crashing", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview preview="" />
      </I18nTestWrapper>,
    );
    expect(container.querySelector("pre")?.textContent).toBe("");
  });
});
