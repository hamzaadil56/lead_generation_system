# Lead Generation System — Design Spec

**Date:** 2026-08-27
**Status:** Approved design, pending implementation plan
**Author:** Hamza Adil (with Claude)

---

## 1. Context

An agency sells custom agentic voice AI systems that handle inbound calls
24/7 for service businesses. This system finds and qualifies leads for that
agency.

Built for the agency's own use first. It may become a product later, so the
design avoids choices that would block multi-tenancy, but does not build
multi-tenancy now.

**Target verticals:** HVAC and home services, healthcare clinics, law firms,
travel and hospitality. Marketing agencies are excluded from v1 — they are a
reseller motion, not an inbound-call motion, and need different criteria.

**Geography:** United States.

---

## 2. Goals and non-goals

### Goals

- Discover businesses matching a vertical and location from Google Maps.
- Collect the data needed to judge whether a business fits the ICP and
  whether it is losing money on missed calls.
- Score every business against editable, versioned rules.
- Present ranked leads in a dashboard with the evidence behind each score.
- Record what happened when leads were contacted, so scoring rules can be
  calibrated against real outcomes.

### Non-goals for v1

- Automated contact/email discovery (schema seam exists; pipeline deferred).
- Email sending or sequencing.
- Free-text natural-language search (dropdowns in v1).
- Multi-tenancy, roles, or per-user data isolation.
- LLM-based lead qualification (rule-based only; LLM is a later option).
- Playwright-based scraping (Serper + Firecrawl only; SerpApi is used
  solely for free-tier review enrichment, ADR-020).

---

## 3. ICP and qualification criteria

**The ICP is an open hypothesis, not a filter (ADR-022).** The stated
profile below was a thesis: growing SMBs still small enough to miss calls, on
the assumption that large high-review companies already run call centres.
Real Houston data did not support the size half of that thesis — review count
showed no correlation with 24/7 coverage, and the second-largest company in
the sample (8,758 reviews) closes at 5pm and all weekend.

**Company size measures ability to pay. Hours measure the call-answering gap
directly.** v1 therefore segments on size and scores on hours, letting
`outcomes` settle the ICP empirically.

The stated ICP (HVAC as the reference vertical):

| Criterion | Detectability | Source |
|---|---|---|
| 200+ Google reviews | **Segment label only (ADR-022)** | Serper `ratingCount` — not a filter, not scored |
| Closes before 6pm / weekends | **Direct** | Serper `openingHours` — the gap measured directly |
| Uses ServiceTitan / Jobber / Housecall Pro | **Direct, free** | Serper `bookingLinks` |
| Running Google Ads | Direct | gtag/conversion tags in scraped HTML |
| Running Local Services Ads | **Deferred (ADR-015)** | Not available from Serper; LSA rules dropped from v1 |

| 50+ new leads/month | **Unavailable in v1 (ADR-013)** | Needs dated review text; Serper returns counts only |
| 10–40 employees | Manual | Apollo free-tier lookup, entered by hand |
| 5–20 technicians | Manual | Apollo / team page |
| $2M–10M revenue | Derived | Not independent — restates employee count |
| At least one office administrator | Manual | Entered by hand during the research pass |
| Owner focused on growth | Manual | Entered by hand during the research pass |

### Segments

Review count becomes a label, carried into `outcomes` so conversion can be
compared across the whole hypothesis:

| Segment | Reviews | Thesis said |
|---|---|---|
| `emerging` | 50 – 200 | too small to buy |
| `growth` | 200 – 2,000 | the stated ICP |
| `established` | 2,000 – 5,000 | — |
| `enterprise` | 5,000+ | already has a call centre |

### Fit vs. pain

The stated ICP is almost entirely **fit** (can they buy?) with no **pain**
(do they hurt?). A perfect-fit business with no problem will not buy.

The system therefore produces **two independent scores**, never blended:

```
            PAIN (do they hurt?)
                    high
                     |
   low-fit           |   GO NOW
   hurting but       |   big, spending on ads,
   too small to buy  |   and dropping calls
  -------------------+-------------------  FIT (can they buy?)
   cold              |   NURTURE
                     |   good fit, no urgency
                    low
```

Quadrant is assigned from the two normalised scores:

| Quadrant | Condition |
|---|---|
| `go_now` | fit >= 60 AND pain >= 60 |
| `nurture` | fit >= 60 AND pain < 60 |
| `low_fit` | fit < 60 AND pain >= 60 |
| `cold` | fit < 60 AND pain < 60 |

The 60 threshold is a starting value, stored in the ruleset rather than
hardcoded, and recalibrated alongside the weights. The dashboard's default
view is the `go_now` quadrant, sorted by `fit x pain`.

### Pain signals (not in the stated ICP, added by this design)

- Reviews in the last 90 days mentioning unanswered calls or unreturned
  voicemails. Strongest available signal; quotes double as outreach copy.
- Phone-only intake — no contact form, chat widget, or online booking.
- Closes before 6pm / not open weekends, in an emergency-driven trade.
- High review velocity, implying high call volume.
- **Running Local Services Ads while closing at 5pm.** LSA bills per phone
  call. A business paying per call and not answering the phone is provably
  wasting money — an invoice to point at, not a hypothesis to pitch.

---

## 4. System architecture

Three deployables plus a managed database.

```
  Next.js (Vercel)  --HTTP-->  FastAPI + scheduler (Railway/Render)  -->  Neon Postgres
     dashboard                  API + pipeline + CLI, one Docker image
```

Next.js never touches the database. All reads and writes, including
server-side, go through the FastAPI API.

### The central split: network half and pure half

