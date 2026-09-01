import Link from "next/link";
import { RunsList } from "@/components/runs-list";
import { Button } from "@/components/ui/button";
import { apiGet, ApiError } from "@/lib/api";
import type { Page, RunOut } from "@/lib/types";

// This screen reads no dynamic request API (no searchParams, no params), so
// Next prerenders it at build time -- inside `docker build`, where API_BASE_URL
// and API_KEY do not exist. The build then bakes the "Something went wrong."
// branch below into a static page that never refetches. Force-dynamic so the
// runs list is rendered per request, against the live API.
export const dynamic = "force-dynamic";

export default async function RunsPage() {
  let data: Page<RunOut>;
  try {
    data = await apiGet<Page<RunOut>>("/runs", { page: 1, page_size: 50 });
  } catch (e) {
    return <p role="alert" className="py-12 text-center text-destructive">
      {e instanceof ApiError ? e.detail : "Something went wrong."}
    </p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Runs</h1>
        <Button render={<Link href="/runs/new" />}>New search</Button>
      </div>
      <RunsList rows={data.items} />
    </div>
  );
}
