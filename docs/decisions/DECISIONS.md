# Decision Log

Every significant decision, why it was made, and what it costs. Append new
entries; never rewrite an old one. If a decision is reversed, add a new entry
that supersedes it and mark the old one `Superseded by ADR-NNN`.

Format: **Context → Decision → Why → Consequences.**

---

## ADR-001 — Staged pipeline over a database, not a single script

**Status:** Accepted (2026-08-27)

**Context.** Five steps: discover, fetch place, scrape site, extract signals,
score. They could run as one function per business, or as independent stages.

**Decision.** Independent stages. Each business is a row with a `status`; each
stage selects rows in one status, processes them, advances the status.

**Why.** The scoring rules are unproven and will be tuned dozens of times. In
a straight-line script, every rule change means re-scraping every website and
re-paying for it — which quietly discourages experimenting. With stages, the
expensive half runs once per business ever, and re-scoring is free and
instant.

**Consequences.** ~1 extra day of scaffolding. State discipline required; a
botched status transition can strand rows, so the dashboard needs a status
view. Five commands instead of one (`run_all` wraps them). Grows into
parallel workers later without redesign.

---

## ADR-002 — Split the pipeline into a network half and a pure half

**Status:** Accepted (2026-08-27)

**Context.** Some stages call paid, flaky APIs. Others are pure computation.

**Decision.** Stages 1–3 do all I/O and write raw payloads to Postgres.
Stages 4–5 are pure functions over stored data, with no network access.

**Why.** The unreliable code and the interesting code are different code. The
scoring logic changes constantly; the API calls never do. Separating them
means logic changes cost nothing and are trivially testable.

**Consequences.** Raw payload storage grows (~0.5–1 MB/business). The
`domain/` layer is import-restricted, enforced by `import-linter` in CI. Test
fixtures come free — stored payloads *are* the fixtures.

---

## ADR-003 — Raw payloads are retained permanently; derived tables are rebuildable

**Status:** Accepted (2026-08-27)

**Context.** Parse-and-discard is the default instinct and saves storage.

**Decision.** Store full API responses and raw HTML forever. `reviews`,
`signals`, and `scores` are derived and may be dropped and regenerated.

**Why.** Parsing destructively bets that today's parser knows what tomorrow
needs. It doesn't. Adding a new signal in two weeks becomes "run one command"
instead of "re-scrape 800 sites and pay twice." This is also what makes
deferring contact discovery safe — the data to backfill it is captured now.

**Consequences.** Storage cost. Neon's free tier is 0.5 GB; escape hatch is
moving `raw_text` to Vercel Blob with a pointer.

---

## ADR-004 — Two scores (fit and pain), never one blended number

**Status:** Accepted (2026-08-27)

**Context.** The stated ICP (200+ reviews, running ads, uses ServiceTitan,
10–40 employees, $2–10M revenue) is entirely about whether a business *can
buy*. It says nothing about whether they have a problem.

**Decision.** Every business gets an independent `fit_score` and
`pain_score`, combined only for ranking, plus a `quadrant`
(`go_now` / `nurture` / `low_fit` / `cold`) at a 60/60 threshold stored in
the ruleset.

**Why.** A 95-fit / 5-pain company is a nice logo you will never close. A
30-fit / 90-pain company is desperate and broke. A single blended "71" hides
which one you are looking at.

**Consequences.** More to display. The dashboard must always show both
numbers together, hence the `<ScorePair>` component.

---

## ADR-005 — Rule-based scoring stored as versioned data, not code

**Status:** Accepted (2026-08-27)

**Context.** Options were manual review, rules, LLM qualification, or rules
then LLM.

**Decision.** Rules only, defined as JSON/YAML in a `rulesets` table with a
fixed operator set. Editing creates a new version; old versions are never
mutated. `scores` is keyed on `(business_id, ruleset_version)`.

**Why.** Rules must be tunable without a deploy. Versioning means tuning
*adds* a scoring rather than overwriting one, so two rulesets can be compared
on the same businesses — otherwise every experiment destroys the evidence of
the last one. LLM qualification is deferred until `outcomes` shows what rules
miss.