```
+---------- NETWORK HALF (costs money, cached forever) -----------+

  [1] discover          [3] scrape_site         [6] fetch_reviews
  Serper /maps          Firecrawl               SerpApi free tier
  (2 credits/page)      (md + rawHtml + links)  (top 25 only, after scoring)
       |                      |                        |
       v                      v                        v
  ============ Postgres: raw payloads retained ==================
       |                      |                        |
       +----------------------+------------------------+
                              |
+---------- PURE HALF (free, instant, re-runnable) ---------------+
                              v
                     [4] extract_signals
                              v
                        [5] score  ---> top 25 by fit feed stage [6],
                              |          then [4] and [5] re-run
                              v
                   Dashboard (via FastAPI)

  [2] fetch_place is a no-op in v1 — Serper's discovery response already
      carries every field the prefilter and fit rules need.
```

Network stages cost money and fail. Pure stages are functions over data
already held. Every expensive stage writes its raw output to Postgres and
never runs twice for the same business.

**Consequence:** re-scoring 200 businesses after a rule change costs nothing
and takes under a second. Adding a new signal requires re-running
`extract_signals` and `score` against stored raw HTML — still zero API calls.
This is the property the whole design exists to protect, because the scoring
rules are unproven and will be tuned dozens of times.

### Status machine

```
discovered -> place_fetched -> site_scraped -> signals_extracted -> scored
     \--> filtered_out   (failed prefilter; terminal, never enriched)

              ^                                                  |
              |          top N by fit_score, once per run         |
              +---- fetch_reviews (SerpApi free tier) <-----------+
                    sets status back to site_scraped

any stage may also land on: failed (with stage name + error)
```

Status is per-business and global, not per-run. Stages select by status, so a
business already at `scored` falls out of every downstream query
automatically. This is the deduplication mechanism.

### Prefiltering before paid enrichment

Discovery now carries most scoring signals for free — `openingHours`,
`bookingLinks`, `types`, `ratingCount` — so collecting broadly is cheap and
only the *deep* enrichment is rationed.

```
discover (100 results/query = 5 pages x ~2-3 Serper credits)
   -> prefilter: has a website                           (free)
   -> assign segment from ratingCount                    (free)
   -> score fit + most of pain from discovery data       (free)
   -> scrape_site on a STRATIFIED SAMPLE: top ~15 per segment
   -> after scoring, fetch_reviews on top ~25            (SerpApi free tier)
```

**Stratified rather than top-N-overall (ADR-022).** Taking the top 15 of each
of the four segments produces ~60 scrape targets per run — fewer than the
~105 in the previous design — while generating comparable outcome data across
every segment. Ranking purely by score would concentrate all outreach in one
segment and make the ICP question unanswerable.

An earlier estimate that a 200-review gate would drop ~85% of results was
**wrong**: 13 of 20 records in a real Houston sample cleared it. The gate is
removed regardless (ADR-022).

Businesses failing the prefilter get status `filtered_out` — terminal, never
enriched, but retained so a later ruleset change can revisit them without
re-running discovery. Because the prefilter requires a website, there is no
"no website" path through the pipeline; a website that is listed but dead or
parked is recorded as `signals.website_status` and flows through normally
with reduced `coverage`.

---

## 5. Pipeline stages

| Stage | Input status | Output status | External calls |
|---|---|---|---|
| `discover` | — | `discovered` | Serper `/maps` (per term × location), ~2–3 credits/page |
| `fetch_place` | `discovered` | `place_fetched` | **no-op in v1** — Serper's discovery response already carries every needed field |
| `scrape_site` | `place_fetched` | `site_scraped` | Firecrawl, 4–6 allowlisted pages per business |
| `extract_signals` | `site_scraped` | `signals_extracted` | none |
| `score` | `signals_extracted` | `scored` | none |
| `fetch_reviews` | `scored` (top N by fit) | `site_scraped` | SerpApi reviews, ~2 calls/business |

`fetch_reviews` runs **once per run, after scoring**, and deliberately loops
rows back to `site_scraped` so `extract_signals` and `score` re-run over the
richer data. Safe because both are free and idempotent.

Each stage is invocable independently via CLI or API, is idempotent, and can
be re-run safely. `run_all` chains them scoped to a `run_id`.

### Discovery expansion

A `SearchPlan` is built from dropdowns (vertical, state/metro,
results-per-query) and expanded via config:

```yaml
# config/verticals.yaml
hvac:
  search_terms:
    - "hvac contractor"
    - "air conditioning repair"
    - "heating and cooling company"
    - "furnace repair"

# config/locations.yaml
tx:
  metros: ["Houston, TX", "Dallas, TX", "San Antonio, TX",
           "Austin, TX", "Fort Worth, TX", "El Paso, TX"]
```

`hvac` × `tx` = 4 terms × 6 metros = 24 searches.

### Firecrawl usage

- Request **both `markdown` and `rawHtml`**. Markdown is for reading; raw
  HTML is required to detect booking widgets, chat widgets, contact forms,
  and ad/tracking tags — all stripped from markdown.
- Never use unbounded `/crawl`. Target an allowlist: homepage, `/about`,
  `/contact`, `/services`, `/team`. Hard page limit.
- Do not use Firecrawl `/extract`. Extraction stays in owned code so field
  provenance is controlled.

### Ads detection

**Not available in v1.** Serper's `/maps` response carries no ad or
Google Guaranteed data, and LSA is deferred (ADR-015). Google Ads presence is
still detected independently from gtag / conversion tags in the scraped HTML,
which is where the `runs_google_ads` fit rule gets its 20 points.

### Refresh

Status prevents re-scraping forever. An explicit opt-in flag reverses it:

```
discover --vertical hvac --location "Houston, TX" --refresh-older-than 90d
```

Never the default.

---

## 5A. External API integration

Verified against SerpApi and Firecrawl documentation on 2026-08-27. Response
shapes and pricing must be re-checked before implementation begins.

### Packages

