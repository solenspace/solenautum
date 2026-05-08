import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { ResultPreview } from "./result-preview";

describe("ResultPreview", () => {
  it("renders nothing when preview is undefined", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview preview={undefined} missionId="m-1" taskId="t-1" />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the preview text when present", () => {
    render(
      <I18nTestWrapper>
        <ResultPreview preview="hello world" missionId="m-1" taskId="t-1" />
      </I18nTestWrapper>,
    );
    expect(screen.getByText("hello world")).toBeDefined();
  });

  it("renders nothing for an empty-string preview", () => {
    // Failed tasks land here with an empty preview; rendering the
    // empty `<pre>` card produced a sad blank rectangle below the
    // failure chip, so the component now skips the preview block
    // entirely when there is no content of any kind.
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview preview="" missionId="m-1" taskId="t-1" />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });
});