**Consequences.** Thresholds must be guessed up front and are expected to be
wrong. `scores` grows by one row per business per ruleset version.

---

## ADR-006 — `outcomes` table built on day one, though unused for weeks

**Status:** Accepted (2026-08-27)

**Context.** Outcome tracking has no immediate value and could be added later.

**Decision.** Build it now — a status dropdown per lead, ~1 hour of work.

**Why.** `scores` is a *prediction*; `outcomes` is the *ground truth* that
says whether the prediction was any good. Without it, "are my rules working?"
is unanswerable. Retrofitting after 300 calls means 300 lost data points. It
also prevents contacting the same business twice.

**Consequences.** One extra table and one form field. Becomes the labelled
training data if LLM scoring is added later.

---

## ADR-007 — Contact discovery deferred to v2, with the seam built now

**Status:** Accepted (2026-08-27)

**Context.** Finding owner names and emails is a project of its own.

**Decision.** Defer the resolvers. Create the `contacts` table now and
populate it **manually** in v1 with `source='manual'`.

**Why.** Manual entry teaches you what good data looks like before automating
it. Because manual and automated contacts land in the *same table*
distinguished by `source`, v2 requires no migration and no dual path — the
resolvers just start inserting rows.

**Consequences.** Manual work in v1. Requires an add-contact form and CSV
export in the dashboard.

---

## ADR-008 — Manual data lives in its own permanent table

**Status:** Accepted (2026-08-27)

**Context.** Employee counts come from a manual Apollo lookup. The obvious
place is `signals`.

**Decision.** A separate `manual_facts` table. `extract_signals` derives from
raw payloads, then overlays manual facts on top.

**Why.** `signals` is rebuilt every time a new signal is added. Manual values
stored there would be silently wiped. This also rescues the two ICP criteria
that cannot be detected (`has_office_admin`, `owner_growth_focused`) — they
become optional rules with `on_missing: skip`, so an unresearched business is
not penalised, just lower `coverage`.

**Consequences.** One extra table and a merge step. Enables the two-pass
model: automatic scoring surfaces ~30 leads, manual research sharpens them.

---

## ADR-009 — FastAPI owns all database access; Next.js goes through the API

**Status:** Accepted (2026-08-27)

**Context.** Next.js Server Components could read Neon directly, removing a
network hop and an entire service.

**Decision.** All reads and writes, including server-side, go through
FastAPI. Next.js is a pure presentation layer.

**Why.** Direct-DB access means two languages writing one schema, two places
for validation, and no single home for business logic. It also means the
dashboard could only *queue* work; with an API, the CLI and the dashboard
call the same service methods.

**Consequences.** A third deployable. FastAPI must be hosted (Railway/Render,
~$5/mo). Extra latency per request. Python owns Alembic migrations; the
frontend never runs DDL.

---

## ADR-010 — APScheduler in-process, not Celery or a separate worker

**Status:** Accepted (2026-08-27)

**Context.** Scraping takes minutes, so it cannot run inside an HTTP request.
Something must pick up queued runs.

**Decision.** APScheduler running on a background thread inside the FastAPI
container, polling every 30s.

**Why.** At ~30 businesses/day, Celery buys distributed workers and priority
queues — real capabilities — at the cost of Redis, worker processes, and a
much harder debugging story. One container, no broker.

**Consequences.** A container restart kills an in-flight run; the status
machine makes recovery a re-run, and stuck runs self-heal on startup. Two
FastAPI instances would double-execute — fix at that point is a Postgres
advisory lock.

---

## ADR-011 — Dropdowns in v1, free-text search deferred

**Status:** Accepted (2026-08-27)

**Context.** A free-text search box needs an LLM to parse queries into search
parameters, plus a confirm step so it never silently spends money.

**Decision.** Vertical picker, state picker, results-per-query field. The
confirm-before-run screen stays and is now fully deterministic.