| Service | Package | Notes |
|---|---|---|
| Serper | plain `httpx` against `google.serper.dev` | No official Python SDK required; the API is a single POST with an `X-API-KEY` header |
| Firecrawl | `firecrawl-py` | Class is `Firecrawl` (**not** `FirecrawlApp`, an older name). `AsyncFirecrawl` also available. API v2 |
| SerpApi *(optional, ADR-013 recovery)* | `serpapi` (official) | **Not** the legacy `google-search-results` package, whose `from serpapi import GoogleSearch` import shadows the official module name |

All sit behind the `SearchProvider` / `WebScraper` Protocols, so no package
name appears outside `clients/`.

### Stage 1 — `discover` (Serper `/maps`)

```python
httpx.post(
    "https://google.serper.dev/maps",
    headers={"X-API-KEY": settings.serper_key},
    json={"q": "hvac businesses in Houston", "gl": "us", "hl": "en"},
)
```

Natural-language location in `q` works and the response echoes back the
resolved `ll` (`"@29.863928,-95.4346125,10z"`), so metro centroids are *not*
required in config — a display name is enough.

Verified response, real record:

```json
{
  "position": 1,
  "title": "Air Tech of Houston AC & Plumbing",
  "address": "2114 Lou Ellen Ln, Houston, TX 77018",
  "latitude": 29.8186339, "longitude": -95.4384587,
  "rating": 4.9, "ratingCount": 6445,
  "type": "HVAC contractor",
  "types": ["HVAC contractor", "Air conditioning contractor", ...],
  "website": "https://www.airtechofhouston.com/...",
  "phoneNumber": "(832) 680-5546",
  "openingHours": {
    "Monday": "Open 24 hours", ..., "Sunday": "Open 24 hours"
  },
  "bookingLinks": ["https://book.servicetitan.com/r403q9wgygvty8ghzvbhag5i?..."],
  "thumbnailUrl": "...",
  "cid": "16433610908791049931",
  "fid": "0x8640c6550750ea9d:0xe40fea0d73798ecb",
  "placeId": "ChIJnepQB1XGQIYRy455cw3qD-Q"
}
```

Response also carries a top-level `"credits": 3` — **log it in `api_calls` as
actual cost rather than an estimate.**

| Field | Used for | Points |
|---|---|---|
| `cid` | Dedupe key (`placeId` and `fid` stored too) | — |
| `ratingCount` | **`segment` label only** (ADR-022) — not a filter, not scored | 0 |
| `openingHours` | `closed_weekends`, `closes_before_6pm`, `is_24_7` | 55 pain |
| `bookingLinks` | Field-service software **and** phone-only intake | 30 fit / 25 pain |
| `website` | The only prefilter, and the scrape target | — |
| `types[]` | Vertical confirmation | — |
| `phoneNumber` | Contact — **must be validated** | — |

**~65 of 200 total points are obtainable at discovery with no scraping.**

#### `bookingLinks` is the highest-value field

Real distribution across the 20-record Houston sample:

```
book.servicetitan.com     → 4 records   ServiceTitan   (fit)
book.housecallpro.com     → 4 records   Housecall Pro  (fit)
own-site booking only     → 6 records   —
key absent entirely       → 6 records   phone-only     (pain)
```

Vendor detection is a substring match on the URL — deterministic, free, no
HTML fingerprinting required. **The absence of the key is itself the
phone-only-intake signal**, so it must be distinguished from an empty array.

#### Known data-quality issues, all observed in real responses

1. **`phoneNumber` can contain the address.** Seen in 2 of 10 records in an
   earlier `/places` sample. Every phone must be regex-validated into E.164
   and flagged `phone_is_valid`; invalid values must never reach a dialler or
   a CSV column labelled "phone".
2. **`openingHours` can be malformed.** One record returned
   `"Thursday": "8 AM–5 AM"` — an obvious mis-parse of 5 PM. Unparseable days
   are stored **null**, never guessed, and reduce that business's `coverage`.
3. **`address` is sometimes absent** — service-area businesses with no
   storefront. Not an error.
4. **`bookingLinks` is often an absent key**, not an empty array.
5. **`rating` does not discriminate.** All 20 records rated 4.6–5.0. Any rule
   keyed on rating fires for ~100% of candidates; removed from scoring.

**Credits:** the sampled call returned 20 results for 3 credits. Free
allocation is 2,500 credits valid 6 months; paid packs run $1.00/1k down to
$0.30/1k, expiring 6 months from purchase.

### Stage 2 — `fetch_place`

**Not needed in v1.** Serper's discovery response already contains every
field the prefilter and fit rules require, so there is no separate
place-details call. The status machine keeps the `place_fetched` state as a
no-op pass-through so the stage can be reintroduced without a migration.

### Stage 6 — `fetch_reviews` (SerpApi free tier, ADR-020)

Adopted. After Serper ranks a run, fetch full reviews for the **top
`enrichment_top_n` leads only** (default 25):

```python
serpapi.search(
    engine="google_maps_reviews",
    data_id=business.cid,
    sort_by="newestFirst",      # mandatory — default ordering breaks velocity
    num=20,
)
```

- First page returns **8 reviews regardless of `num`**; later pages honour
  `num` up to 20. Stop as soon as `iso_date` passes 90 days — typically 2
  calls per business.
- SerpApi's free tier is 250 searches/month. At 25 leads × 2 calls = 50
  searches/run, that covers **4–5 runs/month at zero cost** with ~20%
  headroom. 30 leads would consume 96% of the allowance — no slack for a
  retry storm, hence the default of 25.
- **The budget guard must enforce a monthly SerpApi ceiling**, not just a
  per-run cost cap. The allowance resets monthly and does not roll over;
  exceeding it silently degrades later runs to basic tier.
- Restores `missed_call_complaints` (30 pain points), `review_velocity` (15),
  and the verbatim evidence quotes used as outreach openers.

