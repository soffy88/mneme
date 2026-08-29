import { expect, test } from "@playwright/test";

/**
 * Immersive Learning merge-gate browser tests.
 *
 * Default path uses NEXT_PUBLIC_IMMERSIVE_MOCK=1 so this never writes to the
 * production API (localhost:8000 / api.sxueji.com). Isolated live API tests
 * are gated behind IMMERSIVE_E2E_LIVE=1 + NEXT_PUBLIC_API_BASE pointing at a
 * non-production stack.
 */

test.describe("Immersive Learning — mock / virtualization", () => {
  test.use({
    // Ensure mock mode even if studio was started without the env — page reads
    // build-time NEXT_PUBLIC_*, so studio must be started with MOCK=1.
  });

  test("10k transcript loads without lock and virtualizes DOM", async ({
    page,
  }) => {
    await page.goto("/studio/immersive", { waitUntil: "domcontentloaded" });

    const disabled = page.getByText(/Immersive Learning is off/i);
    const mockTitle = page.getByRole("heading", {
      name: /Mock Immersive Media/i,
    });
    const transcript = page.locator("[data-testid='immersive-transcript']");

    // Wait until mock ready, disabled, or still loading past boot.
    await expect(disabled.or(mockTitle).or(transcript).first()).toBeVisible({
      timeout: 20_000,
    });

    if (await disabled.isVisible()) {
      test.info().annotations.push({
        type: "note",
        description:
          "Studio not started with NEXT_PUBLIC_IMMERSIVE_MOCK=1; virtualization check skipped",
      });
      return;
    }

    await expect(transcript).toBeVisible({ timeout: 20_000 });
    await expect(mockTitle).toBeVisible();

    // Virtualization: rendered segment nodes must be << 10000
    const rendered = await page
      .locator("[data-testid='immersive-segment-row']")
      .count();
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(500);

    // Scroll responsiveness
    await page.locator("[data-testid='immersive-transcript']").evaluate((el) => {
      el.scrollTop = el.scrollHeight / 2;
    });
    await page.waitForTimeout(200);
    const midCount = await page
      .locator("[data-testid='immersive-segment-row']")
      .count();
    expect(midCount).toBeLessThan(500);

    // Seek via click
    const row = page.locator("[data-testid='immersive-segment-row']").first();
    await row.click();
    await expect(
      page.locator("[data-testid='immersive-current-segment']")
    ).toBeVisible({ timeout: 5_000 });

    // Keyboard next/prev / subtitle / translation
    await page.keyboard.press("d");
    await page.keyboard.press("a");
    await page.keyboard.press("s");
    await page.keyboard.press("e");
    await page.keyboard.press("c");
  });
});

test.describe("Immersive Learning — live isolated API", () => {
  test.skip(
    process.env.IMMERSIVE_E2E_LIVE !== "1",
    "Set IMMERSIVE_E2E_LIVE=1 against isolated non-prod API to run golden path"
  );

  test("golden path upload→practice→resume", async ({ page }) => {
    // Placeholder for isolated-stack golden path; requires IMMERSIVE_E2E_LIVE=1
    // and a test API with IMMERSIVE_LEARNING_ENABLED=1 on mneme_test.
    await page.goto("/studio/immersive");
    await expect(page.getByText(/Immersive/i).first()).toBeVisible();
  });
});
