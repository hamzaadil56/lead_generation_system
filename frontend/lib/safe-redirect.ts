/** Fallback destination when `next` is missing or unsafe. */
const FALLBACK = "/leads";

/**
 * Only ever redirect to a same-origin path. `next/navigation`'s redirect()
 * will happily follow an absolute URL, so an unvalidated `next` query
 * param is an open redirect. Accept a value that begins with a single "/"
 * and is not protocol-relative ("//evil.example" and "/\evil.example" are
 * both absolute to a browser); reject everything else -- including
 * `javascript:` and other schemes, which never start with "/" -- and fall
 * back to a known-safe path.
 */
export function safeNextPath(next: string | undefined): string {
  if (!next) return FALLBACK;
  if (!/^\/[^/\\]/.test(next) && next !== "/") return FALLBACK;
  return next;
}