**Why.** Speed to first leads. Free text is nicer and is the right call once
this is handed to someone else, but it is a day of work solving a problem one
user does not have.

**Consequences.** The `SearchPlan` object remains the contract, so an LLM
parser is a second front door later — additive, not a rewrite.

---

## ADR-012 — Firecrawl for site scraping; no Playwright in the pipeline

**Status:** Accepted (2026-08-27)

**Context.** Options were browser automation in a VM, or a scraping API.

**Decision.** Firecrawl v2, requesting `markdown` + `rawHtml` + `links`, with
`only_main_content=False`. Behind a `WebScraper` Protocol.

**Why.** ~80% of small-business sites are server-rendered; a browser is
overkill. Firecrawl replaces "HTTP client + parser + Playwright fallback"
with one call. `rawHtml` is mandatory — every fingerprint signal lives in
script tags that markdown strips. `only_main_content` defaults to `True` and
removes footers, where small-business contact details live.

**Consequences.** Per-page cost (negligible at this volume). Docker image
stays ~200 MB instead of ~1.5 GB with a browser. Playwright returns as a
**test** dependency only.

---

## ADR-013 — Serper for discovery, not SerpApi or Tavily

**Status:** Accepted (2026-08-27) — **supersedes the SerpApi choice in the
original spec**

**Context.** Three candidates evaluated against the pipeline's needs and
cost.

| | Maps data | Review text + dates | rawHtml | $/1k |
|---|---|---|---|---|
| SerpApi | yes | **yes** (`iso_date`) | n/a | $9.17–25 |
| Serper | yes | **no** (counts only) | n/a | $0.30–1.00 |
| Tavily | **no** | no | **no** | $5–8 |

**Decision.** Serper as the sole discovery provider for v1. LSA detection
dropped. Businesses judged on `rating` and `ratingCount`.

**Why.** Priority is reaching email outreach fast and cheap. Serper's 2,500
free credits (valid 6 months) cover roughly ten discovery runs at zero cost,
versus SerpApi's 250/month which does not cover one full run. Tavily was
eliminated outright: no business listings, and `format` accepts only
`markdown`/`text`, so it cannot return the raw HTML every fingerprint signal
depends on.

**Consequences — significant, accepted knowingly.**
- **~70 of 100 pain points are lost.** Missed-call complaint mining (30) and
  review velocity (15) need dated review text Serper does not return; LSA
  rules (25) are deferred. The pain track is rebuilt from website-derived
  signals only (see ADR-014).
- **No evidence quotes.** The verbatim "nobody answered the phone" review
  snippets were both the strongest score justification and the intended
  opening line of outreach emails. Gone until reviews are sourced.
- **Pain coverage now depends entirely on the website scrape.** A dead
  website means `pain_score` has zero applicable rules.
- **`cid` replaces `place_id`** as the dedupe key.
- **`phoneNumber` is unreliable.** In a 10-record sample, 2 records returned
  the street address in the phone field. Requires format validation and a
  `phone_is_valid` flag; invalid phones must not reach a dialler.
- **`operating_hours` absent** from the `/places` payload, so hours-based
  rules must come from the scraped website instead. Serper's `/maps` endpoint
  may include hours — unverified.
- Serper's `/places` returns ~10–20 results per call; >10 results costs 2
  credits instead of 1.

**Recovery option — ADOPTED, see ADR-020:** SerpApi's free tier is
250 searches/month and reviews cost ~3 calls per business — about **80
businesses/month of full review data at no cost**. Spent surgically on the
top ~30 leads *after* Serper ranks them, this restores complaint mining and
evidence quotes exactly where they matter, with no paid vendor and no change
to the pipeline shape. Requires a second `SearchProvider` adapter.

---

## ADR-014 — Reweighted `hvac_v1` for Serper-only data

**Status:** Accepted (2026-08-27), **amended by ADR-020** — the review-based
pain rules return as dormant rules rather than being deleted

**Context.** ADR-013 removed the three highest-weighted pain rules and the
highest-weighted fit rule.

**Decision.** Reweight both tracks using only signals actually obtainable.

