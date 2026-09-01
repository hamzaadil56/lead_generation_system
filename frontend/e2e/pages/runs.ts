import { Page, expect } from "@playwright/test";

export class RunsPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/runs"); }
  rows() { return this.page.locator("tbody tr"); }
  /** The unpaginated total the API reports, not the rows on this page. */
  async total(): Promise<number> {
    const text = await this.page.getByText(/^\d+ runs?$/).innerText();
    return Number(text.split(" ")[0]);
  }
  async expectFailedRunShowsReason() {
    await expect(this.page.getByText(/ceiling/i)).toBeVisible();
  }
}
