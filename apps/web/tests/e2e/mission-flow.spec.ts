import { setupClerkTestingToken } from "@clerk/testing/playwright";
import { expect, test } from "@playwright/test";

/**
 * End-to-end coverage for the URL-mode mission flow.
 *
 * Pre-conditions (set in the shell or CI nightly env):
 *   - `AUTUMN_E2E=1` — opt-in switch (tests skip otherwise so a casual
 *     `pnpm e2e` doesn't fail on missing infrastructure).
 *   - `CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY` — Clerk testing keys.
 *   - The api running on `:8000` with a reachable Postgres, blob backend,
 *     LLM provider key, and `AUTUMN_URL_ALLOWLIST=127.0.0.1` so the SSRF
 *     guard (invariant 1) admits fixture URLs from `:9999`.
 *
 * The two specs cover the exit criteria from Spec 15 §End-to-end:
 *   1. URL-mode 5-URL mission renders end-to-end (slide-over → 5 lanes →
 *      every lane reaches `succeeded`).
 *   2. Forced disconnect mid-stream resumes via `Last-Event-ID`
 *      (`Reconnecting…` chip appears, then clears, lanes still settle).
 */

const FIXTURE_BASE = "http://127.0.0.1:9999";
const URL_COUNT = 5;
const fixtureUrls = Array.from({ length: URL_COUNT }, (_, i) => `${FIXTURE_BASE}/page-${i}`);

test.describe("URL-mode mission", () => {
  test.skip(!process.env.AUTUMN_E2E, "set AUTUMN_E2E=1 to run the e2e suite");

  test("5-URL mission renders end-to-end", async ({ page }) => {
    await setupClerkTestingToken({ page });
    await page.goto("/missions");

    // Open the multi-URL slide-over via the keyboard shortcut wired in
    // `widgets/command-palette/index.tsx`.
    await page.keyboard.press("Meta+Shift+N");

    const textarea = page.getByRole("textbox", { name: /multi-url mission/i });
    await expect(textarea).toBeVisible();
    await textarea.fill(fixtureUrls.join("\n"));
    await textarea.press("Meta+Enter");

    // Five `<li data-status>` lane rows render inside the slide-over, then
    // every lane progresses to `succeeded`. Generous timeouts cover an
    // ~8s-per-task worst case before retries.
    await expect(page.locator("li[data-status]")).toHaveCount(URL_COUNT, {
      timeout: 30_000,
    });
    await expect(page.locator('li[data-status="succeeded"]')).toHaveCount(URL_COUNT, {
      timeout: 90_000,
    });
  });

  test("forced disconnect mid-stream resumes via Last-Event-ID", async ({ page, context }) => {
    await setupClerkTestingToken({ page });
    await page.goto("/missions");

    await page.keyboard.press("Meta+Shift+N");
    const textarea = page.getByRole("textbox", { name: /multi-url mission/i });
    await textarea.fill(fixtureUrls.join("\n"));
    await textarea.press("Meta+Enter");
    await expect(page.locator("li[data-status]")).toHaveCount(URL_COUNT, {
      timeout: 30_000,
    });

    // Cut the network mid-stream; the EventSource fires `onerror`, which
    // flips `useMissionStream`'s `reconnecting` state and surfaces the
    // `Reconnecting…` chip from `widgets/task-lane-stack/reconnect-chip.tsx`.
    await context.setOffline(true);
    await expect(page.getByText("Reconnecting…")).toBeVisible({ timeout: 10_000 });

    // Restore connectivity; the chip clears as soon as the stream
    // reconnects (EventSource auto-retries with its own backoff). The
    // ring buffer + `Last-Event-ID` resume hand the missed events to the
    // client without duplication.
    await context.setOffline(false);
    await expect(page.getByText("Reconnecting…")).toBeHidden({ timeout: 15_000 });
    await expect(page.locator('li[data-status="succeeded"]')).toHaveCount(URL_COUNT, {
      timeout: 90_000,
    });
  });
});
