import { expect, test } from "@playwright/test";
import { LeadDetailPage } from "./pages/lead-detail";
import { LeadsPage } from "./pages/leads";
import { LoginPage } from "./pages/login";
import { NewSearchPage } from "./pages/new-search";
import { RunsPage } from "./pages/runs";

test.describe("unauthenticated", () => {
  test("story 1: a protected page redirects to login", async ({ page }) => {
    await page.goto("/leads");
    await expect(page).toHaveURL(/\/login/);
  });

  test("story 1: a wrong password is rejected", async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto();
    await login.signIn("definitely-not-the-password");
    await login.expectRejected();
  });
});

test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto();
    await login.signIn();
    await expect(page).toHaveURL(/\/leads/);
  });

  test("story 7: leads default to go_now", async ({ page }) => {
    const leads = new LeadsPage(page);
    await leads.goto();
    await leads.expectQuadrantEverywhere("Go now");
  });

  test("story 8: filtering by quadrant changes the rows", async ({ page }) => {
    const leads = new LeadsPage(page);
    await leads.goto();
    const before = await leads.rows().count();
    await leads.filterByQuadrant("cold");
    await expect(page).toHaveURL(/quadrant=cold/);
    await leads.expectQuadrantEverywhere("Cold");
    expect(await leads.rows().count()).not.toBe(before);
  });

  test("story 9: lead detail shows the breakdown and evidence", async ({ page }) => {
    const leads = new LeadsPage(page);
    await leads.goto();
    await leads.openFirstLead();
    const detail = new LeadDetailPage(page);
    await detail.expectScoreBreakdown();
    await expect(page.getByText(/nobody ever answered/i).first()).toBeVisible();
  });

  test("an unvalidated phone renders as a dash, never a number", async ({ page }) => {
    // seed-03 is seeded with phone_is_valid=False.
    await new LeadDetailPage(page).goto("seed-03");
    await expect(page.getByText("+1713555")).toHaveCount(0);
  });

  test("an unknown signal reads as unknown, not as no", async ({ page }) => {
    // seed-07 leaves runs_google_ads unset.
    await new LeadDetailPage(page).goto("seed-07");
    await expect(page.getByText(/runs google ads: unknown/i)).toBeVisible();
  });

  test("story 12: setting an outcome persists it", async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    // Write a status the lead is NOT already on. The database outlives the
    // run, so asserting a fixed value would pass on the second run even if
    // the write had stopped working.
    const current = await page.getByLabel("Status").inputValue();
    const next = current === "contacted" ? "replied" : "contacted";
    await detail.setOutcome(next);
    await page.reload();
    await expect(page.getByLabel("Status")).toHaveValue(next);
  });

  test("story 10: manual facts persist", async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-02");
    // Same reason as story 12: a fixed 25 would pass on a re-run without the
    // save having done anything.
    const current = await page.getByLabel("Estimated employees").inputValue();
    const next = current === "25" ? 26 : 25;
    await detail.setEmployees(next);
    await page.reload();
    await expect(page.getByLabel("Estimated employees")).toHaveValue(String(next));
  });

  test("story 13: exporting returns a CSV", async ({ page }) => {
    await new LeadsPage(page).goto();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Export CSV" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("leads.csv");
  });

  test("story 2 and 3: the confirm screen shows the expansion and a duplicate warning",
       async ({ page }) => {
    const search = new NewSearchPage(page);
    await search.goto();
    await search.choose("hvac", "tx", 2);
    await search.expectConfirm();
  });

  test("story 4: cancelling from confirm queues nothing", async ({ page }) => {
    const runs = new RunsPage(page);
    await runs.goto();
    const before = await runs.rows().count();

    const search = new NewSearchPage(page);
    await search.goto();
    await search.choose("hvac", "tx", 1);
    await search.cancel();

    await runs.goto();
    expect(await runs.rows().count()).toBe(before);
  });

  test("story 6: a failed run shows its reason", async ({ page }) => {
    const runs = new RunsPage(page);
    await runs.goto();
    await runs.expectFailedRunShowsReason();
  });

  test("story 14: an impossible filter shows an empty state, not an error",
       async ({ page }) => {
    await page.goto("/leads?quadrant=go_now&min_fit=100&min_pain=100");
    await new LeadsPage(page).expectEmptyState();
  });

  test("the cost figure is labelled as search-only", async ({ page }) => {
    const search = new NewSearchPage(page);
    await search.goto();
    await search.choose("hvac", "tx", 1);
    await expect(page.getByText(/scraping is not included/i)).toBeVisible();
  });
});
