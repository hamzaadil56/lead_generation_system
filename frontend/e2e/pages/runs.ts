import { Page, expect } from "@playwright/test";

export class RunsPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/runs"); }
  rows() { return this.page.locator("tbody tr"); }
  async expectFailedRunShowsReason() {
    await expect(this.page.getByText(/ceiling/i)).toBeVisible();
  }
}
