export const SESSION_COOKIE = "leadgen_session";

// Single-user internal dashboard: bound how long a leaked cookie stays
// valid without forcing re-auth constantly. A few days is short enough to
// matter, long enough not to be annoying.
export const MAX_SESSION_AGE_MS = 7 * 24 * 60 * 60 * 1000;

function secretKey() {
  const secret = process.env.SESSION_SECRET;
  if (!secret || secret.length < 32) {
    throw new Error("SESSION_SECRET must be set and at least 32 characters");
  }
  return crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign", "verify"]);
}

const b64 = (b: ArrayBuffer) =>
  btoa(String.fromCharCode(...new Uint8Array(b)))
    .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

async function mac(payload: string) {
  const sig = await crypto.subtle.sign("HMAC", await secretKey(),
                                       new TextEncoder().encode(payload));
  return b64(sig);
}

/** Sign an arbitrary payload into a `<payload>.<mac>` token. Exported so
 *  tests can construct tokens with a specific embedded timestamp without
 *  faking the clock. */
export async function signPayload(payload: string): Promise<string> {
  return `${payload}.${await mac(payload)}`;
}

/** Issue a session token, but only for the right password. */
export async function signSession(password: string): Promise<string> {
  const expected = process.env.DASHBOARD_PASSWORD;
  if (!expected) throw new Error("DASHBOARD_PASSWORD is not set");
  // Constant-time-ish: compare after hashing so length does not leak.
  const [a, b] = await Promise.all([mac(password), mac(expected)]);
  if (a !== b) throw new Error("wrong password");
  const payload = `ok.${Date.now()}`;
  return signPayload(payload);
}

export async function verifySession(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const i = token.lastIndexOf(".");
  if (i < 0) return false;
  const payload = token.slice(0, i);
  const given = token.slice(i + 1);
  try {
    if (given !== await mac(payload)) return false;
  } catch {
    return false;      // misconfigured secret must deny, never allow
  }
  // Payload must be exactly "ok.<digits>". A malformed or non-numeric
  // timestamp denies -- it never defaults to valid.
  const match = /^ok\.(\d+)$/.exec(payload);
  if (!match) return false;
  const issuedAt = Number(match[1]);
  if (!Number.isFinite(issuedAt)) return false;
  return Date.now() - issuedAt <= MAX_SESSION_AGE_MS;
}
