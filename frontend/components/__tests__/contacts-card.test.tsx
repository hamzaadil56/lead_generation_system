// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContactsCard, type ContactsCardActions } from "@/components/contacts-card";
import type { ContactOut } from "@/lib/types";

const harvested: ContactOut = {
  id: 1, name: null, role: null, email: "owner@leisuration.test",
  phone: null, linkedin_url: null, source: "website", confidence: 0.9,
  discovery_note: "matches the website domain", is_primary: false,
  confirmed_at: null, created_at: "2026-09-01T09:00:00",
};
const typed: ContactOut = {
  ...harvested, id: 2, name: "John Smith", role: "Owner",
  email: "john@leisuration.test", source: "manual", confidence: null,
  discovery_note: null, confirmed_at: "2026-09-01T09:00:00",
};

function makeActions(): ContactsCardActions {
  return {
    add: vi.fn(), confirm: vi.fn(), remove: vi.fn(), harvest: vi.fn(),
  };
}

afterEach(() => vi.clearAllMocks());

// Exact string, not a regex: the footer's fixed export-disclaimer line also
// contains the word "Unconfirmed", so a substring match would be ambiguous.
it("marks an unharvested contact as unconfirmed", () => {
  render(<ContactsCard contacts={[harvested]} actions={makeActions()} website={null} />);
  expect(screen.getByText("Unconfirmed")).toBeInTheDocument();
});

it("does not mark a confirmed contact", () => {
  render(<ContactsCard contacts={[typed]} actions={makeActions()} website={null} />);
  expect(screen.queryByText("Unconfirmed")).not.toBeInTheDocument();
});

it("says out loud that unconfirmed contacts are excluded from the export", () => {
  // Without this line the export silently drops rows and reads as broken.
  render(<ContactsCard contacts={[harvested]} actions={makeActions()} website={null} />);
  expect(screen.getByText(/not included in the export/i)).toBeInTheDocument();
});

it("shows the discovery note rather than a bare number", () => {
  render(<ContactsCard contacts={[harvested]} actions={makeActions()} website={null} />);
  expect(screen.getByText(/matches the website domain/i)).toBeInTheDocument();
});

it("renders no confidence for a manually typed contact", () => {
  // confidence is null, and a fabricated 100% would be a lie. The typed
  // fixture also has no discovery_note, so nothing confidence-shaped —
  // no float, no percentage — should render anywhere for this contact.
  render(<ContactsCard contacts={[typed]} actions={makeActions()} website={null} />);
  expect(screen.queryByText(/0\.9/)).not.toBeInTheDocument();
  expect(screen.queryByText(/90%/)).not.toBeInTheDocument();
  expect(screen.queryByText(/100%/)).not.toBeInTheDocument();
});

it("offers Confirm only on unconfirmed contacts", () => {
  render(<ContactsCard contacts={[harvested, typed]} actions={makeActions()} website={null} />);
  expect(screen.getAllByRole("button", { name: /^confirm$/i })).toHaveLength(1);
});

it("disables Harvest when the lead has no website", () => {
  render(<ContactsCard contacts={[]} actions={makeActions()} website={null} />);
  expect(screen.getByRole("button", { name: /harvest/i })).toBeDisabled();
});

it("enables Harvest when the lead has a website", () => {
  render(<ContactsCard contacts={[]} actions={makeActions()} website="https://leisuration.test" />);
  expect(screen.getByRole("button", { name: /harvest/i })).toBeEnabled();
});

it("labels every field in the add form", () => {
  // The axe assertion on the lead detail screen must keep passing.
  render(<ContactsCard contacts={[]} actions={makeActions()} website={null} />);
  expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/designation/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/^email$/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/^phone$/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/linkedin/i)).toBeInTheDocument();
  // The checkbox's accessible name comes from its associated <label>, not a
  // wrapping relationship, so assert via role rather than getByLabelText —
  // base-ui's checkbox exposes both the visible widget and a native hidden
  // input as "labelled by" the same text, which getByLabelText (rightly)
  // reports as an ambiguous match.
  expect(screen.getByRole("checkbox", { name: /primary contact/i })).toBeInTheDocument();
});

it("suggests common designations without restricting the field", () => {
  render(<ContactsCard contacts={[]} actions={makeActions()} website={null} />);
  const input = screen.getByLabelText(/designation/i);
  expect(input).toHaveAttribute("list");        // free text + datalist
  expect(input.tagName).toBe("INPUT");          // never a <select>
});