**Fit (100)** — `ratingCount` 500+ → 25 (200–499 → 15); field-service
software → 25; Google Ads tag → 20; estimated employees 10–40 → 20; rating
≥ 4.0 → 10.

**Pain (100)** — phone-only intake → 40; no 24/7 or emergency claim on the
website → 25; hours close before 6pm → 20; not open weekends → 15.

**Why.** Every surviving pain signal now comes from the scraped website
rather than Google. HVAC sites routinely advertise "24/7 emergency service"
in a header banner, and publish their hours — often more reliably than GMB.

**Consequences.** Pain is lower-resolution than designed and is a *proxy for*
missed calls rather than evidence of them. Weights are guesses and must be
recalibrated once `outcomes` has 30–50 contacted leads. If the ADR-013
recovery option is adopted, the review-based pain rules return and these
weights change again.

---

## ADR-015 — LSA detection deferred

**Status:** Accepted (2026-08-27)

**Context.** Local Services Ads bill per phone call, making "runs LSA but
closes at 5pm" the only provable, quantifiable loss in the whole ruleset.
Sources conflict on whether the underlying Google API is being discontinued,
and Serper's LSA support is unverified.

**Decision.** Drop LSA from `hvac_v1`. Google Ads presence is still detected
independently via gtag tags in scraped HTML.

**Why.** Resolving it would block the path to outreach, and the answer is
genuinely uncertain.

**Consequences.** Loses the sharpest cold-call opener available. Revisit once
outreach is running — the payoff justifies the research then, not now.

---

## ADR-016 — shadcn/ui, and Playwright for frontend testing

**Status:** Accepted (2026-08-27)

**Decision.** shadcn/ui as the design system foundation; Playwright E2E
against a seeded real backend with faked external APIs.

**Why.** shadcn components are copied into the repo rather than installed, so
they are editable, and Radix underneath gives keyboard navigation and ARIA
for free — which matters on the lead-detail screen worked through 30 leads at
a time. Playwright runs against the real FastAPI in docker-compose because
mocking the API would only test that the mocks match imagination; the
`FakeScraper` adapters mean zero API spend during tests.

**Consequences.** Playwright is a dev dependency only and never enters the
Docker image. Visual regression snapshots deferred until the UI stabilises.

---

## ADR-017 — Single Docker image with multiple entrypoints

**Status:** Accepted (2026-08-27)

**Decision.** One image runs the API, the scheduler, the CLI, and migrations,
selected by command. Next.js is not containerised (Vercel builds it).
Migrations run as a pre-deploy step, never on container startup.

**Why.** The API and CLI already share the service layer, so a second image
would only create drift. Running migrations on startup means a bad migration
takes down the running app instead of failing the deploy, and two instances
race each other.

**Consequences.** Deploy configuration must set a pre-deploy command.

---

## ADR-018 — Small-batch volume (~50–200 businesses/week)

**Status:** Accepted (2026-08-27)

**Decision.** Target one metro + one vertical per run, sequential processing,
no parallelism.

**Why.** The scoring rules are unproven. At 10k leads a wrong assumption is
expensive to discover and expensive to re-scrape. Small batches let the rules
earn their thresholds against real outcomes first.

**Consequences.** Sequential runs take minutes, which is fine. The narrow ICP
means discovery must **over-collect and prefilter hard** — deep pagination,
then drop everything under 200 reviews before any paid enrichment.

---

## ADR-019 — v1 ships the HVAC ruleset only

**Status:** Accepted (2026-08-27)

**Decision.** Healthcare clinics, law firms, and hospitality use the same
engine and pipeline but are added after HVAC is validated against real
outcomes. Marketing agencies are excluded entirely from v1.

**Why.** Each vertical needs its own search terms and pain signals — a law
firm's pain is after-hours intake going to voicemail; a clinic's is
appointment booking. Adding a vertical is a config change, not a code change,
so there is no cost to waiting. Marketing agencies do not take high-stakes
inbound customer calls at all; they are a reseller motion with entirely
different criteria.

