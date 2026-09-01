import Link from "next/link";
import { LeadsTable } from "@/components/leads-table";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { apiGet, ApiError } from "@/lib/api";
import { LEAD_FILTER_KEYS } from "@/lib/filters";
import type { LeadOut, Page } from "@/lib/types";

const QUADRANTS = ["go_now", "nurture", "low_fit", "cold"];
const OUTCOMES = ["new", "contacted", "replied", "booked", "won", "lost"];

export default async function LeadsPage({
  searchParams,
}: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  // Default to go_now: the leads worth emailing today (ADR-004).
  const quadrant = sp.quadrant ?? "go_now";
  const page = Number(sp.page ?? 1);

  let data: Page<LeadOut>;
  try {
    data = await apiGet<Page<LeadOut>>("/leads", {
      quadrant: quadrant === "all" ? undefined : quadrant,
      state: sp.state, outcome_status: sp.outcome_status,
      min_fit: sp.min_fit, min_pain: sp.min_pain,
      page, page_size: 50,
    });
  } catch (e) {
    const msg = e instanceof ApiError ? e.detail : "Something went wrong.";
    return <p role="alert" className="py-12 text-center text-destructive">{msg}</p>;
  }

  // The CSV must be the set on screen. Every filter the list request above
  // used is forwarded; `page`/`page_size` are not, because the file is the
  // whole filtered set rather than the page being viewed.
  const exportParams = new URLSearchParams();
  if (quadrant !== "all") exportParams.set("quadrant", quadrant);
  for (const key of LEAD_FILTER_KEYS) {
    if (key === "quadrant") continue;      // handled above: "all" means none
    const value = sp[key];
    if (value) exportParams.set(key, value);
  }
  const exportHref = `/api/export?${exportParams.toString()}`;

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
