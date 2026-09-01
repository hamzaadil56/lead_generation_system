export const SESSION_COOKIE = "leadgen_session";

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

/** Issue a session token, but only for the right password. */
export async function signSession(password: string): Promise<string> {
  const expected = process.env.DASHBOARD_PASSWORD;
  if (!expected) throw new Error("DASHBOARD_PASSWORD is not set");
  // Constant-time-ish: compare after hashing so length does not leak.
  const [a, b] = await Promise.all([mac(password), mac(expected)]);
  if (a !== b) throw new Error("wrong password");
  const payload = `ok.${Date.now()}`;
  return `${payload}.${await mac(payload)}`;
}

export async function verifySession(token: string | undefined): Promise<boolean> {
  if (!token) return false;
  const i = token.lastIndexOf(".");
  if (i < 0) return false;
  const payload = token.slice(0, i);
  const given = token.slice(i + 1);
  try {
    return given === await mac(payload);
  } catch {
    return false;      // misconfigured secret must deny, never allow
  }
}
