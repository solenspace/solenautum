import { describe, expect, it } from "vitest";

import { translate } from "./translate";

describe("translate", () => {
  it("returns the literal for a known key", () => {
    expect(translate("common", "signOut")).toBe("Sign out");
  });

  it("interpolates {name} placeholders from params", () => {
    expect(translate("mission", "noMissionsHint", { shortcut: "⌘N" })).toBe(
      "Paste a URL above or press ⌘N",
    );
  });

  it("returns the key when the lookup misses", () => {
    // @ts-expect-error — deliberately invalid key for the negative path
    expect(translate("common", "doesNotExist")).toBe("doesNotExist");
  });

  it("leaves unmatched placeholders intact", () => {
    expect(translate("mission", "noMissionsHint")).toBe("Paste a URL above or press {shortcut}");
  });
});