### Stage 3 — `scrape_site` (Firecrawl v2)

```python
firecrawl.scrape(
    url=business.website,
    formats=["markdown", "rawHtml", "links"],
    only_main_content=False,       # ← see trap below
    timeout=30000,
)
```

Three settings that matter:

- **`only_main_content` defaults to `True`** and strips headers, navs, and
  **footers** — which is exactly where small-business contact details,
  addresses, and vendor badges live. Must be set `False`.
- **`links` is worth requesting.** It returns every link on the page, which
  (a) locates the real `/about`, `/contact`, `/team` URLs instead of guessing
  paths, and (b) detects field-service software directly from outbound links
  such as `book.housecallpro.com` or `clienthub.getjobber.com`.
- **`maxAge` defaults to ~2 days of caching.** Beneficial here: a re-run
  within that window is served from cache. Leave at default.

**Two-step page selection:** scrape the homepage first, read `links`, then
scrape up to 4 matched internal pages. This replaces blind path-guessing and
avoids unbounded `/crawl` entirely.

Signals derived from `rawHtml` (substring matching against a fingerprint
list — deterministic, no LLM):

| Signal | Fingerprints |
|---|---|
| `field_service_software` | `housecallpro`, `getjobber`, `clienthub.getjobber`, `servicetitan`, `st-booking` |
| `has_booking_widget` | above, plus `calendly`, `acuityscheduling` |
| `has_chat_widget` | `podium`, `intercom`, `drift`, `tawk.to`, `tidio` |
| `has_google_ads_tag` | `googleadservices`, `gtag/js?id=AW-`, `googleads.g.doubleclick` |
| `has_meta_pixel` | `connect.facebook.net`, `fbq(` |
| `has_contact_form` | `<form>` with an email or tel input |

**Scope reduced by ADR-021.** ServiceTitan / Jobber / Housecall Pro are now
detected from Serper's `bookingLinks` at zero cost, so only the **chat widget
and ad-tag fingerprints** still need capturing from real sites. Smaller task
than originally scoped, but still not writable from memory.

### Error handling specifics

| Code | Service | Class (section 10) |
|---|---|---|
| 402 | Firecrawl | Permanent for the run — abort, out of credits |
| 429 | Both | Transient — back off, respect `Retry-After` |
| 401 / 403 | Both | Permanent for the run — circuit breaker |
| 5xx | Both | Transient — retry |
| Empty `places` | Serper | Not an error — a market with no matches |
| Firecrawl non-200 on target site | Firecrawl | Permanent for that business — `website_status='dead'` |

Serper's free allocation is 2,500 credits valid 6 months — roughly ten
discovery runs — enough to reach outreach without paying anything.

---

## 6. Data model

Two classes of table. If a table can be safely dropped and regenerated, it is
**rebuildable**; otherwise it is **permanent**.

```
PERMANENT (expensive, never regenerated)
  runs · businesses · run_businesses · raw_payloads
  search_queries · manual_facts · contacts · outcomes · api_calls

REBUILDABLE (drop and regenerate any time, free)
  reviews · signals · scores
```

### Permanent tables

**`runs`** — one per search; also the work queue.
```
id, status (queued|running|complete|failed), source (ui|cli),
search_plan jsonb, stats jsonb, max_cost_usd, estimated_cost, actual_cost,
created_at, started_at, finished_at, error
```

**`businesses`** — one row per unique business, globally deduped.
```
id, cid UNIQUE, place_id, fid,
name, address, city, state, zip, lat, lng,
phone, phone_is_valid, website,
rating, review_count, segment,          -- emerging|growth|established|enterprise
primary_category, types jsonb,
opening_hours jsonb, booking_links jsonb,
vertical,
status, failed_stage, error_message, error_at, attempt_count,
first_seen_run_id, created_at, updated_at
```

**`run_businesses`** — many-to-many. Exists for display, not deduplication:
without it, a run that rediscovers 150 known businesses would show only the
50 new ones.
```
run_id, business_id, is_new    PRIMARY KEY (run_id, business_id)
```

**`raw_payloads`** — append-only archive everything else derives from.
```
id, business_id, source (serpapi_search|serpapi_place|serpapi_reviews|firecrawl),
url, fetched_at, payload jsonb, raw_text text
```

**`search_queries`** — query-level dedupe, the only lever on search cost.
```
id, run_id, term, location, executed_at, result_count
```

**`manual_facts`** — hand-entered data. Must NOT live in `signals`, which is
rebuilt and would wipe it.
```
business_id PK, estimated_employees, technician_count,
has_office_admin, owner_growth_focused, notes, updated_at
```

**`contacts`** — populated manually in v1, by resolvers in v2. Same table
either way, distinguished by `source`.
```
id, business_id, name, role, email, phone, linkedin_url,
source (manual|license_registry|website|bbb|finder_api),
confidence, verification_status (unverified|valid|risky|invalid|catch_all),
is_primary, created_at, verified_at
```

**`outcomes`** — ground truth for scoring.
```
id, business_id, status (new|contacted|replied|booked|won|lost),
source (manual|email_event), notes, contacted_at, updated_at
```

**`suppressions`** — required before the first outreach email is ever sent.
```
email PK, reason (unsubscribed|bounced|complained|manual), source, created_at
```

**`api_calls`** — cost accounting, latency debugging, and budget guard input.
```
id, run_id, business_id, provider, endpoint, credits, cost_usd,
status_code, duration_ms, created_at
```

**`rulesets`** — versioned scoring config, seeded from YAML in `config/`.
```
version PK, name, vertical, definition jsonb, is_active, created_at
```

### Rebuildable tables

**`reviews`** — parsed from raw payloads; needed as rows for velocity and
complaint mining.
```
id, business_id, author, rating, text,
published_at, published_at_is_approximate, source
```

