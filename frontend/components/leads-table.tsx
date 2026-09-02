"use client";
import Link from "next/link";
import { CoverageIndicator } from "@/components/coverage-indicator";
import { QuadrantBadge } from "@/components/quadrant-badge";
import { ScorePair } from "@/components/score-pair";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { humanise } from "@/lib/format";
import type { LeadOut } from "@/lib/types";

export function LeadsTable({ rows }: { rows: LeadOut[] }) {
  if (rows.length === 0) {
    return <p className="py-12 text-center text-muted-foreground">
      No leads match these filters.
    </p>;
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Business</TableHead>
          <TableHead>Where</TableHead>
          {/* Fit/pain is the only ordering the API offers, and review_count
              is deliberately not a sortable control (ADR-022). */}
          <TableHead>Fit / Pain</TableHead>
          <TableHead>Quadrant</TableHead>
          <TableHead>Coverage</TableHead>
          <TableHead>Phone</TableHead>
          <TableHead>Outcome</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.cid}>
            <TableCell>
              <Link href={`/leads/${r.cid}`} className="font-medium underline-offset-2 hover:underline">
                {r.name}
              </Link>
              {r.segment && (
                <span className="ml-2 text-xs text-muted-foreground">{r.segment}</span>
              )}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {[r.city, r.state].filter(Boolean).join(", ") || "—"}
            </TableCell>
            <TableCell><ScorePair fit={r.fit_score} pain={r.pain_score} /></TableCell>
            <TableCell><QuadrantBadge quadrant={r.quadrant} /></TableCell>
            <TableCell><CoverageIndicator coverage={r.coverage} /></TableCell>
            {/* null means the number failed validation (ADR-013) -- never
                render something a person might dial. */}
            <TableCell className="font-mono text-sm">{r.phone ?? "—"}</TableCell>
            <TableCell>{r.outcome_status ? humanise(r.outcome_status) : "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
