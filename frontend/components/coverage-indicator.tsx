import { percent } from "@/lib/format";

/** Below this, a score rests on too little evidence to read at face value. */
export const LOW_COVERAGE = 0.6;

export function CoverageIndicator({ coverage }: { coverage: number }) {
  const low = coverage < LOW_COVERAGE;
  return (
    <span className="inline-flex items-center gap-1 text-sm">
      <span className={low ? "text-amber-600 dark:text-amber-400" : "text-muted-foreground"}>
        {percent(coverage)}
      </span>
      {low && (
        <span role="img" aria-label="Low coverage — this score rests on little evidence"
              title="Low coverage — this score rests on little evidence">⚠</span>
      )}
    </span>
  );
}
