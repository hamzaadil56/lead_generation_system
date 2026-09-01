import { Page, expect } from "@playwright/test";

export class LoginPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/login"); }
  async signIn(password = process.env.DASHBOARD_PASSWORD ?? "changeme") {
    await this.page.getByLabel("Password").fill(password);
    await this.page.getByRole("button", { name: "Sign in" }).click();
  }
  async expectRejected() {
    // Scoped to the form: Next renders its own always-present route announcer
    // (`<div role="alert" id="__next-route-announcer__">`) on every page, so a
    // bare getByRole("alert") is a strict-mode violation on every screen.
    await expect(this.page.locator("form").getByRole("alert"))
      .toContainText("not right");
  }
}
