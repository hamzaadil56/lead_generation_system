import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { LoginPage } from "./pages/login";

const SCREENS = ["/leads", "/leads/seed-01", "/runs", "/runs/new"];

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
