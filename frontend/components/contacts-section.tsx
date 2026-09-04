"use client";
import { useState } from "react";
import { ContactsCard, type ContactsCardActions } from "@/components/contacts-card";
import type { ContactIn, ContactOut } from "@/lib/types";

/** Bridges the presentational ContactsCard to the server actions Task 9
 *  owns. The one thing this file exists for: ContactsCard.handleAdd swallows
 *  a rejected add (`.catch(() => {})`, deliberately, so the form the user
 *  just typed into is never wiped by a routine failure) — which means the
 *  message from a 409 duplicate-address or 422 validation error has to be
 *  shown from here, before that swallow, not from ContactsCard itself. */
export function ContactsSection({ contacts, website, addContact, confirmContact,
                                  deleteContact, harvestContacts }: {
  contacts: ContactOut[];
  website: string | null;
  addContact: (contact: ContactIn) => Promise<{ error: string } | undefined>;
  confirmContact: (id: number) => Promise<void>;
  deleteContact: (id: number) => Promise<void>;
  harvestContacts: () => Promise<void>;
}) {
  const [addError, setAddError] = useState<string | null>(null);

  const actions: ContactsCardActions = {
    async add(contact) {
      const result = await addContact(contact);
      if (result?.error) {
        setAddError(result.error);
        // Reject so ContactsCard's own (deliberately silent) catch skips the
        // form reset. The message above is what the user actually sees;
        // this throw only stops the form being wiped under them.
        throw new Error(result.error);
      }
      setAddError(null);
    },
    confirm: confirmContact,
    remove: deleteContact,
    harvest: harvestContacts,
  };

  return (
    <div className="space-y-2">
      {addError && (
        <p role="alert" className="text-sm text-destructive">{addError}</p>
      )}
      <ContactsCard contacts={contacts} actions={actions} website={website} />
    </div>
  );
}
