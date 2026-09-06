// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { ContactOut, LeadDetailOut, ManualFactsOut } from "@/lib/types";

vi.mock("next/cache", () => ({ revalidatePath: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: vi.fn() }));

const apiGetMock = vi.fn();
const apiSendMock = vi.fn();
const apiDeleteMock = vi.fn();
class MockApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}
vi.mock("@/lib/api", () => ({
  apiGet: apiGetMock, apiSend: apiSendMock, apiDelete: apiDeleteMock,
  ApiError: MockApiError,
}));

const { default: LeadDetail } = await import("@/app/leads/[cid]/page");

const detail = (facts: ManualFactsOut | null, contacts: ContactOut[] = []): LeadDetailOut => ({
  lead: {
    cid: "seed-01", name: "Uptown Air", city: "Houston", state: "TX",
    website: null, phone: null, segment: null, review_count: null,
    fit_score: 90, pain_score: 85, quadrant: "go_now", coverage: 0.9,
    outcome_status: null,
  },
  score: null, reasons: [], signals: {}, evidence: [], manual_facts: facts,
  contacts,
});

const harvestedContact: ContactOut = {
  id: 1, name: null, role: null, email: "owner@uptownair.test",
  phone: null, linkedin_url: null, source: "website", confidence: 0.9,
  discovery_note: "matches the website domain", is_primary: false,
  confirmed_at: null, created_at: "2026-09-01T09:00:00",
};

const NOTHING_RESEARCHED: ManualFactsOut = {
  estimated_employees: null, technician_count: null,
  has_office_admin: null, owner_growth_focused: null, notes: null,
};

async function renderPage(facts: ManualFactsOut | null, contacts: ContactOut[] = []) {
  apiGetMock.mockResolvedValueOnce(detail(facts, contacts));
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

afterEach(() => {
  apiGetMock.mockReset(); apiSendMock.mockReset(); apiDeleteMock.mockReset();
});

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

it("renders the contacts card with the lead's contacts", async () => {
  await renderPage(NOTHING_RESEARCHED, [harvestedContact]);
  expect(screen.getByText("Contacts")).toBeInTheDocument();
  expect(screen.getByText(harvestedContact.email!, { selector: "span" }))
    .toBeInTheDocument();
});

/** Fill in and submit the Contacts card's "add" form. */
function submitAddContact(name: string, email: string) {
  fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: name } });
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
}

it("posts a new contact to the lead's contacts endpoint", async () => {
  await renderPage(NOTHING_RESEARCHED, []);
  submitAddContact("Jane Doe", "jane@uptownair.test");
  await waitFor(() => expect(apiSendMock).toHaveBeenCalledWith(
    "POST", "/leads/seed-01/contacts", expect.objectContaining({
      name: "Jane Doe", email: "jane@uptownair.test",
    })));
});

it("surfaces a 409 from adding a duplicate contact as an inline message, not a crash", async () => {
  // A duplicate address is routine once harvest has already found it -- the
  // add form's own .catch(() => {}) swallows the rejection so the user's
  // typing survives, which means the message has to come from somewhere
  // else: the server action must show it before that catch runs.
  await renderPage(NOTHING_RESEARCHED, []);
  apiSendMock.mockImplementation((_method: string, path: string) => {
    if (String(path).includes("/contacts")) {
      return Promise.reject(new MockApiError(409, "that email is already a contact for this lead"));
    }
    return Promise.resolve({});
  });
  submitAddContact("Jane Doe", "jane@uptownair.test");
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "that email is already a contact for this lead");
  // Nothing above this should have thrown out to an error boundary -- the
  // form and its fields are still on the page, still holding what was typed.
  expect(screen.getByLabelText(/^name$/i)).toHaveValue("Jane Doe");
});

it("confirms a contact through the contacts endpoint", async () => {
  await renderPage(NOTHING_RESEARCHED, [harvestedContact]);
  fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
  await waitFor(() => expect(apiSendMock).toHaveBeenCalledWith(
    "POST", "/contacts/1/confirm", undefined));
});

it("deletes a contact through apiDelete", async () => {
  apiDeleteMock.mockResolvedValue(undefined);
  await renderPage(NOTHING_RESEARCHED, [harvestedContact]);
  fireEvent.click(screen.getByRole("button", { name: /delete/i }));
  await waitFor(() => expect(apiDeleteMock).toHaveBeenCalledWith("/contacts/1"));
});

it("harvests contacts for this lead from its website", async () => {
  const detailWithWebsite = detail(NOTHING_RESEARCHED, []);
  detailWithWebsite.lead.website = "https://uptownair.test";
  apiGetMock.mockResolvedValueOnce(detailWithWebsite);
  apiSendMock.mockResolvedValue({ created: 1, skipped: 0, candidates: 1 });
  render(await LeadDetail({ params: Promise.resolve({ cid: "seed-01" }) }));
  fireEvent.click(screen.getByRole("button", { name: /harvest/i }));
  await waitFor(() => expect(apiSendMock).toHaveBeenCalledWith(
    "POST", "/leads/seed-01/contacts/harvest", undefined));
});
