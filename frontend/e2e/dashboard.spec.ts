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

  test("an unresearched manual fact stays unknown, and a partial save leaves it alone",
       async ({ page }) => {
    // The Critical this wave fixed. `has_office_admin` and
    // `owner_growth_focused` are `bool | None`, but the form rendered them as
    // checkboxes, so every save wrote an explicit `false` for anything
    // unticked -- into `manual_facts`, the one permanent table a pipeline
    // rerun must never rebuild -- and `null` became unreachable from the UI.
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-05");

    // Alternate the yes/no field for the same reason as stories 10 and 12: a
    // fixed value would pass on a re-run even if the write had stopped
    // working.
    const current = await detail.fact("Owner is growth-focused").inputValue();
    const flipped = current === "yes" ? "no" : "yes";
    await detail.setFacts({
      "Has an office admin": "unknown",
      "Owner is growth-focused": flipped,
    });
    await page.reload();
    // Round trip through the API and back: "unknown" here means the column is
    // NULL, because a stored `false` renders as "no".
    await expect(detail.fact("Has an office admin")).toHaveValue("unknown");
    await expect(detail.fact("Owner is growth-focused")).toHaveValue(flipped);

    // Now the exact reproduction from the review: type only a note and save.
    const note = `partial save ${Date.now()}`;
    await detail.setFactsNotes(note);
    await page.reload();
    await expect(detail.factsNotes()).toHaveValue(note);
    await expect(detail.fact("Has an office admin")).toHaveValue("unknown");
    await expect(detail.fact("Owner is growth-focused")).toHaveValue(flipped);
  });

  test("story 13: exporting returns a CSV", async ({ page }) => {
    await new LeadsPage(page).goto();
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("link", { name: "Export CSV" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe("leads.csv");
  });

  test("story 13: the exported CSV is the filtered set, not the whole table",
       async ({ page }) => {
    // Reproduced live before this fix: outcome_status=contacted showed 1 row
    // and downloaded 10. "booked" is used by no other test, so this owns its
    // own filter end to end.
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-06");
    await detail.setOutcome("booked");

    const leads = new LeadsPage(page);
    await page.goto("/leads?quadrant=all&outcome_status=booked");
    const onScreen = await leads.rows().count();
    expect(onScreen).toBe(1);

    const rows = await leads.exportCsvRows();
    expect(rows).toHaveLength(onScreen);
    expect(rows[0]).toContain("Lone Star Cooling");
  });

  test("story 5: starting a run queues it and it shows up on /runs",
       async ({ page }) => {
    // The money path's success branch. It was verified by nothing: the suite
    // covered preview and cancel only. Safe to run here because the stack's
    // provider keys are unset, so the queued run fails at the first search
    // and spends nothing -- asserted below.
    const runs = new RunsPage(page);
    await runs.goto();
    const before = await runs.total();

    const search = new NewSearchPage(page);
    await search.goto();
    await search.choose("hvac", "tx", 1);
    await search.start();

    await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
    expect(await runs.total()).toBe(before + 1);
    // Newest first (repositories/runs.py orders created_at DESC), so the run
    // just queued is the top row.
    const newest = runs.rows().first();
    await expect(newest).toContainText(/queued|running|failed/);
    await expect(newest).toContainText("hvac");
    // Nothing has been spent. Asserted as "no non-zero amount" rather than a
    // fixed string, because the scheduler may pick the run up mid-assertion
    // and turn a null actual_cost into $0.000 -- both are zero spend, and
    // pinning either one would make this test race the scheduler.
    await expect(newest).not.toContainText(/\$0*[1-9]/);
  });

  test("story 5: /runs pages the same envelope /leads does", async ({ page }) => {
    // /runs rendered 50 rows and nothing else, so run 51 was unreachable.
    const runs = new RunsPage(page);
    await runs.goto();
    await expect(page.getByText(/page 1 of \d+/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
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
