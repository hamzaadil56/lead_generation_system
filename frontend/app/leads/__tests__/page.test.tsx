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

it("asks the list endpoint for exactly what it asks the export for", async () => {
  const sp = { quadrant: "nurture", outcome_status: "won", state: "CA",
               min_fit: "10", min_pain: "20" };
  const params = await renderLeads(sp);
  const [, listQuery] = apiGetMock.mock.calls[0];
  for (const key of ["quadrant", "outcome_status", "state", "min_fit", "min_pain"]) {
    expect(params.get(key)).toBe(String(listQuery[key]));
  }
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
