import Link from "next/link";
import { Button } from "@/components/ui/button";

/** Previous/Next plus a "Page N of M" readout for the `Page<T>` envelope every
 *  list endpoint returns.
 *
 *  Shared rather than reimplemented: /leads and /runs page the same envelope
 *  from the same API, and /runs shipped without any controls at all, so runs
 *  past the first page were unreachable. A disabled edge is a real disabled
 *  <button>, never a dead <a>: an anchor with no href is not focusable and
 *  announces nothing to a screen reader. */
export function Pagination({ page, pages, prevHref, nextHref }: {
  page: number;
  pages: number;
  prevHref: string | null;
  nextHref: string | null;
}) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-sm text-muted-foreground">
        Page {page} of {pages}
      </span>
      <div className="flex gap-2">
        <Button size="sm" variant="outline" disabled={!prevHref}
                render={prevHref ? <Link href={prevHref} /> : undefined}>
          Previous
        </Button>
        <Button size="sm" variant="outline" disabled={!nextHref}
                render={nextHref ? <Link href={nextHref} /> : undefined}>
          Next
        </Button>
      </div>
    </div>
  );
}