The `google_maps_reviews` engine returns both a relative `date`
("2 months ago") and an absolute **`iso_date`**. `published_at` comes from
`iso_date`, so review velocity is exact, not estimated. The
`published_at_is_approximate` flag exists only for reviews sourced from a
place payload rather than the reviews engine.

**`signals`** — the typed inputs rules consume. Derived from raw payloads,
then overlaid with `manual_facts` (manual always wins).
```
business_id PK,
-- from Serper /maps (free, always available)
has_booking_link, booking_vendor,       -- servicetitan|jobber|housecallpro|own|none
is_phone_only,                          -- bookingLinks key absent
is_24_7, closes_before_6pm, closed_weekends,
hours_parse_failed,                     -- true if any day was unparseable
segment,
-- from Firecrawl (scraped subset only)
has_chat_widget, chat_vendor,
has_contact_form,
-- from SerpApi enrichment (top ~25 only, dormant otherwise)
review_velocity_90d,
missed_call_complaints_90d, complaint_quotes jsonb,
has_google_ads_tag, has_meta_pixel,
runs_google_ads,
team_page_headcount, estimated_employees, employee_est_source,
website_status (ok|none|dead|parked),
extracted_at, extractor_version
```

**`scores`** — keyed on `(business_id, ruleset_version)`, so tuning **adds**
a scoring rather than overwriting one. Two rulesets can be compared on the
same businesses without destroying the earlier evidence.
```
id, business_id, ruleset_version, fit_score, pain_score, quadrant,
coverage, reasons jsonb, scored_at
UNIQUE (business_id, ruleset_version)
```

### Storage note

Raw HTML runs roughly 0.5–1 MB per business across 4 pages. Neon's free tier
is 0.5 GB. Postgres TOAST compression absorbs much of this, but budget for
it. Escape hatch if needed: move `raw_text` to Vercel Blob, keep a pointer.

---

## 7. Scoring engine

### Rules as data

A ruleset is a JSON document in `rulesets`, seeded from YAML in `config/`.

```yaml
version: hvac_v1
vertical: hvac

prefilters:                       # applied before any paid enrichment
  - {signal: review_count, op: gte, value: 200}
  - {signal: website, op: not_null}

fit_rules:
  - id: field_service_software
    when: {signal: booking_vendor, op: in,
           value: [servicetitan, jobber, housecallpro]}
    points: 30
    label: "Uses {booking_vendor}"

  - id: has_office_admin
    when: {signal: has_office_admin, op: is_true}
    points: 10
    on_missing: skip              # not penalised until researched

pain_rules:
  - id: closed_weekends
    when: {signal: closed_weekends, op: is_true}
    points: 30
    label: "Closed Saturday and Sunday in an emergency trade"

  - id: phone_only_intake
    when: {signal: is_phone_only, op: is_true}
    points: 25
    label: "No online booking — every lead arrives as a phone call"

  - id: missed_call_complaints          # dormant until ADR-020 enrichment
    when: {signal: missed_call_complaints_90d, op: gte, value: 3}
    points: 30
    on_missing: skip
    label: "{missed_call_complaints_90d} recent reviews mention unanswered calls"
    evidence: complaint_quotes
```

**Fixed operator set** — `gte, lte, gt, lt, eq, neq, in, not_in, is_true,
is_false, is_null, not_null`, plus `all` / `any` grouping. No expression
language, no `eval()`. If a rule cannot be expressed, add a *signal*, not an
operator.

### Starting HVAC ruleset (hvac_v1)

**v1 ships the HVAC ruleset only.** Healthcare clinics, law firms, and
hospitality use the same engine, tables, and pipeline; each needs its own
ruleset plus vertical-specific search terms and pain signals (a law firm's
pain is intake calls going to voicemail after hours; a clinic's is
appointment booking). Those are added after HVAC has been validated against
real outcomes — adding a vertical is a config change, not a code change.

Weights are informed guesses. They are expected to be wrong until `outcomes`
provides calibration data.

Both tracks of **automatic** rules total 100 points. Manual-pass rules
(`has_office_admin` +10, `owner_growth_focused` +10, both `on_missing: skip`)
are additional and sit outside that 100 — scores are normalised over
applicable points, so a nominal total is a convenience, not a constraint. A
business that has been researched is scored against 120 fit points; one that
has not is scored against 100, and its `coverage` reflects the difference.

Reweighted per ADR-014 to use only signals obtainable from Serper +
Firecrawl. LSA and all review-text rules are removed.

**Fit (100)** — *review count and rating are deliberately absent (ADR-022,
ADR-021):*

| Rule | Points | Source | Tier |
|---|---|---|---|
| Uses ServiceTitan / Jobber / Housecall Pro | 30 | Serper `bookingLinks` | free |
| Running Google Ads (gtag present) | 25 | rawHtml | scrape |
| Estimated 10–40 employees | 25 | manual (Apollo) | `on_missing: skip` |
| Has online booking of any kind | 20 | Serper `bookingLinks` | free |

**Pain — 100 always-on + 45 dormant:**

| Rule | Points | Source | Tier |
|---|---|---|---|
| Closed on weekends (emergency trade) | 30 | Serper `openingHours` | free |
| Closes before 6pm on weekdays | 25 | Serper `openingHours` | free |
| No booking link at all → phone-only intake | 25 | Serper `bookingLinks` | free |
| No chat widget on site | 20 | rawHtml | scrape |
| >= 3 reviews in 90d mention unanswered calls | 30 | SerpApi | `on_missing: skip` |
| Review velocity >= 5/month | 15 | SerpApi | `on_missing: skip` |

The last two are **dormant, not deleted** (ADR-020). Basic-tier leads skip
them and normalise over 100; enriched leads apply them and normalise over
145. Both produce comparable 0–100 scores, and `coverage` reports which tier
a lead is on — no `enrichment_tier` column, no second ruleset, no branching.

