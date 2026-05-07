import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { I18nTestWrapper } from "@/shared/i18n";

import { ResultPreview } from "./result-preview";

beforeEach(() => {
  // Default to production for these tests so the link renders enabled;
  // individual cases override for the dev-disabled assertion. `vi.stubEnv`
  // is the supported vitest API — direct `process.env` assignment is
  // refused by Node 22+ since `NODE_ENV` is non-configurable.
  vi.stubEnv("NODE_ENV", "production");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe("ResultPreview — Spec 14 snapshot download link", () => {
  it("renders nothing when neither preview nor snapshotKey is set", () => {
    const { container } = render(
      <I18nTestWrapper>
        <ResultPreview preview={undefined} missionId="m-1" taskId="t-1" />
      </I18nTestWrapper>,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders a link to the BFF snapshot route when snapshotKey is set", () => {
    render(
      <I18nTestWrapper>
        <ResultPreview
          preview="hello"
          missionId="m-1"
          taskId="t-2"
          snapshotKey="user/m-1/t-2/snap.html.gz"
        />
      </I18nTestWrapper>,
    );
    const link = screen.getByRole("link", { name: /Download HTML/ });
    expect(link.getAttribute("href")).toBe("/api/missions/m-1/tasks/t-2/snapshot");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toContain("noopener");
  });

  it("does not render a link when snapshotKey is absent", () => {
    render(
      <I18nTestWrapper>
        <ResultPreview preview="hello" missionId="m-1" taskId="t-1" />
      </I18nTestWrapper>,
    );
    expect(screen.queryByRole("link", { name: /Download HTML/ })).toBeNull();
  });

  it("renders a disabled label in dev (local-fs blob backend)", () => {
    vi.stubEnv("NODE_ENV", "development");
    render(
      <I18nTestWrapper>
        <ResultPreview
          preview="hello"
          missionId="m-1"
          taskId="t-2"
          snapshotKey="user/m-1/t-2/snap.html.gz"
        />
      </I18nTestWrapper>,
    );
    expect(screen.queryByRole("link", { name: /Download HTML/ })).toBeNull();
    // The hint text is rendered next to the disabled label.
    expect(screen.getByText(/dev only/i)).toBeDefined();
  });
});
