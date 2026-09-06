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

  /** The `<li>` for one contact row, scoped by any visible text in it (name,
   *  email, or discovery note). Confirm/Delete live inside this row, and
   *  several rows can be on screen at once, so every contact action below
   *  is scoped through this rather than a bare `getByRole`. */
  contactRow(match: string): Locator {
    return this.page.locator("li").filter({ hasText: match });
  }

  /** Same wait strategy as `save` above: ContactsCard's actions are plain
   *  server-action calls with no success indicator of their own, so the
   *  response to the action's own POST is the only deterministic signal
   *  that the mutation (and the `revalidatePath` after it) has landed. */
  private async mutate(click: () => Promise<void>) {
    await Promise.all([
      this.page.waitForResponse((r) =>
        r.request().method() === "POST" && r.url().includes("/leads/")),
      click(),
    ]);
  }

  async harvestContacts() {
    await this.mutate(() =>
      this.page.getByRole("button", { name: "Harvest from website" }).click());
  }

  async confirmContact(match: string) {
    await this.mutate(() =>
      this.contactRow(match).getByRole("button", { name: "Confirm" }).click());
  }

  async deleteContact(match: string) {
    await this.mutate(() =>
      this.contactRow(match).getByRole("button", { name: "Delete" }).click());
  }

  /** Fills only the fields given, then submits. Mirrors ContactsCard's own
   *  "" -> null coercion: an omitted field is left blank, not zeroed out. */
  async addContact(fields: { name?: string; email?: string }) {
    if (fields.name) await this.page.getByLabel("Name").fill(fields.name);
    if (fields.email) await this.page.getByLabel("Email").fill(fields.email);
    await this.mutate(() =>
      this.page.getByRole("button", { name: "Add" }).click());
  }
}