it("shows an empty state when there are no contacts", () => {
  render(<ContactsCard contacts={[]} actions={makeActions()} website={null} />);
  expect(screen.getByText(/no contacts/i)).toBeInTheDocument();
});

it("calls confirm with the contact id when Confirm is clicked", () => {
  const actions = makeActions();
  render(<ContactsCard contacts={[harvested]} actions={actions} website={null} />);
  fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));
  expect(actions.confirm).toHaveBeenCalledWith(harvested.id);
});

it("calls remove with the contact id when Delete is clicked", () => {
  const actions = makeActions();
  render(<ContactsCard contacts={[typed]} actions={actions} website={null} />);
  fireEvent.click(screen.getAllByRole("button", { name: /delete/i })[0]);
  expect(actions.remove).toHaveBeenCalledWith(typed.id);
});

it("calls harvest when the Harvest button is clicked", () => {
  const actions = makeActions();
  render(<ContactsCard contacts={[]} actions={actions} website="https://leisuration.test" />);
  fireEvent.click(screen.getByRole("button", { name: /harvest/i }));
  expect(actions.harvest).toHaveBeenCalled();
});

it("submits the add form with the typed values, and clears the field with no value", () => {
  const actions = makeActions();
  render(<ContactsCard contacts={[]} actions={actions} website={null} />);
  fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: "Jane Doe" } });
  fireEvent.change(screen.getByLabelText(/^email$/i), { target: { value: "jane@leisuration.test" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /primary contact/i }));
  fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
  expect(actions.add).toHaveBeenCalledWith({
    name: "Jane Doe", role: null, email: "jane@leisuration.test",
    phone: null, linkedin_url: null, is_primary: true,
  });
});

it("keeps what the user typed when add rejects", async () => {
  // The server rejects this routinely: 422 with neither name nor email (or
  // a malformed linkedin_url), and 409 when the address is already a
  // contact on this lead — an ordinary outcome once harvest has run, not an
  // edge case. Resetting the form regardless of outcome would silently
  // discard the user's typing on every one of those paths.
  const actions = makeActions();
  vi.mocked(actions.add).mockRejectedValue(new Error("409 Conflict"));
  render(<ContactsCard contacts={[]} actions={actions} website={null} />);
  const nameInput = screen.getByLabelText(/^name$/i) as HTMLInputElement;
  const emailInput = screen.getByLabelText(/^email$/i) as HTMLInputElement;
  fireEvent.change(nameInput, { target: { value: "Jane Doe" } });
  fireEvent.change(emailInput, { target: { value: "jane@leisuration.test" } });
  fireEvent.click(screen.getByRole("button", { name: /^add$/i }));
  await waitFor(() => expect(actions.add).toHaveBeenCalled());
  // Flush the rejected promise's microtask queue. There is nothing else to
  // await on: a reset that never happens produces no observable event, so
  // the assertion below is the only proof available.
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(nameInput.value).toBe("Jane Doe");
  expect(emailInput.value).toBe("jane@leisuration.test");
});

it("renders a mailto link for the contact's email", () => {
  render(<ContactsCard contacts={[typed]} actions={makeActions()} website={null} />);
  expect(screen.getByRole("link", { name: typed.email! }))
    .toHaveAttribute("href", `mailto:${typed.email}`);
});

it("uses the email as the row's name when no name was given", () => {
  render(<ContactsCard contacts={[harvested]} actions={makeActions()} website={null} />);
  // The row's name element is a <span>; the row also independently renders
  // the same email as a <a href="mailto:..."> link further down. Scoping to
  // "span" targets only the name fallback — an assertion against the email
  // text anywhere in the row would pass on the mailto link alone even if
  // the name-fallback logic were deleted entirely.
  expect(screen.getByText(harvested.email!, { selector: "span" })).toBeInTheDocument();
});

it("still shows the typed name, not the email, when a name is given", () => {
  render(<ContactsCard contacts={[typed]} actions={makeActions()} website={null} />);
  expect(screen.getByText(typed.name!, { selector: "span" })).toBeInTheDocument();
  expect(screen.queryByText(typed.email!, { selector: "span" })).not.toBeInTheDocument();
});
