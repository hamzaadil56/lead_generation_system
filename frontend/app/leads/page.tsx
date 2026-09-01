import Link from "next/link";
import { LeadsTable } from "@/components/leads-table";
import { Button } from "@/components/ui/button";
import { apiGet, ApiError } from "@/lib/api";
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
                  render={<a href={`/api/export?${new URLSearchParams(
                    quadrant === "all" ? {} : { quadrant }).toString()}`} />}>
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

      <div className="flex items-center justify-between">
        <span className="text-sm text-muted-foreground">
          Page {data.page} of {data.pages}
        </span>
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={data.page <= 1}
                  render={data.page <= 1 ? undefined : <Link href={link({ page: String(data.page - 1) })} />}>
            Previous
          </Button>
          <Button size="sm" variant="outline" disabled={!data.has_next}
                  render={!data.has_next ? undefined : <Link href={link({ page: String(data.page + 1) })} />}>
            Next
          </Button>
        </div>
      </div>
    </div>
  );
}
