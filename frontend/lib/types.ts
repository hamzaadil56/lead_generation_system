// Page<T> — the envelope every list endpoint returns.
// `pages` is at least 1 even when empty, so "page 1 of 0" never renders.
export type Page<T> = {
  items: T[]; total: number; page: number; page_size: number;
  pages: number; has_next: boolean;
};

export type LeadOut = {
  cid: string; name: string;
  city: string | null; state: string | null;
  website: string | null;
  phone: string | null;          // null when the number failed validation (ADR-013)
  segment: string | null;        // "emerging" | "growth" | "established" | "enterprise"
  review_count: number | null;   // LABEL ONLY — never a sort or filter control
  fit_score: number; pain_score: number;
  quadrant: string;              // "go_now" | "nurture" | "low_fit" | "cold"
  coverage: number;              // 0.0–1.0
  outcome_status: string | null;
};

export type ReasonOut = {
  rule: string; track: string;   // track is "fit" | "pain"
  matched: boolean; points: number; label: string;
  evidence?: string[] | null;
};

export type ScoreOut = {
  ruleset_version: string; fit_score: number; pain_score: number;
  quadrant: string; coverage: number; scored_at: string;
};

export type EvidenceOut = {
  text: string; rating: number | null; published_at: string | null;
};

export type LeadDetailOut = {
  lead: LeadOut;
  score: ScoreOut | null;        // null = not scored yet. BRANCH ON THIS,
                                 // never on lead.quadrant, which is a
                                 // placeholder "cold" for unscored leads.
  reasons: ReasonOut[];
  signals: Record<string, unknown>;   // null value = UNKNOWN, not false
  evidence: EvidenceOut[];
};

export type RunOut = {
  id: number; status: string;    // "queued" | "running" | "complete" | "failed"
  source: string;                // "ui" | "cli"
  search_plan: Record<string, unknown>;
  stats: Record<string, unknown> | null;
  max_cost_usd: number | null;
  estimated_cost: number | null; // SEARCH COST ONLY — see the note below
  actual_cost: number | null;
  created_at: string | null; started_at: string | null;
  finished_at: string | null; error: string | null;
};

export type RunCreate = {
  vertical: string;
  state?: string | null;         // one of state or location is REQUIRED
  location?: string | null;
  pages?: number;                // 1–20, default 5
  max_cost_usd?: number | null;  // server defaults to 5.0 when omitted
};

export type PreviewOut = {
  vertical: string; queries: string[]; search_count: number;
  estimated_results: number;
  estimated_cost_usd: number;    // SEARCH COST ONLY
  recently_run_queries: string[];
};

export type OutcomeIn = { status: string; notes?: string | null };
// status is one of: new, contacted, replied, booked, won, lost

export type ManualFactsIn = {
  estimated_employees?: number | null;   // 0–100000
  technician_count?: number | null;      // 0–10000
  has_office_admin?: boolean | null;
  owner_growth_focused?: boolean | null;
  notes?: string | null;                 // max 4000
};
