"use client";
import { SignalBadge } from "@/components/signal-badge";
import type { ReasonOut } from "@/lib/types";

function Track({ title, reasons }: { title: string; reasons: ReasonOut[] }) {
  return (
    <div>
      <h3 className="mb-2 font-semibold">{title}</h3>
      <ul className="space-y-1">
        {reasons.map((r) => (
          <li key={r.rule}
              className={r.matched
                ? "rounded border-l-2 border-emerald-500 bg-muted/40 p-2"
                : "rounded p-2 text-muted-foreground opacity-60"}>
            <div className="flex items-center justify-between gap-3">
              <span>{r.label}</span>
              <span className="font-mono text-sm">{r.matched ? `+${r.points}` : "0"}</span>
            </div>
            {r.evidence?.length ? (
              <ul className="mt-1 space-y-0.5">
                {r.evidence.map((e, i) => (
                  <li key={i} className="text-xs italic text-muted-foreground">&ldquo;{e}&rdquo;</li>
                ))}
              </ul>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ReasonList({ reasons }: { reasons: ReasonOut[] }) {
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Track title="Fit" reasons={reasons.filter((r) => r.track === "fit")} />
      <Track title="Pain" reasons={reasons.filter((r) => r.track === "pain")} />
    </div>
  );
}

export function SignalList({ signals }: { signals: Record<string, unknown> }) {
  return (
    <div className="flex flex-wrap gap-2">
      {Object.entries(signals).map(([name, value]) => (
        <SignalBadge key={name} name={name} value={value} />
      ))}
    </div>
  );
}
