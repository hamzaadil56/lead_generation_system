"use client";
import { money } from "@/lib/format";
import type { PreviewOut } from "@/lib/types";

export function ConfirmPanel({ preview }: { preview: PreviewOut }) {
  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <dt className="text-muted-foreground">Searches</dt>
        <dd>{preview.search_count} searches</dd>
        <dt className="text-muted-foreground">Estimated results</dt>
        <dd>{preview.estimated_results}</dd>
        {/* The API's figure covers the search step only. Calling it the total
            would understate a real run by roughly 4x. */}
        <dt className="text-muted-foreground">Estimated search cost</dt>
        <dd>{money(preview.estimated_cost_usd)}</dd>
      </dl>

      <p className="text-xs text-muted-foreground">
        Website scraping is not included in that figure — the real total is
        higher and depends on how many businesses have a website.
      </p>

      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">
          Show the {preview.queries.length} queries
        </summary>
        <ul className="mt-2 space-y-0.5">
          {preview.queries.map((q) => (
            <li key={q} className="font-mono text-xs">{q}</li>
          ))}
        </ul>
      </details>

      {preview.recently_run_queries.length > 0 && (
        <div role="alert" className="rounded border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
          <p className="font-medium">
            {preview.recently_run_queries.length} of these were already run in the
            last 30 days:
          </p>
          <ul className="mt-1">
            {preview.recently_run_queries.map((q) => (
              <li key={q} className="font-mono text-xs">{q}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