**Consequences.** Three of four target verticals wait for validation.


---

## ADR-020 — Two-tier enrichment: Serper broad, SerpApi free tier narrow

**Status:** Accepted (2026-08-27) — adopts the recovery option in ADR-013 and
amends ADR-014. Pain weights further revised by ADR-021.

**Context.** ADR-013 removed review-derived signals, costing 45 pain points
and the verbatim evidence quotes intended as cold-email openers. SerpApi's
free tier is 250 searches/month and reviews cost ~2 calls per business, which
is enough for roughly 100 businesses — far fewer than the ~105 that survive
prefiltering, but far *more* than the number actually contacted in a week.

**Decision.** Two enrichment passes.

1. **Broad pass** — Serper discovery + Firecrawl scrape + score, across all
   prefilter survivors (~105/run). Review rules are skipped.
2. **Narrow pass** — after scoring, fetch full review corpora from SerpApi's
   free tier for the **top N by fit score** (default `N = 25`), then re-run
   `extract_signals` and `score`.

**Why.** Review data is simultaneously the most expensive and most valuable
input. Buying it for 105 businesses when 25 get contacted wastes ~75% of a
monthly allowance that does not roll over. Ranking on cheap signals first,
then spending the scarce budget on the winners, gets full-quality data
precisely where it is used — at no cash cost.

`N = 25` rather than 30: at 4 runs/month, 30 consumes 240 of 250 free
searches (96%), leaving no headroom for a retry storm. 25 uses 200 (80%).
Configurable as `enrichment_top_n`.

**Why it needs no new machinery.** `fetch_reviews` sets the business back to
`site_scraped`; stages 4–5 re-run naturally because they are free and
idempotent (ADR-002). The tier difference is expressed entirely through the
existing `on_missing: skip` mechanism (ADR-005) — review rules are dormant
for basic-tier leads and active for enriched ones. One ruleset, one `scores`
row per business, upserted. **`coverage` is what distinguishes the tiers**, so
no `enrichment_tier` column, no branching, and no second ruleset are needed.
The mechanism built for dead websites absorbs this case unchanged.

**Consequences.**
- Restores `missed_call_complaints` (30 pain points), `review_velocity` (15),
  and the verbatim evidence quotes — for the top 25 leads only.
- Pain normalises over 100 points at basic tier and 145 at enriched tier.
  Both yield comparable 0–100 scores; `coverage` reports the difference.
- A **second `SearchProvider` adapter** (SerpApi) alongside Serper.
- **The budget guard must track SerpApi calls against a monthly ceiling**,
  not only per-run cost, because the free allowance resets monthly and is the
  binding constraint. Exceeding it silently degrades every subsequent run to
  basic tier.
- Caps throughput at ~4 runs/month before SerpApi needs paying for. At that
  point the options are a paid tier or fewer enriched leads per run.
- Total cash cost of the system stays under ~$5/month (Firecrawl only).


---

## ADR-021 — Use Serper `/maps`, not `/places`

**Status:** Accepted (2026-08-27) — supersedes the `/places` usage in ADR-013

**Context.** A real `/maps` response for "hvac businesses in Houston"
(20 records) was compared against the `/places` shape used until now.

**Decision.** Use `/maps` as the sole discovery endpoint.

**Why.** Same cost, strictly more data. `/maps` additionally returns:

| Field | Worth |
|---|---|
| `openingHours` | Full 7-day schedule. **Moves every hours-based pain rule off the website scrape onto Google**, closing the dead-website coverage hole from ADR-014 |
| `bookingLinks` | Contains `book.servicetitan.com` / `book.housecallpro.com` URLs directly. **Field-service software detection becomes free at discovery** — no scraping needed. Absence of the key is itself the phone-only-intake pain signal |
| `types[]` | Full category array, better vertical filtering than a single `type` |
| `placeId`, `fid` | Real Google place ID alongside `cid` |
| `credits` | The response self-reports actual cost — `api_calls` logs real spend, not estimates |