**80 of 100 always-on pain points now come free from Serper**, so a dead
website no longer zeroes the pain track — the coverage hole ADR-014 created
is closed.

`has online booking` (+20 fit) and `no booking link` (+25 pain) are deliberate
inverses. Having booking means they buy intake tooling; not having it means
every lead is a phone call. Both are true, and the two-track model is what
lets them coexist without cancelling out.

**`is_24_7` is tracked but not scored.** A 24/7 claim means they have thought
about coverage; it says nothing about whether the coverage is any good. Only
review complaints answer that — which is exactly what the ADR-020 enrichment
pass buys back for the top leads.

**Every surviving pain rule comes from the website scrape.** A dead website
therefore means `pain_score` has zero applicable rules and `coverage` is 0 on
that track — the dashboard must show this rather than rendering a misleading
low score. Pain is now a *proxy for* missed calls rather than evidence of
them; the ADR-013 recovery option restores the evidence-based rules.

### Missing data

Each rule has an `on_missing` behaviour, defaulting to **`skip`**, not zero.

```
fit_score = points_earned / points_from_APPLICABLE_rules * 100
```

Skipped rules leave the denominator, keeping scores comparable. Every
business carries a **`coverage`** percentage. A score of 74 at 45% coverage
is a guess wearing a number's clothing; the dashboard must show it as such.

### Three-pass qualification

```
Pass 1 (automatic, broad)   ~105 businesses scored on Serper + website
                            signals. Review rules skipped, coverage ~65%.

Pass 2 (automatic, narrow)  top 25 by fit -> SerpApi free-tier reviews
                            -> re-score. Coverage 100%, evidence quotes
                            available. ~50 free searches.

Pass 3 (manual)             Apollo employee lookup + office-admin check on
                            those 25 -> re-score -> final ranking.
```

Each pass spends a scarcer resource on a smaller set: Serper credits are
plentiful, SerpApi free searches are capped monthly, and your own time is the
scarcest of all.

Apollo free-tier credits are spent on pre-qualified businesses only.

### Versioning

Editing a ruleset creates a new version; the old one is never mutated.
`score --ruleset hvac_v2` adds rows alongside `hvac_v1`. Once `outcomes` has
data, the comparison becomes empirical: *did v2 rank the won deals higher
than v1 did?*

### Output

```json
{
  "fit_score": 78, "pain_score": 65, "quadrant": "go_now", "coverage": 1.0,
  "reasons": [
    {"rule": "field_service_software", "track": "fit", "matched": true,
     "points": 30, "label": "Uses ServiceTitan"},
    {"rule": "closed_weekends", "track": "pain", "matched": true, "points": 30,
     "label": "Closed Saturday and Sunday in an emergency trade"},
    {"rule": "missed_call_complaints", "track": "pain", "matched": true,
     "points": 30,
     "label": "4 recent reviews mention unanswered calls",
     "evidence": ["Called 3 times, no answer, went with someone else",
                  "Left two voicemails over a week, never heard back"]}
  ]
}
```

Evidence quotes justify the score and serve as the opening line of outreach.

---

## 8. Backend architecture

### Dependency rule

```
api  ->  services  ->  repositories  ->  database
            \
             domain   (imports NOTHING: no FastAPI, no SQLAlchemy, no HTTP)
```

Dependencies point inward. `domain/` is pure. **Enforced by `import-linter`
in CI** — a build failure, not a convention.

### Layout

```
backend/
├── app/
│   ├── api/routers/          runs, businesses, contacts, rulesets
│   ├── schemas/              Pydantic DTOs
│   ├── services/             use cases (shared by CLI and API)
│   ├── repositories/
│   ├── models/               SQLAlchemy
│   ├── domain/               PURE: scoring/, extractors/, rules/, resolvers/
│   ├── clients/              serpapi, firecrawl (behind Protocols)
│   ├── pipeline/             stages + APScheduler
│   └── core/                 config, db, logging, errors
├── alembic/
├── config/                   verticals.yaml, locations.yaml, rulesets/
├── tests/                    unit/, integration/, fixtures/
├── cli.py                    Typer
├── Dockerfile
└── pyproject.toml
```

### Patterns used

**Architectural**

| Pattern | Where |
|---|---|
| Pipes and Filters | The staged pipeline; the database is the pipe |
| Layered / Clean Architecture | api → services → repositories, domain at the centre |
| Functional Core, Imperative Shell | Network half at the edges, pure logic in the middle |
| Client–Server / API-first | Next.js as pure presentation |
| Polling Consumer | Scheduler picking up `queued` runs |

**Enterprise (PoEAA)**

| Pattern | Where |
|---|---|
| Repository | `repositories/` |
| Service Layer | `services/` — one use case per class |
| Data Mapper | SQLAlchemy ORM (not Active Record) |
| Data Transfer Object | Pydantic schemas at the API boundary |
| Unit of Work | Transaction scoped per business, not per run |

**Gang of Four**

| Pattern | Where | Problem solved |
|---|---|---|
| Strategy | `domain/extractors/`, operator dispatch | Adding a signal doesn't modify existing ones |
| Chain of Responsibility | `domain/resolvers/` (v2) | Try handlers cheapest-first, stop on success |
| Adapter | `clients/` behind Protocols | Swap Firecrawl→Playwright in one file; `FakeScraper` in tests |
| Template Method | `pipeline/Stage` base | Retry, logging, error capture written once |
| Interpreter (light) | `domain/rules/` | Rules change without code changes |

**Also:** State Machine (`businesses.status`), Dependency Injection
(FastAPI `Depends`).

**Deliberately not used:** CQRS, event sourcing, message bus, DDD aggregates,
generic `BaseRepository[T]`, abstract factories. Create an interface only
when there is a second implementation or a test fake is needed.

