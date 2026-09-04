import { revalidatePath } from "next/cache";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ContactsSection } from "@/components/contacts-section";
import { CoverageIndicator } from "@/components/coverage-indicator";
import { EvidenceQuote } from "@/components/evidence-quote";
import { ReasonList, SignalList } from "@/components/lead-forms";
import { QuadrantBadge } from "@/components/quadrant-badge";
import { ScorePair } from "@/components/score-pair";
import { TriStateField } from "@/components/tri-state-field";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { apiDelete, apiGet, apiSend, ApiError } from "@/lib/api";
import { triStateToBool } from "@/lib/tri-state";
import type { ContactIn, LeadDetailOut } from "@/lib/types";

const OUTCOMES = ["new", "contacted", "replied", "booked", "won", "lost"];

export default async function LeadDetail({
  params,
}: { params: Promise<{ cid: string }> }) {
  const { cid } = await params;

  let detail: LeadDetailOut;
  try {
    detail = await apiGet<LeadDetailOut>(`/leads/${encodeURIComponent(cid)}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    return <p role="alert" className="text-destructive">
      {e instanceof ApiError ? e.detail : "Something went wrong."}
    </p>;
  }

  const { lead, score, reasons, signals, evidence, contacts } = detail;
  // Prefill from what is stored: an empty form would both hide the saved
  // values and null every untouched column on the next save.
  const facts = detail.manual_facts;

  async function saveOutcome(form: FormData) {
    "use server";
    await apiSend("PUT", `/leads/${encodeURIComponent(cid)}/outcome`, {
      status: String(form.get("status")),
      notes: String(form.get("notes") || "") || null,
    });
    revalidatePath(`/leads/${cid}`);
  }

  async function saveManualFacts(form: FormData) {
    "use server";
    const num = (k: string) => {
      const v = String(form.get(k) ?? "").trim();
      return v === "" ? null : Number(v);
    };
    await apiSend("PUT", `/leads/${encodeURIComponent(cid)}/manual-facts`, {
      estimated_employees: num("estimated_employees"),
      technician_count: num("technician_count"),
      // Three-state, not a checkbox: `null` means nobody has researched
      // this, and must stay reachable. See lib/tri-state.ts.
      has_office_admin: triStateToBool(form.get("has_office_admin")),
      owner_growth_focused: triStateToBool(form.get("owner_growth_focused")),
      notes: String(form.get("notes") || "") || null,
    });
    revalidatePath(`/leads/${cid}`);
  }

  // ContactsCard calls these directly with parsed values (its own form
  // handling already turned FormData into ContactIn / a contact id) rather
  // than via a native <form action>, so each takes a plain argument instead
  // of a FormData.
  async function addContact(contact: ContactIn) {
    "use server";
    try {
      await apiSend("POST", `/leads/${encodeURIComponent(cid)}/contacts`, contact);
    } catch (e) {
      // A duplicate address is an ordinary outcome, not a crash: the address
      // may already have been harvested. Surface it on the form instead of
      // throwing -- ContactsSection turns this into the inline message, and
      // still rejects afterwards so ContactsCard's own form-reset is skipped.
      if (e instanceof ApiError && (e.status === 409 || e.status === 422)) {
        return { error: e.detail };
      }
      throw e;
    }
    revalidatePath(`/leads/${cid}`);
  }

  async function confirmContact(id: number) {
    "use server";
    await apiSend("POST", `/contacts/${id}/confirm`, undefined);
    revalidatePath(`/leads/${cid}`);
  }

  async function deleteContact(id: number) {
    "use server";
    await apiDelete(`/contacts/${id}`);
    revalidatePath(`/leads/${cid}`);
  }

  async function harvestContacts() {
    "use server";
    await apiSend("POST", `/leads/${encodeURIComponent(cid)}/contacts/harvest`, undefined);
    revalidatePath(`/leads/${cid}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">{lead.name}</h1>
          <p className="text-muted-foreground">
            {[lead.city, lead.state].filter(Boolean).join(", ") || "—"}
            {lead.website && <> · <a href={lead.website} target="_blank"
              rel="noreferrer" className="underline">{lead.website}</a></>}
            {/* phone is null when unvalidated (ADR-013) — render nothing, no fallback */}
            {lead.phone && <> · <span className="font-mono">{lead.phone}</span></>}
          </p>
        </div>
        <Button variant="outline" render={<Link href="/leads" />}>Back to leads</Button>
      </div>

      {/* score === null means not scored yet. Do NOT read lead.quadrant here:
          it is a placeholder "cold" for unscored leads. */}
      {score === null ? (
        <Card><CardContent className="py-6 text-muted-foreground">
          This lead has not been scored yet.
        </CardContent></Card>
      ) : (
        <Card>
          <CardHeader className="flex-row items-center gap-4 space-y-0">
            <ScorePair fit={score.fit_score} pain={score.pain_score} />
            <QuadrantBadge quadrant={score.quadrant} />
            <CoverageIndicator coverage={score.coverage} />
            <span className="ml-auto text-sm text-muted-foreground">
              {score.ruleset_version}
            </span>
          </CardHeader>
          <CardContent><ReasonList reasons={reasons} /></CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Signals</CardTitle></CardHeader>
        <CardContent><SignalList signals={signals} /></CardContent>
      </Card>

      <ContactsSection contacts={contacts} website={lead.website}
                       addContact={addContact} confirmContact={confirmContact}
                       deleteContact={deleteContact} harvestContacts={harvestContacts} />

      {evidence.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Review evidence</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {evidence.map((e, i) => (
              <EvidenceQuote key={i} text={e.text} rating={e.rating}
                             publishedAt={e.published_at} />
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Outcome</CardTitle></CardHeader>
          <CardContent>
            <form action={saveOutcome} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="status">Status</Label>
                <select id="status" name="status" defaultValue={lead.outcome_status ?? "new"}
                        className="w-full rounded-md border bg-background p-2">
                  {OUTCOMES.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              </div>
              <div className="space-y-2">
                <Label htmlFor="outcome-notes">Notes</Label>
                <Textarea id="outcome-notes" name="notes" rows={3} />
              </div>
              <Button type="submit">Save outcome</Button>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Manual facts</CardTitle></CardHeader>
          <CardContent>
            <form action={saveManualFacts} className="space-y-3">
              <div className="space-y-2">
                <Label htmlFor="estimated_employees">Estimated employees</Label>
                <Input id="estimated_employees" name="estimated_employees"
                       type="number" min={0} max={100000}
                       defaultValue={facts?.estimated_employees ?? ""} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="technician_count">Technicians</Label>
                <Input id="technician_count" name="technician_count"
                       type="number" min={0} max={10000}
                       defaultValue={facts?.technician_count ?? ""} />
              </div>
              <TriStateField name="has_office_admin" label="Has an office admin"
                             value={facts?.has_office_admin} />
              <TriStateField name="owner_growth_focused"
                             label="Owner is growth-focused"
                             value={facts?.owner_growth_focused} />
              <div className="space-y-2">
                <Label htmlFor="facts-notes">Notes</Label>
                <Textarea id="facts-notes" name="notes" rows={3}
                          defaultValue={facts?.notes ?? ""} />
              </div>
              <Button type="submit">Save facts</Button>
            </form>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
