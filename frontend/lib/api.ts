import "server-only";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) {
    super(detail);
    this.name = "ApiError";
  }
}

function config() {
  const base = process.env.API_BASE_URL ?? "http://api:8000";
  const key = process.env.API_KEY;
  // Fail loudly rather than sending unauthenticated requests that 401 in a
  // way that looks like a backend problem.
  if (!key) throw new Error("API_KEY is not set — the dashboard cannot call the API");
  return { base, key };
}

function url(base: string, path: string,
             params?: Record<string, string | number | undefined>) {
  const u = new URL(path, base);
  for (const [k, v] of Object.entries(params ?? {})) {
    // Skip undefined: URLSearchParams would otherwise send the literal
    // string "undefined" and the API would filter on it.
    if (v !== undefined && v !== "") u.searchParams.set(k, String(v));
  }
  return u;
}

/** Turn any failure into an ApiError with a message safe to show a person. */
async function toError(res: Response): Promise<ApiError> {
  let detail = "Something went wrong.";
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") detail = body.detail;
    else if (Array.isArray(body?.detail)) detail = "That request was not valid.";
  } catch { /* non-JSON body: keep the generic message */ }
  if (res.status === 500) detail = "The server hit an error. Try again.";
  return new ApiError(res.status, detail);
}

async function request(method: string, path: string,
                       params?: Record<string, string | number | undefined>,
                       body?: unknown): Promise<Response> {
  const { base, key } = config();
  let res: Response;
  try {
    res = await fetch(url(base, path, params), {
      method,
      headers: {
        "X-API-Key": key,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
  } catch {
    // The API being unreachable must read as an error, not a blank page.
    throw new ApiError(0, "Cannot reach the API. Is it running?");
  }
  if (!res.ok) throw await toError(res);
  return res;
}

export async function apiGet<T>(
    path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  return (await request("GET", path, params)).json() as Promise<T>;
}

export async function apiSend<T>(method: "POST" | "PUT", path: string,
                                 body: unknown): Promise<T> {
  return (await request(method, path, undefined, body)).json() as Promise<T>;
}

/** For the CSV proxy, which needs the Response itself rather than JSON. */
export async function apiGetRaw(
    path: string, params?: Record<string, string | number | undefined>) {
  return request("GET", path, params);
}
