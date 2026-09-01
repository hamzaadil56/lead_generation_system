import { Locator, Page, expect } from "@playwright/test";

export class LeadDetailPage {
  constructor(private page: Page) {}
  async goto(cid: string) { await this.page.goto(`/leads/${cid}`); }
  async expectScoreBreakdown() {
    await expect(this.page.getByRole("heading", { name: "Fit" })).toBeVisible();
    await expect(this.page.getByRole("heading", { name: "Pain" })).toBeVisible();
  }
  /** Click, then wait for the Server Action's POST to come back.
   *
   *  Neither form shows anything on success -- no toast, no changed text --
   *  so there is no DOM signal to wait on, and `click()` resolves as soon as
   *  the event dispatches. A `page.reload()` straight after therefore races
   *  the action's own request and re-renders from the pre-save row. The
   *  response is the only deterministic "the write has landed" signal these
   *  screens offer today. */
  private async save(name: string) {
    await Promise.all([
      this.page.waitForResponse((r) =>
        r.request().method() === "POST" && r.url().includes("/leads/")),
      this.page.getByRole("button", { name }).click(),
    ]);
  }
  async setOutcome(status: string) {
    await this.page.getByLabel("Status").selectOption(status);
    await this.save("Save outcome");
  }
  async setEmployees(n: number) {
    await this.page.getByLabel("Estimated employees").fill(String(n));
    await this.save("Save facts");
  }

  /** The three-state control for a `bool | null` manual fact. Not a checkbox:
   *  a checkbox cannot hold "unknown". */
  fact(label: string): Locator { return this.page.getByLabel(label); }
  factsNotes(): Locator {
    return this.page.getByRole("button", { name: "Save facts" })
      .locator("xpath=ancestor::form").getByLabel("Notes");
  }
  async setFacts(values: Record<string, string>) {
    for (const [label, value] of Object.entries(values)) {
      await this.fact(label).selectOption(value);
    }
    await this.save("Save facts");
  }
  async setFactsNotes(text: string) {
    await this.factsNotes().fill(text);
    await this.save("Save facts");
  }
}
