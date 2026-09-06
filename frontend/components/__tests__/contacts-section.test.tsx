// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ContactsSection } from "@/components/contacts-section";
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

afterEach(() => vi.clearAllMocks());

function renderSection(overrides: Partial<{
  contacts: ContactOut[];
  confirmContact: (id: number) => Promise<{ error: string } | undefined>;
  deleteContact: (id: number) => Promise<{ error: string } | undefined>;
}> = {}) {
  const addContact = vi.fn();
  const confirmContact = overrides.confirmContact ?? vi.fn();
  const deleteContact = overrides.deleteContact ?? vi.fn();
  const harvestContacts = vi.fn();
  render(
    <ContactsSection
      contacts={overrides.contacts ?? [harvested]}
      website={null}
      addContact={addContact}
      confirmContact={confirmContact}
      deleteContact={deleteContact}
      harvestContacts={harvestContacts}
    />
  );
  return { addContact, confirmContact, deleteContact, harvestContacts };
}

// This is the regression test for the "confirm fails silently" defect: with
// the `.catch` / error-surfacing removed, confirmContact's rejection would
// either blow up as an unhandled promise rejection or leave the screen with
// nothing but the still-"Unconfirmed" badge -- no role="alert" would ever
// appear. Only the visible alert proves the failure was actually surfaced.
it("shows a visible alert when confirming a contact fails", async () => {
  const confirmContact = vi.fn().mockResolvedValue({ error: "Contact not found." });
  renderSection({ confirmContact });

  fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

  await waitFor(() => expect(confirmContact).toHaveBeenCalledWith(harvested.id));
  expect(await screen.findByRole("alert")).toHaveTextContent("Contact not found.");
});

// Same defect shape on delete: a 404/500/network failure must not vanish.
it("shows a visible alert when deleting a contact fails", async () => {
  const deleteContact = vi.fn().mockResolvedValue({ error: "The server hit an error. Try again." });
  renderSection({ contacts: [typed], deleteContact });

  fireEvent.click(screen.getAllByRole("button", { name: /delete/i })[0]);

  await waitFor(() => expect(deleteContact).toHaveBeenCalledWith(typed.id));
  expect(await screen.findByRole("alert"))
    .toHaveTextContent("The server hit an error. Try again.");
});

it("does not show an alert when confirm succeeds", async () => {
  const confirmContact = vi.fn().mockResolvedValue(undefined);
  renderSection({ confirmContact });

  fireEvent.click(screen.getByRole("button", { name: /^confirm$/i }));

  await waitFor(() => expect(confirmContact).toHaveBeenCalled());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