**Consequences.**
- ~65 of 200 scoring points become obtainable at discovery with no scrape.
- Firecrawl's remaining job shrinks to chat widgets, gtag, contact forms,
  24/7 claims, and team pages.
- **Hours need validation.** One record returned `"Thursday": "8 AM–5 AM"` —
  an obvious parse error. Unparseable days must be stored null, never
  guessed.
- Some records omit `address` entirely (service-area businesses with no
  storefront) and many omit `bookingLinks` as an absent key rather than an
  empty array.
- `rating` is useless as a discriminator: all 20 records rated **4.6–5.0**.
  The `rating >= 4.0` rule fired for 100% of candidates and is removed.

---

## ADR-022 — ICP is an open hypothesis: segment, do not filter

**Status:** Accepted (2026-08-27) — supersedes the review-count prefilter and
the review-count fit rule

**Context.** The stated ICP (10–40 employees, 200+ reviews, $2–10M revenue)
was an explicit thesis: growing SMBs still small enough to miss calls, on the
assumption that large high-review companies already run call centres.

The Houston sample tests part of that thesis and does not support it. Review
count does not predict 24/7 coverage:

```
Open 24h all week:   6,445 · 1,993 · 1,561 · 529 · 524 · 504 · 191 · 124
Closes early:        8,758 · 2,941 · 1,002 · 379 · 349 · 304 · 174 · 75 · 72 · 43
```

Companies with 124 and 191 reviews claim 24/7. Royal Air — **8,758 reviews,
the second largest in the sample — runs 8AM–5PM weekdays and is closed both
weekend days.** By the stated ICP it would have been filtered out for being
too big, while being arguably the strongest lead present.

**Decision.**

1. **The prefilter drops to "has a website."** Review count is no longer a
   gate.
2. **Review count leaves the fit score entirely in v1.** It becomes a
   `segment` label only: `emerging` (50–200), `growth` (200–2,000),
   `established` (2,000–5,000), `enterprise` (5,000+).
3. **Stratified sampling** — enrich the top ~15 per segment rather than the
   top N overall, so every run produces comparable data across the whole
   hypothesis.
4. **Company size stops being a proxy for the call-answering gap.** Hours
   measure the gap directly; size only measures ability to pay.

**Why.** Scoring on review count would bake an untested assumption into the
numbers, and the results would then confirm the assumption by construction —
the one failure mode that makes a feedback loop worthless. Segmenting instead
means `outcomes` can answer the ICP question empirically after 30–50
contacted leads:

```sql
SELECT segment, COUNT(*),
       COUNT(*) FILTER (WHERE status IN ('booked','won'))
FROM outcomes JOIN businesses USING (id) GROUP BY segment;
```

**Consequences.**
- v1 becomes an instrument for *finding* the ICP rather than a machine that
  assumes it.
- Costs **less** Firecrawl than the previous design (~60 stratified targets
  vs ~105), because discovery now carries most scoring signals for free.
- Deliberately contacting segments the thesis says are wrong is the price of
  learning whether the thesis is right. Some of those outreach attempts will
  be wasted — that is the experiment's cost, and it is small.
- `n = 20`, one metro, one vertical, top-ranked results only. Suggestive, not
  conclusive — which is exactly why it becomes a measurement rather than a
  new assumption.
- Revisit once outcomes data exists. If `enterprise` converts at zero across
  40 attempts, reinstate the gate with evidence behind it.

---

## ADR-023 — Fingerprints confirmed against live sites; all guesses were wrong

**Status:** Accepted (2026-08-29) — amends ADR-012 and ADR-014

**Context.** The `has_chat_widget` and `runs_google_ads` signals depend on
substring fingerprints in scraped HTML. The plan carried a guessed list
marked "confirm, not trust". All 20 Houston HVAC sites from the Serper sample
were fetched and inspected on 2026-08-29.

**Every guessed fingerprint scored zero hits across all 20 sites:**

```
connect.podium.com        0/20      googleadservices.com       0/20
widget.intercom.io        0/20      googleads.g.doubleclick    0/20
js.driftt.com             0/20
embed.tawk.to             0/20
code.tidio.co             0/20
```

