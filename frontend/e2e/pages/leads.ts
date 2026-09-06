import { readFileSync } from "node:fs";
import { Page, expect } from "@playwright/test";

export class LeadsPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/leads"); }
  rows() { return this.page.locator("tbody tr"); }
  async filterByQuadrant(q: string) {
    await this.page.getByRole("link", { name: q.replace(/_/g, " "), exact: true }).click();
  }
  async openFirstLead() {
    await this.rows().first().getByRole("link").click();
  }
  async filterByOutcome(status: string) {
    await this.page.getByRole("link", { name: status, exact: true }).click();
  }
  /** Click Export CSV and hand back the file's data rows (header dropped). */
  async exportCsvRows(): Promise<string[]> {
    const [download] = await Promise.all([
      this.page.waitForEvent("download"),
      this.page.getByRole("link", { name: "Export CSV" }).click(),
    ]);
    const path = await download.path();
    return readFileSync(path, "utf-8").trim().split("\n").slice(1);
  }
  /** Click Export contacts CSV and hand back its data rows (header dropped). */
  async exportContactsCsvRows(): Promise<string[]> {
    const [download] = await Promise.all([
      this.page.waitForEvent("download"),
      this.page.getByRole("link", { name: "Export contacts CSV" }).click(),
    ]);
    const path = await download.path();
    return readFileSync(path, "utf-8").trim().split("\n").slice(1);
  }
  async expectEmptyState() {
    await expect(this.page.getByText(/no leads match/i)).toBeVisible();
  }
  async expectQuadrantEverywhere(label: string) {
    // Column 4 is Quadrant -- see the header order in components/leads-table.
    const badges = this.page.locator("tbody tr td:nth-child(4)");
    const n = await badges.count();
    expect(n).toBeGreaterThan(0);
    for (let i = 0; i < n; i++) await expect(badges.nth(i)).toHaveText(label);
  }
}
