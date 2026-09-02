import Link from "next/link";
import { Pagination } from "@/components/pagination";
import { RunsList } from "@/components/runs-list";
import { Button } from "@/components/ui/button";
import { apiGet, ApiError } from "@/lib/api";
import type { Page, RunOut } from "@/lib/types";

// Kept explicit even though `searchParams` now makes this route dynamic on
// its own: without it Next prerendered the screen at build time -- inside
// `docker build`, where API_BASE_URL and API_KEY do not exist -- and baked
// the "Something went wrong." branch below into a static page that never
// refetched. The pin is what stops that regressing if the page ever stops
// reading a dynamic request API again.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 50;

export default async function RunsPage({
  searchParams,
}: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const page = Number(sp.page ?? 1);

  let data: Page<RunOut>;
  try {
    data = await apiGet<Page<RunOut>>("/runs", { page, page_size: PAGE_SIZE });
  } catch (e) {
    return <p role="alert" className="py-12 text-center text-destructive">
      {e instanceof ApiError ? e.detail : "Something went wrong."}
    </p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Runs</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">
            {data.total} run{data.total === 1 ? "" : "s"}
          </span>
          <Button render={<Link href="/runs/new" />}>New search</Button>
        </div>
      </div>
      <RunsList rows={data.items} />
      <Pagination page={data.page} pages={data.pages}
                  prevHref={data.page <= 1 ? null : `/runs?page=${data.page - 1}`}
                  nextHref={data.has_next ? `/runs?page=${data.page + 1}` : null} />
    </div>
  );
}
