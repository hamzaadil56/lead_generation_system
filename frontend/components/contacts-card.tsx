"use client";
import { useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { ContactIn, ContactOut } from "@/lib/types";

const DESIGNATIONS = ["Owner", "General Manager", "Office Manager",
                      "Operations Manager", "Service Manager", "Dispatcher",
                      "Marketing Manager"];

export type ContactsCardActions = {
  add: (contact: ContactIn) => void | Promise<void>;
  confirm: (id: number) => void | Promise<void>;
  remove: (id: number) => void | Promise<void>;
  harvest: () => void | Promise<void>;
};

/** A single contact row. Confidence is never rendered as a number — the
 *  harvester's discovery_note is the decision-grade explanation, and a
 *  human-typed contact has confidence === null with nothing to fabricate. */
function ContactRow({ contact, onConfirm, onDelete }: {
  contact: ContactOut;
  onConfirm: (id: number) => void;
  onDelete: (id: number) => void;
}) {
  const displayName = contact.name ?? contact.email ?? "—";
  const unconfirmed = contact.confirmed_at === null;

  return (
    <li className="flex flex-wrap items-start justify-between gap-3 rounded-md border p-3">
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{displayName}</span>
          {contact.is_primary && <Badge variant="secondary">Primary</Badge>}
          {unconfirmed && <Badge variant="outline">Unconfirmed</Badge>}
        </div>
        <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm text-muted-foreground">
          {contact.role && <span>{contact.role}</span>}
          {contact.email && (
            <a href={`mailto:${contact.email}`} className="underline">
              {contact.email}
            </a>
          )}
          {contact.phone && <span>{contact.phone}</span>}
          {contact.linkedin_url && (
            <a href={contact.linkedin_url} target="_blank" rel="noreferrer"
               className="underline">
              LinkedIn
            </a>
          )}
        </div>
        {contact.discovery_note && (
          <p className="text-xs italic text-muted-foreground">{contact.discovery_note}</p>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {unconfirmed && (
          <Button type="button" size="sm" onClick={() => onConfirm(contact.id)}>
            Confirm
          </Button>
        )}
        <Button type="button" variant="ghost" size="sm" onClick={() => onDelete(contact.id)}>
          Delete
        </Button>
      </div>
    </li>
  );
}

/** The contacts card on the lead detail screen: the list of contacts, the
 *  confirm step that gates export (ADR-029), a free-text "add manually" form,
 *  and a harvest-from-website action. Purely presentational — `actions`
 *  carries the server calls, which Task 9 owns. Contacts are rendered in the
 *  order the API returned them (primary, then confirmed, then confidence
 *  descending); re-sorting here would create a second, driftable copy of
 *  that rule. */
export function ContactsCard({ contacts, actions, website }: {
  contacts: ContactOut[];
  actions: ContactsCardActions;
  website: string | null;
}) {
  const formRef = useRef<HTMLFormElement>(null);

  function handleAdd(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    const str = (key: string) => {
      const v = String(data.get(key) ?? "").trim();
      return v === "" ? null : v;
    };
    void actions.add({
      name: str("name"),
      role: str("role"),
      email: str("email"),
      phone: str("phone"),
      linkedin_url: str("linkedin_url"),
      is_primary: Boolean(data.get("is_primary")),
    });
    formRef.current?.reset();
  }

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-4 space-y-0">
        <CardTitle>Contacts</CardTitle>
        <div className="flex flex-col items-end gap-1">
          <Button type="button" variant="outline" disabled={!website}
                  onClick={() => actions.harvest()}>
            Harvest from website
          </Button>
          {!website && (
            <span className="text-xs text-muted-foreground">
              This lead has no website to harvest from.
            </span>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {contacts.length === 0 ? (
          <p className="py-6 text-center text-muted-foreground">No contacts yet.</p>
        ) : (
          <ul className="space-y-2">
            {contacts.map((c) => (
              <ContactRow key={c.id} contact={c}
                          onConfirm={actions.confirm} onDelete={actions.remove} />
            ))}
          </ul>
        )}

        <form ref={formRef} onSubmit={handleAdd} className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-2">
            <Label htmlFor="contact-name">Name</Label>
            <Input id="contact-name" name="name" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="contact-role">Designation</Label>
            <Input id="contact-role" name="role" list="designations" />
            <datalist id="designations">
              {DESIGNATIONS.map((d) => <option key={d} value={d} />)}
            </datalist>
          </div>
          <div className="space-y-2">
            <Label htmlFor="contact-email">Email</Label>
            <Input id="contact-email" name="email" type="email" />
          </div>
          <div className="space-y-2">
            <Label htmlFor="contact-phone">Phone</Label>
            <Input id="contact-phone" name="phone" />
          </div>
          <div className="space-y-2 sm:col-span-2">
            <Label htmlFor="contact-linkedin">LinkedIn URL</Label>
            <Input id="contact-linkedin" name="linkedin_url" type="url" />
          </div>
          <div className="flex items-center gap-2 sm:col-span-2">
            <Checkbox id="contact-is-primary" name="is_primary" />
            <Label htmlFor="contact-is-primary">Primary contact</Label>
          </div>
          <div className="sm:col-span-2">
            <Button type="submit">Add</Button>
          </div>
        </form>
      </CardContent>
      <CardFooter className="text-sm text-muted-foreground">
        Unconfirmed contacts are not included in the export.
      </CardFooter>
    </Card>
  );
}
