import { NextRequest } from "next/server";
import { apiGetRaw, ApiError } from "@/lib/api";

/** Proxies the API's CSV so the key stays on the server. A direct link from
 *  the browser to the API would require shipping the key to the client. */
export async function GET(req: NextRequest) {
  const sp = req.nextUrl.searchParams;
  try {
    const upstream = await apiGetRaw("/leads/export.csv", {
      quadrant: sp.get("quadrant") ?? undefined,
      min_fit: sp.get("min_fit") ?? undefined,
    });
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
