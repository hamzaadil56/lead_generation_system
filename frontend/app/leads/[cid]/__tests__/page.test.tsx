// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { LeadDetailOut, ManualFactsOut } from "@/lib/types";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));

const apiGetMock = vi.fn();
const apiSendMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({
  apiGet: apiGetMock, apiSend: apiSendMock, ApiError: MockApiError,
}));

const { default: LeadDetail } = await import("@/app/leads/[cid]/page");

const detail = (facts: ManualFactsOut | null): LeadDetailOut => ({
  lead: {
    cid: "seed-01", name: "Uptown Air", city: "Houston", state: "TX",
    website: null, phone: null, segment: null, review_count: null,
    fit_score: 90, pain_score: 85, quadrant: "go_now", coverage: 0.9,
    outcome_status: null,
  },
  score: null, reasons: [], signals: {}, evidence: [], manual_facts: facts,
  contacts: [],
});

const NOTHING_RESEARCHED: ManualFactsOut = {
  estimated_employees: null, technician_count: null,
  has_office_admin: null, owner_growth_focused: null, notes: null,
};

async function renderPage(facts: ManualFactsOut | null) {
  apiGetMock.mockResolvedValueOnce(detail(facts));
  apiSendMock.mockResolvedValue({ cid: "seed-01" });
  render(await LeadDetail({ params: Promise.resolve({ cid: "seed-01" }) }));
}

/** The manual-facts form. Scoped because the outcome form beside it has a
 *  "Notes" field of its own. */
const factsForm = () => screen.getByRole("button", { name: "Save facts" })
  .closest("form") as HTMLFormElement;

/** Submit the manual-facts form and hand back the body that reached the API. */
async function saveFacts(): Promise<Record<string, unknown>> {
  fireEvent.submit(factsForm());
  await waitFor(() => expect(apiSendMock).toHaveBeenCalled());
  const call = apiSendMock.mock.calls.find(
    ([, path]) => String(path).includes("manual-facts"));
  return call?.[2] as Record<string, unknown>;
}

afterEach(() => { apiGetMock.mockReset(); apiSendMock.mockReset(); });

it("prefills an unresearched boolean fact as unknown, not as no", async () => {
  await renderPage(NOTHING_RESEARCHED);
  expect(screen.getByLabelText("Has an office admin")).toHaveValue("unknown");
  expect(screen.getByLabelText("Owner is growth-focused")).toHaveValue("unknown");
});

it.each([
  [true, "yes"], [false, "no"],
] as const)("prefills a researched %s as %s", async (stored, shown) => {
  await renderPage({ ...NOTHING_RESEARCHED, has_office_admin: stored });
  expect(screen.getByLabelText("Has an office admin")).toHaveValue(shown);
});

it("saving with a boolean left at unknown sends null, never false", async () => {
  // The defect: a checkbox posts nothing when unticked, and the action read
  // that as `=== "on"` -> false. Typing only a note therefore fabricated two
  // research findings in `manual_facts`, the one permanent table, and made
  // null unreachable from the UI forever.
  await renderPage(NOTHING_RESEARCHED);
  fireEvent.change(within(factsForm()).getByLabelText("Notes"), {
    target: { value: "called them" },
  });
  const body = await saveFacts();
  expect(body.has_office_admin).toBeNull();
  expect(body.owner_growth_focused).toBeNull();
  expect(body.notes).toBe("called them");
});

it("choosing no sends an explicit false", async () => {
  await renderPage(NOTHING_RESEARCHED);
  fireEvent.change(screen.getByLabelText("Has an office admin"),
                   { target: { value: "no" } });
  const body = await saveFacts();
  expect(body.has_office_admin).toBe(false);
  expect(body.owner_growth_focused).toBeNull();
});

it("a partial save does not disturb the fields it did not touch", async () => {
  await renderPage({
    estimated_employees: 12, technician_count: 4,
    has_office_admin: true, owner_growth_focused: false, notes: "prior note",
  });
  fireEvent.change(screen.getByLabelText("Estimated employees"),
                   { target: { value: "13" } });
  const body = await saveFacts();
  expect(body).toMatchObject({
    estimated_employees: 13, technician_count: 4,
    has_office_admin: true, owner_growth_focused: false, notes: "prior note",
  });
});
