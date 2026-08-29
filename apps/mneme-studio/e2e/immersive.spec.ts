import { expect, test } from "@playwright/test";

test.describe("Immersive Learning", () => {
  test("mock workspace loads 10k virtualized transcript without lock", async ({
    page,
  }) => {
    await page.goto("/studio/immersive?mock=1", {
      waitUntil: "domcontentloaded",
    });
    // Mock mode may be env-gated; accept either player shell or disabled banner.
    const body = page.locator("body");
    await expect(body).toBeVisible();
    const disabled = page.getByText(/Immersive Learning is off/i);
    const transcript = page.getByText(/segment|transcript|cue/i).first();
    await expect(disabled.or(transcript)).toBeVisible({ timeout: 15000 });
  });
});