### Execution

Stages are services. Both entry points call the same code:

```
CLI:   python -m cli score --run-id 17    ->  ScoreRunService.execute()
API:   POST /runs/17/score                ->  ScoreRunService.execute()
```

**APScheduler runs in-process** inside the FastAPI container:

- every 30s — pick up `queued` runs and execute them
- monthly — refresh businesses older than 90 days
- nightly — retry `failed` rows under an `attempt_count` cap
- on startup — reset runs stuck in `running` for >1h back to `queued`

One container, no Redis, no Celery. Known limitation: two FastAPI instances
would double-execute; the fix at that point is a Postgres advisory lock.

---

## 9. Frontend

**Next.js App Router on Vercel.** Server Components `fetch()` the FastAPI
API. No direct database access from Next.js. **shadcn/ui** is the design
system foundation (components copied into the repo, Radix primitives
underneath).

### Screens

1. **New Search** — vertical / state / results-per-query dropdowns → confirm
   screen showing the expansion (`3 terms × 5 metros = 15 searches`),
   estimated result count, estimated cost, and a warning for searches already
   run in the last 30 days with a "skip them" option. Nothing is spent until
   confirmed.
2. **Runs** — list with status; polls while `running`.
3. **Leads** — the primary screen. Data table (TanStack Table) defaulting to
   `quadrant = go_now`, sorted by fit × pain. Filters for quadrant, vertical,
   state, ruleset version, outcome. CSV export of the filtered set.
4. **Lead detail** — score breakdown with every rule's reason and verbatim
   review evidence; forms for `manual_facts`, `contacts`, and outcome status.
   Keyboard-navigable with next/previous, since the manual pass runs through
   ~30 leads at a time.
5. **Ruleset compare** — v1 vs v2 side by side. Cut from v1 if time is tight.

### Domain tokens

Four semantic tokens define the scoring vocabulary once: `go-now`,
`nurture`, `low-fit`, `cold`.

Project components composed from shadcn primitives:

| Component | Purpose |
|---|---|
| `<ScorePair fit pain />` | Always shows both numbers — never one alone |
| `<QuadrantBadge />` | The four states, one visual language |
| `<CoverageIndicator />` | Flags low-coverage leads so a score isn't over-read |
| `<EvidenceQuote />` | Verbatim review quotes, easy to copy for outreach |
| `<SignalBadge />` | LSA, ServiceTitan, Jobber, Google Ads |

Dark mode via `next-themes`.

### Auth

Users authenticate at the Next.js edge (middleware + password env var for a
single user). Next.js passes a service token (`X-API-Key`) to FastAPI.
FastAPI is never publicly browsable. Clerk is the upgrade path when a second
user exists.

---

## 10. Error handling and operations

### Four failure kinds

| Kind | Example | Response |
|---|---|---|
| Transient | Timeout, 429, 502 | Retry with backoff — 3 attempts, 1s/4s/16s, respect `Retry-After` |
| Permanent for this business | Dead domain, parked page, 404 | **Not an error — it's data.** `website_status='dead'`, continue with reduced coverage |
| Permanent for the run | Bad API key, out of credits | **Abort the run.** Circuit breaker: 5 consecutive auth/quota errors |
| Bug | Parser crash, unexpected payload | Capture traceback, mark that business `failed`, continue |

Retry only on timeouts, connection errors, 429, and 5xx. Never on other 4xx.

### Isolation

Each business is processed in its own transaction; a crash on business 47
leaves 1–46 committed. Failures are recorded on the row (`failed_stage`,
`error_message`, `attempt_count`) and retried nightly under a cap.

### Budget guard

`runs.max_cost_usd`, checked between businesses from `api_calls` totals.
Aborts the run if exceeded. Necessary because a dropdown change can 10× a
run's size.

### Observability

`structlog` with JSON output, binding `run_id` / `business_id` / `stage`.
Sentry free tier for exceptions. `/health` for the container healthcheck.

### Config

One `pydantic-settings` class that fails at startup on missing values:
`DATABASE_URL`, `SERPAPI_KEY`, `FIRECRAWL_KEY`, `API_KEY`, `SENTRY_DSN`.
`.env` locally, platform env vars in production, nothing committed.

---

## 11. Testing

### Backend

| Layer | Method | Volume |
|---|---|---|
| `domain/` | Pure functions, real captured fixtures, no mocks, no DB | Most |
| `repositories/` | Real Postgres (compose container), rollback per test | Some |
| `services/` | Fake repos + fake clients via Protocols | Some |
| `api/` | FastAPI `TestClient`, happy + error paths | Few |

**Fixtures come from real captured responses** — genuine Serper JSON and
genuine messy HTML from real HVAC sites, sanitized and committed under
`tests/fixtures/`. Synthetic fixtures only test the parser against imagined
input.

**Golden tests for scoring:** ~10 businesses with known signals and expected
scores, so a ruleset change produces a readable diff of what moved.

**Live contract tests:** one per client, marked `@pytest.mark.live`, excluded
from CI, run manually to catch provider API drift.

Tests are written first for `domain/`.

### Frontend

**Playwright against a seeded real backend**, not mocks. FastAPI runs in
docker-compose with a deterministic seed of ~20 businesses with known scores.
External APIs are replaced by the `FakeScraper` / `FakeSearchProvider`
adapters, so tests spend nothing.

**Page Object Model** — one class per screen exposing intent-level methods.
Selector churn edits one file, not fifteen tests.

**User stories to cover:**

1. Log in / blocked when unauthenticated
2. Create a search → confirm screen shows correct expansion and cost
3. Duplicate-query warning; skipping reduces the count
4. Cancel from confirm → nothing queued
5. Run progresses queued → running → complete
6. Failed run shows its reason
7. Leads list defaults to `go_now`, correctly sorted
8. Filter by quadrant, state, outcome; sort by fit and pain
9. Lead detail shows score breakdown with evidence quotes
10. Add manual facts → score changes after re-scoring
11. Add a contact email
12. Set an outcome status
13. Export CSV of the filtered set
14. Empty states — no runs, no matching leads
15. API unreachable → real error, not a blank page

