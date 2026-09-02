import { NextRequest } from "next/server";
import { apiGetRaw, ApiError } from "@/lib/api";
import { LEAD_FILTER_KEYS } from "@/lib/filters";

/** Proxies the API's CSV so the key stays on the server. A direct link from
 *  the browser to the API would require shipping the key to the client. */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  // Forward every filter, from the one list the leads screen builds its link
  // from. Naming them individually here is how three of the five went
  // missing, and a dropped filter does not error -- it exports everything.
  const params: Record<string, string | undefined> = {};
  for (const key of LEAD_FILTER_KEYS) params[key] = sp.get(key) ?? undefined;
  try {
    const upstream = await apiGetRaw("/leads/export.csv", params);
    return new Response(upstream.body, {
      headers: {
        "content-type": "text/csv; charset=utf-8",
        "content-disposition": 'attachment; filename="leads.csv"',
      },
    });
  } catch (e) {
    const status = e instanceof ApiError && e.status ? e.status : 502;
    return new Response("Could not export leads.", { status });
  }
}
