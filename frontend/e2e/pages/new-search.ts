import { Page, expect } from "@playwright/test";

export class NewSearchPage {
  constructor(private page: Page) {}
  async goto() { await this.page.goto("/runs/new"); }
  async choose(vertical: string, state: string, pages: number) {
    await this.page.getByLabel("Vertical").selectOption(vertical);
    await this.page.getByLabel("State").selectOption(state);
    await this.page.getByLabel("Pages per query").fill(String(pages));
    await this.page.getByRole("button", { name: "Preview" }).click();
  }
  async expectConfirm() {
    await expect(this.page.getByText(/searches/)).toBeVisible();
    await expect(this.page.getByText(/estimated search cost/i)).toBeVisible();
  }
  async cancel() { await this.page.getByRole("link", { name: "Cancel" }).click(); }
}