`@axe-core/playwright` accessibility assertion on each main screen. Runs in
CI on pull requests. Visual regression snapshots deferred — noise while the
UI is still moving.

---

## 12. Deployment

| Piece | Where | Notes |
|---|---|---|
| Postgres | Neon | Alembic owns all migrations |
| FastAPI + scheduler + CLI | Railway or Render | One Docker image, ~$5/mo |
| Next.js | Vercel | Built from source |

**One image, multiple entrypoints:**

```
uvicorn app.main:app                          # API + scheduler
python -m cli score --run-id 17               # one-off CLI
alembic upgrade head                          # migrations
```

**Migrations run as a pre-deploy step, never on container startup** — a bad
migration must fail the deploy, not take down the running app.

Local development: `docker compose up` provides Postgres + API; Next.js runs
on the host against `localhost:8000`.

Image is ~200 MB. Dropping Playwright from scraping avoided a browser
runtime roughly 8× larger.

---

## 13. Deferred to v2

| Item | Seam already in place |
|---|---|
| Automated contact discovery | `contacts` table with `source`/`confidence`; `domain/resolvers/` stub; raw payloads retained for backfill without re-scraping |
| Email outreach automation | `suppressions` table; `outcomes.source` accepts `email_event`; `verification_status` on contacts |
| Free-text natural-language search | `SearchPlan` is the contract; an LLM parser is a second front door producing the same object |
| LLM lead qualification | `outcomes` + `signals` become the labelled training data |
| Marketing-agency vertical | Separate ruleset; reseller motion, different criteria |
| Parallel workers | Stages are already idempotent and independent |
| Multi-tenancy | Deliberately absent; auth is a single service token today |

**Known warning for v2:** cold outreach must not be sent through Resend,
SendGrid, or Postmark — their terms prohibit it. Purpose-built tooling
(Instantly, Smartlead) handles inbox rotation, warmup, and separate sending
domains.

**Contact discovery sources identified for v2** (free public registries beat
LinkedIn on accuracy and legal risk):

| Vertical | Source |
|---|---|
| Healthcare clinics | NPPES / NPI Registry — free official API and monthly bulk file |
| HVAC / home services | State contractor license boards (CSLB, TDLR) — bulk CSV downloads |
| Law firms | State bar member directories |
| Hospitality | Liquor licences, health inspection records |
| All | Secretary of State filings; OpenCorporates as aggregator |
| All | BBB "Principal Contacts"; Yelp "Meet the Business Owner"; owner-signed Google review replies |
| Law / agencies | LinkedIn profile URLs via Serper `/search` (`site:linkedin.com/in "owner" <company>`) — never by touching LinkedIn directly |

These are loaded as **local reference tables refreshed monthly**, not called
per lead — making owner identification effectively free at high coverage.

---

## 14. Assumptions and open questions

**Assumptions carried into implementation:**

- Scoring weights in `hvac_v1` are guesses and will be recalibrated once
  `outcomes` has 30–50 contacted leads.
- Cost estimates (Serper $0.30–1.00/1k credits with 2 credits per >10-result
  page, Firecrawl ~$0.001–0.002/page) are approximate and must be verified
  against current pricing before the budget guard's defaults are set. Total
  expected cash cost is under ~$5/month, essentially Firecrawl alone.
- **Corrected by real data:** the estimate that 200+ review HVAC companies
  are ~10–15% of a metro was wrong — 13 of 20 records in a real Houston
  sample cleared it. The gate is removed entirely (ADR-022); `ratingCount` is
  now a segment label.
- **The ICP itself is unvalidated and deliberately so.** v1 segments rather
  than filters, and `outcomes` is the instrument that will settle it. Revisit
  after 30–50 contacted leads spread across all four segments.
- Whether `is_24_7` businesses actually answer after hours is unknowable from
  Serper data alone; only review complaints answer it, via the ADR-020
  enrichment pass.
- Meta Ad Library API access for non-political ads is uncertain; Google Ads
  and LSA detection do not depend on it.
- Serper's `/maps` endpoint may expose `operating_hours`, which would move
  three pain rules off the website scrape and onto Google. Unverified; worth
  15 minutes before implementation.
- **RISK (deferred, ADR-015) — LSA detection may not be available.** Sources conflict on whether
  Google has discontinued the Local Services API and whether SerpApi's
  `google_local_services` engine is being retired; SerpApi's own docs page
  shows no deprecation notice, while other sources state Maps is the
  replacement. This must be resolved **before implementation**, because
  LSA rules have since been removed from `hvac_v1` entirely (ADR-015), so
  this no longer blocks implementation. Revisit only after outreach is
  running — an LSA-based rule would be the sharpest cold-call opener
  available, which justifies the research then, not now.
- Cost per run is **~240 Serper credits** (24 queries x 5 pages x 2 credits),
  **~525 Firecrawl pages** (~105 survivors x 5), and **~50 SerpApi free-tier
  searches** (25 enriched leads x 2 calls). Serper's 2,500 free credits cover
  ~10 runs; SerpApi's 250/month allowance covers 4–5 runs and is the binding
  monthly constraint.
- Volume target is ~50–200 businesses/week (single metro + vertical per run).

**Open for the implementation plan:**

- Field-service-software fingerprints (ServiceTitan, Jobber, Housecall Pro)
  need to be captured from real sites before `extract_signals` can be
  written. This is a concrete first task.
- The missed-call complaint matcher starts as keyword matching over review
  text; precision must be measured on real reviews before deciding whether an
  LLM pass is warranted.
