// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { LeadOut, Page } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/leads",
}));

const apiGetMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({ apiGet: apiGetMock, ApiError: MockApiError }));

const { default: LeadsPage } = await import("@/app/leads/page");

const lead: LeadOut = {
  cid: "seed-01", name: "Uptown Air", city: "Houston", state: "TX",
  website: null, phone: null, segment: null, review_count: null,
  fit_score: 90, pain_score: 85, quadrant: "go_now", coverage: 0.9,
  outcome_status: "contacted",
};
const envelope: Page<LeadOut> = {
  items: [lead], total: 1, page: 1, page_size: 50, pages: 1, has_next: false,
};

async function renderLeads(sp: Record<string, string | undefined>) {
  apiGetMock.mockResolvedValueOnce(envelope);
  render(await LeadsPage({ searchParams: Promise.resolve(sp) }));
  return new URL(
    screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")!,
    "http://x",
  ).searchParams;
}

afterEach(() => apiGetMock.mockReset());

it("exports the set the screen is showing, not the whole table", async () => {
  // Reproduced live before this fix: outcome_status=contacted showed 1 row on
  // screen and downloaded 10. Only `quadrant` reached the export href.
  const params = await renderLeads({
    quadrant: "go_now", outcome_status: "contacted", state: "TX",
    min_fit: "40", min_pain: "30",
  });
  expect(Object.fromEntries(params)).toEqual({
    quadrant: "go_now", outcome_status: "contacted", state: "TX",
    min_fit: "40", min_pain: "30",
  });
});

/** Everything the list request carries except the paging, as strings, so it
 *  can be compared whole against the export href's query. */
function listFilters(): Record<string, string> {
  const [, query] = apiGetMock.mock.calls[0] as [string, Record<string, unknown>];
  return Object.fromEntries(
    Object.entries(query)
      .filter(([k, v]) => k !== "page" && k !== "page_size"
                          && v !== undefined && v !== "")
      .map(([k, v]) => [k, String(v)]));
}

it.each([
  // Named so a failure says which filter diverged.
  ["a filter neither side used to send", {
    quadrant: "all", vertical: "plumbing", ruleset_version: "plumbing_v1" }],
  ["the filters with visible controls", {
    quadrant: "nurture", outcome_status: "won" }],
  ["every filter at once", {
    quadrant: "go_now", vertical: "hvac", ruleset_version: "hvac_v1",
    state: "CA", outcome_status: "won", min_fit: "10", min_pain: "20" }],
  ["no filters at all", {}],
])("the export href and the list request cannot diverge: %s",
   async (_name, sp) => {
  // Not a hand-written key list: the first fix built the export link from
  // LEAD_FILTER_KEYS while the list request kept its own object, so
  // ?vertical=plumbing showed 10 rows on screen and downloaded 0 -- finding
  // 3's failure mode inverted. Comparing the two query strings WHOLE is the
  // only assertion that catches a key present on one side and absent on the
  // other, whichever side grows it.
  const params = await renderLeads(sp);
  expect(Object.fromEntries(params)).toEqual(listFilters());
});

it("sends no quadrant when the quadrant filter is 'all'", async () => {
  const params = await renderLeads({ quadrant: "all" });
  expect(params.has("quadrant")).toBe(false);
});

it("does not leak paging into the export", async () => {
  // The file is the whole filtered set, not the page on screen.
  const params = await renderLeads({ quadrant: "go_now", page: "2" });
  expect(params.has("page")).toBe(false);
  expect(params.has("page_size")).toBe(false);
});

it("derives the contacts export link from the same filters as the leads export", async () => {
  // Two independently-built query strings is exactly how the export drifted
  // from the list twice already (f7b1ef2, and its inverted repeat). The
  // contacts export link must never be a second hand-rolled copy.
  apiGetMock.mockResolvedValueOnce(envelope);
  render(await LeadsPage({ searchParams: Promise.resolve({
    quadrant: "go_now", vertical: "hvac", state: "TX",
    outcome_status: "contacted", min_fit: "40", min_pain: "30",
  }) }));
  const leadsHref = screen.getByRole("link", { name: "Export CSV" }).getAttribute("href")!;
  const contactsHref = screen.getByRole("link", { name: "Export contacts CSV" }).getAttribute("href")!;
  const leadsQuery = new URL(leadsHref, "http://x").searchParams;
  const contactsQuery = new URL(contactsHref, "http://x").searchParams;
  expect(Object.fromEntries(contactsQuery)).toEqual(Object.fromEntries(leadsQuery));
});

it("offers a harvest-emails button", async () => {
  apiGetMock.mockResolvedValueOnce(envelope);
  render(await LeadsPage({ searchParams: Promise.resolve({}) }));
  expect(screen.getByRole("button", { name: /harvest emails/i })).toBeInTheDocument();
});
