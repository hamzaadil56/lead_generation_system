/** Every filter `GET /leads` accepts — and, since the CSV is specified as
 *  "the export of the filtered set", every filter `GET /leads/export.csv`
 *  accepts too.
 *
 *  One list, read by the screen's export link and by the proxy route, because
 *  the two drifting apart is precisely how the export shipped honouring one
 *  filter of five: FastAPI ignores query params an endpoint does not declare,
 *  so a dropped filter does not fail — it quietly returns the whole table.
 *
 *  `review_count` is deliberately absent: ADR-022 makes it a label, never a
 *  sort or filter control. */
export const LEAD_FILTER_KEYS = [
  "quadrant", "vertical", "state", "outcome_status",
  "min_fit", "min_pain", "ruleset_version",
] as const;

export type LeadFilterKey = (typeof LEAD_FILTER_KEYS)[number];
