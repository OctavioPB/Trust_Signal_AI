/**
 * Playwright smoke test — demo mode.
 *
 * Verifies the golden path: click "Load Demo" → gauge SVG renders →
 * KPI row shows TrustScore ≤ 35 → FLAGGED badge is visible.
 *
 * Requires the Vite dev server (npm run dev) to be running on port 5173.
 * playwright.config.ts starts it automatically via webServer.
 */

import { expect, test } from "@playwright/test";

test.describe("demo mode", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
  });

  test("loads demo session and renders gauge", async ({ page }) => {
    await page.getByRole("button", { name: /load demo/i }).click();

    // TrustScoreGauge SVG is visible
    await expect(page.locator("svg").first()).toBeVisible();
  });

  test("KPI row shows TrustScore ≤ 35", async ({ page }) => {
    await page.getByRole("button", { name: /load demo/i }).click();

    // Demo scenario trust_score = 31.5 — shown as "31.5" in KpiRow
    const scoreEl = page.getByText("31.5").first();
    await expect(scoreEl).toBeVisible();

    // Confirm the numeric value is indeed ≤ 35
    const raw = await scoreEl.textContent();
    expect(parseFloat(raw ?? "0")).toBeLessThanOrEqual(35);
  });

  test("FLAGGED badge is visible", async ({ page }) => {
    await page.getByRole("button", { name: /load demo/i }).click();

    // "FLAGGED" appears in both KpiRow and AlertPanel
    await expect(page.getByText("FLAGGED").first()).toBeVisible();
  });

  test("alert panel is rendered with aria role", async ({ page }) => {
    await page.getByRole("button", { name: /load demo/i }).click();

    // AlertPanel sets role="alert" aria-live="assertive"
    await expect(page.locator('[role="alert"]')).toBeVisible();
  });
});