Had these shipped, `has_chat_widget` would have been `False` for every
business forever, the `no_chat_widget` rule would have awarded 20 pain points
universally, and **nothing would have errored or failed a test.**

**Decision.** Replace the guessed list with what is actually present.

**Confirmed chat vendors** (3 of 20 sites have any chat at all):

| Fingerprint | Vendor | Sites |
|---|---|---|
| `webchat.scheduleengine.net` | ScheduleEngine | 1 |
| `app.purechat.com` | PureChat | 1 |
| `chat.housecallpro.com` | Housecall Pro | 1 |

**Confirmed exclusions** — each produced a false positive and is now asserted
against in the test suite:

| Substring | What it really is | False hits |
|---|---|---|
| `crisp` | WordPress CSS var `--wp--preset--shadow--crisp` | 11/20 |
| `rollbar` | the CSS class `.swiper-scrollbar` | 7/20 |
| `chat-widget` | Wix boilerplate `engage.wixapps.net/chat-widget-server`, present whether or not chat is enabled | 2/20 |

**Google Ads:** only the `AW-` form works (`gtag/js?id=AW-`), found on 2 of
20. `G-` is GA4 analytics, present on 5 of 20, and must never count.
**Meta Pixel:** `connect.facebook.net` / `fbq(` confirmed on 4 of 20.

**HTML adds coverage over `bookingLinks`.** Two businesses whose Serper
`bookingLinks` pointed only at their own site embed a vendor scheduler in the
page — House Pro embeds ServiceTitan, Revolution Air embeds Housecall Pro. So
`software_from_html` is kept as a secondary source worth roughly 10% extra
detection on the highest-weighted fit rule.

**Fixtures.** Four real pages are committed at
`backend/tests/fixtures/hvac_site_{uptown,mission,revair,royalair}.html` —
every `<script>` and `<link>` from the live document plus real `<form>`
elements. `royalair` is the deliberate negative case (no chat, no ads).

**Consequences.**
- Task 9's manual capture step is **done**; it is now a verification step.
- **`no_chat_widget` is a weak rule.** Only 3 of 20 sites have chat, so it
  fires for **85%** of candidates — the same low-discrimination problem that
  removed the `rating >= 4.0` rule in ADR-021. By contrast, a contact form
  with an email or tel input is present on 9 of 20, so `no_contact_form`
  would fire for 55% and separate the field far better. **Recommended:
  replace `no_chat_widget` (20 pain points) with `no_contact_form`.** Not yet
  applied — it changes `hvac_v1` weights and the golden tests, and should be
  a deliberate call.
- **`claims_24_7` is also weak** — 15 of 20 sites claim 24/7 in page text.
  Tracked, not scored, which was already the decision in ADR-021.
- Fingerprints are metro- and vertical-specific. Re-run this capture when
  adding a vertical or a very different market.

---

## ADR-024 — A read-only `repositories/` layer, for the API only

**Context.** The spec's dependency rule is `api -> services -> repositories
-> database`, but Plan 1 built no repositories: each pipeline stage queries
the session directly. Adding the layer now meant either refactoring five
reviewed, working stages or leaving the codebase with two data-access styles.

**Decision.** Introduce `app/repositories/` for the API's **read** paths
only — filtered, paginated queries the UI needs. The pipeline's
stage-scoped writes stay exactly as they are. `repositories/` never writes,
and `app/pipeline/` never imports it.

**Why.** The two have genuinely different shapes. A stage reads "every row
in status X" and writes it forward; the API reads "page 3 of go_now leads in
Texas, sorted by fit x pain". Forcing both through one abstraction would
serve neither. The alternative — refactoring the pipeline — would rewrite
the data access of code that had just passed review, with 181 tests to
rework, for no behavioural gain.

**Consequences.** Two data-access styles coexist, which is a real cost and
is why this ADR exists rather than a silent convention. An `import-linter`
contract enforces the split so it cannot erode. If the pipeline ever needs a
filtered read, that is the signal to revisit.
