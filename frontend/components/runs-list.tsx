"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { Badge } from "@/components/ui/badge";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { money, when } from "@/lib/format";
import type { RunOut } from "@/lib/types";

export const isInFlight = (rows: RunOut[]) =>
  rows.some((r) => r.status === "queued" || r.status === "running");

const TONE: Record<string, string> = {
  queued: "bg-slate-500", running: "bg-sky-600",
  complete: "bg-emerald-600", failed: "bg-red-600",
};

export function RunsList({ rows }: { rows: RunOut[] }) {
  const router = useRouter();

  // Poll only while something is actually in flight. The scheduler picks up a
  // queued run within ~30s, so 5s is responsive without being wasteful.
  useEffect(() => {
    if (!isInFlight(rows)) return;
    const t = setInterval(() => router.refresh(), 5000);
    return () => clearInterval(t);
  }, [rows, router]);

  if (rows.length === 0) {
    return <p className="py-12 text-center text-muted-foreground">No runs yet.</p>;
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Run</TableHead><TableHead>Status</TableHead>
          <TableHead>Search</TableHead><TableHead>Started</TableHead>
          <TableHead>Search est. / actual</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => {
          const plan = r.search_plan as Record<string, unknown>;
          return (
            <TableRow key={r.id}>
              <TableCell className="font-mono">#{r.id}
                <span className="ml-2 text-xs text-muted-foreground">{r.source}</span>
              </TableCell>
              <TableCell>
                <Badge className={`${TONE[r.status] ?? TONE.queued} text-white`}>
                  {r.status}
                </Badge>
                {r.error && (
                  <p className="mt-1 max-w-md text-xs text-destructive">{r.error}</p>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {String(plan.vertical ?? "—")} ·{" "}
                {String(plan.location ?? plan.state ?? "—")}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">
                {when(r.started_at)}
              </TableCell>
              {/* "Search est." not "Estimated": the figure excludes scraping,
                  so a bare "estimated vs actual" would read as an overrun. */}
              <TableCell className="font-mono text-sm">
                {money(r.estimated_cost)} / {money(r.actual_cost)}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
