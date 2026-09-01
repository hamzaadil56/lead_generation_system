import Link from "next/link";
import { ConfirmPanel } from "@/components/new-search-form";
import { QueueRunForm } from "@/components/queue-run-form";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { apiGet, apiSend, ApiError } from "@/lib/api";
import type { PreviewOut, RunCreate } from "@/lib/types";

type Vertical = { name: string; search_terms: string[]; ruleset: string };
type State = { code: string; metros: string[] };

export default async function NewSearch({
  searchParams,
}: { searchParams: Promise<Record<string, string | undefined>> }) {
  const sp = await searchParams;
  const [verticals, states] = await Promise.all([
    apiGet<Vertical[]>("/verticals"),
    apiGet<State[]>("/states"),
  ]);

  const body: RunCreate = {
    vertical: sp.vertical ?? verticals[0]?.name ?? "hvac",
    state: sp.state || null,
    location: sp.location || null,
    pages: Number(sp.pages ?? 5),
  };
  const ready = Boolean(body.state || body.location);
  const confirming = sp.confirm === "1";

  let preview: PreviewOut | null = null;
  let error: string | null = null;
  let missingLocation: string | null = null;
  if (confirming && ready) {
    try {
      preview = await apiSend<PreviewOut>("POST", "/runs/preview", body);
    } catch (e) {
      error = e instanceof ApiError ? e.detail : "Could not build a preview.";
    }
  } else if (confirming && !ready) {
    // The API requires one of state or location and would 422 on neither.
    // Catch that here instead of sending a request known to fail, so the
    // screen explains itself rather than silently doing nothing.
    missingLocation = "Choose a state or a location before previewing a search.";
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold">New search</h1>

      <Card>
        <CardHeader><CardTitle>What to search</CardTitle></CardHeader>
        <CardContent>
          {/* GET so the choice lives in the URL and is shareable/back-able. */}
          <form method="GET" className="space-y-4">
            <input type="hidden" name="confirm" value="1" />
            <div className="space-y-2">
              <Label htmlFor="vertical">Vertical</Label>
              <select id="vertical" name="vertical" defaultValue={body.vertical}
                      className="w-full rounded-md border bg-background p-2">
                {verticals.map((v) => (
                  <option key={v.name} value={v.name}>{v.name}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="state">State</Label>
              <select id="state" name="state" defaultValue={sp.state ?? ""}
                      className="w-full rounded-md border bg-background p-2">
                <option value="">— choose a state —</option>
                {states.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.code.toUpperCase()} ({s.metros.length} metros)
                  </option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="pages">Pages per query</Label>
              <Input id="pages" name="pages" type="number" min={1} max={20}
                     defaultValue={body.pages} />
            </div>
            <Button type="submit">Preview</Button>
          </form>
        </CardContent>
      </Card>

      {missingLocation && <p role="alert" className="text-destructive">{missingLocation}</p>}
      {error && <p role="alert" className="text-destructive">{error}</p>}

      {preview && (
        <Card>
          <CardHeader><CardTitle>Confirm</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <ConfirmPanel preview={preview} />
            <div className="flex gap-2">
              <QueueRunForm body={body} />
              <Button variant="outline" render={<Link href="/runs" />}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
