import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { LoginPage } from "./pages/login";

// seed-01 exercises the contacts card empty; seed-02 carries a seeded
// confirmed manual contact (Dana Reyes), so this also covers the card with an
// actual contact row -- the Primary badge and the mailto link -- rendered
// deterministically, without depending on another spec's harvest having run
// first.
const SCREENS = ["/leads", "/leads/seed-01", "/leads/seed-02", "/runs", "/runs/new"];

test.beforeEach(async ({ page }) => {
  const login = new LoginPage(page);
  await login.goto();
  await login.signIn();
});

for (const path of SCREENS) {
  test(`no accessibility violations on ${path}`, async ({ page }) => {
    await page.goto(path);
    const { violations } = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
}
