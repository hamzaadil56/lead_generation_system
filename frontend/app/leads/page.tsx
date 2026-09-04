import { revalidatePath } from "next/cache";
import Link from "next/link";
import { HarvestContactsButton, type HarvestResult } from "@/components/harvest-contacts-button";
import { LeadsTable } from "@/components/leads-table";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { apiGet, apiSend, ApiError } from "@/lib/api";
import { LEAD_FILTER_KEYS } from "@/lib/filters";
import type { BulkHarvestOut, LeadOut, Page } from "@/lib/types";

const QUADRANTS = ["go_now", "nurture", "low_fit", "cold"];
const OUTCOMES = ["new", "contacted", "replied", "booked", "won", "lost"];

export default async function LeadsPage({
  searchParams,
}: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  // Default to go_now: the leads worth emailing today (ADR-004).
  const quadrant = sp.quadrant ?? "go_now";
  const page = Number(sp.page ?? 1);

  // ONE set of filter values, read by both the list request and the export
  // link below. Two parallel constructions is what shipped an export that
  // honoured one filter of five -- and then, when the link alone was rebuilt
  // from LEAD_FILTER_KEYS while this request kept a hand-written object,
  // reopened the same bug inverted: ?vertical=plumbing showed 10 rows on
  // screen and downloaded 0. Anything derived from this object cannot
  // describe a different set from anything else derived from it.
  const filters: Record<string, string | undefined> = {};
  for (const key of LEAD_FILTER_KEYS) filters[key] = sp[key];
  // "all" is a word in the UI, not a value the API takes: it means no
  // quadrant filter at all.
  filters.quadrant = quadrant === "all" ? undefined : quadrant;

  let data: Page<LeadOut>;
  try {
    data = await apiGet<Page<LeadOut>>("/leads", {
      ...filters, page, page_size: 50,
    });
  } catch (e) {
    const msg = e instanceof ApiError ? e.detail : "Something went wrong.";
    return <p role="alert" className="py-12 text-center text-destructive">{msg}</p>;
  }

  // The same filters, minus the paging: the file is the whole filtered set,
  // not the page being viewed. `lib/api.ts` drops undefined and "" from the
  // list request, so this drops them too.
  const exportParams = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value) exportParams.set(key, value);
  }
  const exportHref = `/api/export?${exportParams.toString()}`;
  // Same exportParams, same one filter object underneath -- a second,
  // independently-built query string here is exactly how this drifted twice
  // already (see the comment on `filters` above).
  const contactsExportHref = `/api/contacts-export?${exportParams.toString()}`;

  async function harvestContacts(): Promise<HarvestResult> {
    "use server";
    try {
      const result = await apiSend<BulkHarvestOut>(
        "POST", "/contacts/harvest", undefined, filters);
      revalidatePath("/leads");
      return { created: result.created, error: null };
    } catch (e) {
      return {
        created: null,
        error: e instanceof ApiError ? e.detail : "Could not harvest contacts.",
      };
    }
  }

  const link = (over: Record<string, string>) => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries({ ...sp, ...over })) if (v) p.set(k, v);
    return `/leads?${p.toString()}`;
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm text-muted-foreground">Quadrant:</span>
        {["all", ...QUADRANTS].map((q) => (
          <Button key={q} size="sm"
                  variant={q === quadrant ? "default" : "outline"}
                  render={<Link href={link({ quadrant: q, page: "1" })} />}>
            {q.replace(/_/g, " ")}
          </Button>
        ))}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-sm text-muted-foreground">
            {data.total} lead{data.total === 1 ? "" : "s"}
          </span>
          <Button size="sm" variant="secondary"
                  render={<a href={exportHref} />}>
            Export CSV
          </Button>
          <Button size="sm" variant="secondary"
                  render={<a href={contactsExportHref} />}>
            Export contacts CSV
          </Button>
          <HarvestContactsButton action={harvestContacts} />
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="text-sm text-muted-foreground">Outcome:</span>
        {["any", ...OUTCOMES].map((o) => (
          <Button key={o} size="sm"
                  variant={o === (sp.outcome_status ?? "any") ? "default" : "ghost"}
                  render={<Link href={link({ outcome_status: o === "any" ? "" : o, page: "1" })} />}>
            {o}
          </Button>
        ))}
      </div>

      <LeadsTable rows={data.items} />

      <Pagination page={data.page} pages={data.pages}
                  prevHref={data.page <= 1 ? null : link({ page: String(data.page - 1) })}
                  nextHref={data.has_next ? link({ page: String(data.page + 1) }) : null} />
    </div>
  );
}
