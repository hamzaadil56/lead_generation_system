export const money = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `$${n.toFixed(3)}`;

export const percent = (n: number | null | undefined) =>
  n === null || n === undefined ? "—" : `${Math.round(n * 100)}%`;

export const when = (iso: string | null | undefined) =>
  !iso ? "—" : new Date(iso).toLocaleString();

/** "go_now" -> "Go now". Quadrants and statuses arrive snake_cased. */
export const humanise = (s: string) =>
  s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
