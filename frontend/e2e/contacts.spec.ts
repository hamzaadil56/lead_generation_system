import { expect, test } from "@playwright/test";
import { LeadDetailPage } from "./pages/lead-detail";
import { LeadsPage } from "./pages/leads";
import { LoginPage } from "./pages/login";

/**
 * Contact discovery, end to end, against the real API and a real database --
 * never mocked. A mocked response echoes whatever the form sends, which is
 * exactly why the earlier vitest suite caught neither the missing
 * manual-facts read path nor the tri-state form flattening three states into
 * two: nothing here can hide a frontend/backend contract mismatch the way a
 * stub would.
 *
 * seed-01 is the fixture the harvest tests share: `seed_demo` gives it a
 * RawPayload containing one address the extractor should keep
 * (`owner@seed-01.test`, which matches the website domain) and one it must
 * always reject (`noreply@seed-01.test`, a junk local-part). Every test below
 * that touches it calls `harvestContacts()` itself rather than relying on an
 * earlier test having done so -- harvesting is insert-only and skips
 * addresses that already exist, so repeating it is always safe -- so each
 * test remains meaningful in isolation.
 *
 * The exception is the confirm gate pair at the end: confirming is a one-way
 * transition (there is no "unconfirm" endpoint), so "appears unconfirmed"
 * and "the export excludes it" can only be true for a given contact once. The
 * last test therefore deletes the contact it just confirmed, restoring
 * seed-01 to zero contacts so a later run of this file harvests it fresh
 * again. Tests in this file rely on running in the order written --
 * `playwright.config.ts` sets `fullyParallel: false` and `workers: 1`
 * specifically because the whole suite shares one seeded database.
 */
test.describe("signed in", () => {
  test.beforeEach(async ({ page }) => {
    const login = new LoginPage(page);
    await login.goto();
    await login.signIn();
    await expect(page).toHaveURL(/\/leads/);
  });

  test("adding a contact makes it appear on the lead detail", async ({ page }) => {
    // seed-04: untouched by every other spec, so this owns it end to end.
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-04");
    const name = "Jamie Rivera";
    // Time-suffixed so a re-run of this file (a persistent, seeded database
    // outlives any one run) does not collide with the address it created
    // last time and get rejected as a duplicate. Scoping the row lookup on
    // this unique email, not on the fixed name, matters too: a second run
    // that reused `name` to find the row would hit Playwright's strict-mode
    // check the moment a THIRD run left more than one "Jamie Rivera" on the
    // page -- the email is what stays unique.
    const email = `jamie.${Date.now()}@seed-04.test`;
    await detail.addContact({ name, email });
    const row = detail.contactRow(email);
    await expect(row).toBeVisible();
    await expect(row).toContainText(name);
  });

  test("a harvested contact appears unconfirmed, with its discovery note",
      async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    await detail.harvestContacts();

    const row = detail.contactRow("owner@seed-01.test");
    await expect(row).toBeVisible();
    await expect(row).toContainText("Unconfirmed");
    // The extractor's own wording (app/domain/extractors/emails.py
    // MATCHES_WEBSITE) -- seed-01's website is https://seed-01.test, so the
    // address's domain matches it exactly.
    await expect(row).toContainText(/matches the website domain/i);
  });

  test("the junk address in the seeded HTML is never harvested", async ({ page }) => {
    // noreply@ is a role-account local-part on the extractor's junk-prefix
    // denylist -- rejected before scoring, so it must never become a
    // contact, however many times this lead is harvested.
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    await detail.harvestContacts();
    await expect(page.getByText("noreply@seed-01.test")).toHaveCount(0);
  });

  test("adding an address that was already harvested shows a message, not an error page",
      async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    await detail.harvestContacts();
    // owner@seed-01.test is already a contact on this business (harvested
    // above). Adding it again by hand must surface the API's 409 as an
    // inline message, not blow up the page.
    await detail.addContact({ email: "owner@seed-01.test" });
    // ContactsSection renders this message as a sibling of ContactsCard, not
    // inside its <form> (unlike LoginPage's rejection, which IS inside a
    // form) -- matched on text directly rather than role, since Next's own
    // always-present route announcer (`role="alert"`, empty text) would
    // otherwise make a bare `getByRole("alert")` a strict-mode violation.
    await expect(page.getByText(/already a contact/i)).toBeVisible();
    // Still on the lead detail screen, not a Next.js error boundary.
    await expect(page.getByRole("heading", { name: "Uptown Air & Heat" }))
      .toBeVisible();
  });

  test("the contacts export does NOT contain an unconfirmed contact", async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    await detail.harvestContacts();
    await expect(detail.contactRow("owner@seed-01.test")).toContainText("Unconfirmed");

    await page.goto("/leads?quadrant=all");
    const rows = await new LeadsPage(page).exportContactsCsvRows();
    expect(rows.some((r) => r.includes("owner@seed-01.test"))).toBe(false);
  });

  test("after Confirm, the contacts export DOES contain it", async ({ page }) => {
    const detail = new LeadDetailPage(page);
    await detail.goto("seed-01");
    await detail.harvestContacts();
    await detail.confirmContact("owner@seed-01.test");
    await expect(detail.contactRow("owner@seed-01.test"))
      .not.toContainText("Unconfirmed");

    await page.goto("/leads?quadrant=all");
    const rows = await new LeadsPage(page).exportContactsCsvRows();
    expect(rows.some((r) => r.includes("owner@seed-01.test"))).toBe(true);

    // Restore seed-01 to zero contacts so a later run of this file harvests
    // owner@seed-01.test fresh (and unconfirmed) again -- see the file
    // comment above. Confirming is one-way; deleting is the only way back.
    await detail.goto("seed-01");
    await detail.deleteContact("owner@seed-01.test");
    await expect(detail.contactRow("owner@seed-01.test")).toHaveCount(0);
  });

  test("the leads list export link carries the current filters", async ({ page }) => {
    // Both export links are built from the same filter object the screen
    // itself renders from (app/leads/page.tsx) -- a dropped filter here is
    // exactly how the leads export once shipped honouring one filter of
    // five (commit f7b1ef2), and the contacts export repeats that
    // construction, so both are checked.
    await page.goto("/leads?quadrant=cold&outcome_status=lost");
    const leadsHref = await page.getByRole("link", { name: "Export CSV" })
      .getAttribute("href");
    const contactsHref = await page.getByRole("link", { name: "Export contacts CSV" })
      .getAttribute("href");
    for (const href of [leadsHref, contactsHref]) {
      expect(href).toContain("quadrant=cold");
      expect(href).toContain("outcome_status=lost");
    }
  });
});
