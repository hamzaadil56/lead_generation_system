# Development Log — Lead Pipeline Core

**Last updated:** 2026-09-01
**Branch:** `feat/dashboard` (not yet merged)
**Status:** backend pipeline, HTTP API, scheduler, and the Next.js dashboard all
complete and reviewed — 320 backend tests, 60 frontend tests, and an 18-case
Playwright suite against the live stack all pass; `mypy` and `tsc` clean. Not
yet run against live provider APIs.

This document explains, in plain language, what exists in this repository and why.
If you are picking the project back up after time away, read this first.

---

## 1. What we are building

An agency needs customers. The customers are US service businesses — HVAC and home
services first — that lose money because nobody answers the phone after hours.
The agency sells them a voice AI that answers those calls.

This system finds those businesses automatically. It searches Google Maps, reads
their websites, looks for evidence that they are losing calls, and scores them.
The output is a ranked list you can start emailing.

It is a **lead generation pipeline**, not a CRM and not an email sender. Those come later.

---

## 2. What happened in this session

Three phases, in order. Each one produced a document that the next one used.

| Phase | Output | State |
|---|---|---|
| Brainstorming | `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md` — the design spec | Approved |
| Planning | `docs/superpowers/plans/2026-08-29-lead-pipeline-core.md` — 17 numbered build tasks | Approved |
| Building (Plan 1) | The pipeline in `backend/` — 17 tasks | Complete, reviewed, merged |
| Building (Plan 2) | The API and scheduler — 11 tasks | Complete, reviewed, merged |
| Building (Plan 3) | The Next.js dashboard — 9 tasks | Complete, reviewed |
| Building (Plan 3) | `docs/superpowers/plans/2026-09-01-dashboard.md` — the Next.js dashboard, 9 tasks | Complete, reviewed |

Every design choice made along the way is written down in
`docs/decisions/DECISIONS.md` — 27 numbered decisions, each in the form
*Context → Decision → Why → Consequences*. When you wonder "why is it done this
way", that file is the answer, not this one.

The code was built task by task. For each task, a fresh agent implemented it with
tests and committed it, then a second agent reviewed the diff against the plan, and
defects went back for a fix round with a scoped re-review. That is why the git
history reads as one clean commit per feature, with `fix:` commits where a review
found something. A final review then read the whole branch at once — see section 6,
because it is the part worth reading.

---

## 3. How the system works

Think of it as an **assembly line**. Every business is a row in the `businesses`
table, and every row carries a `status` that says how far down the line it has
travelled:

```
discovered → site_scraped → signals_extracted → scored
                                                   ↑
                             filtered_out ─────────┘ (dead ends)
                             failed
```

Each stage does exactly one job:

| Stage | File | What it does |
|---|---|---|
| **discover** | `backend/app/pipeline/discover.py` | Searches Google Maps through the Serper API. Saves each business once. Drops anything with no website. |
| **scrape_site** | `backend/app/pipeline/scrape_site.py` | Fetches the business website through Firecrawl and stores the raw HTML. |
| **fetch_reviews** | `backend/app/pipeline/fetch_reviews.py` | For the best-looking businesses only, pulls Google reviews from SerpApi's free tier. |
| **extract_signals** | `backend/app/pipeline/extract_signals.py` | Reads the saved data and works out facts: does it close at 5pm, is there a chat widget, does it use ServiceTitan, do reviews complain about missed calls. |
| **score** | `backend/app/pipeline/score.py` | Applies the scoring rules and writes two numbers per business. |

A stage only picks up rows in the status it expects, and only advances rows it
finished. So **the status column is the memory**. If the machine dies halfway
through, you re-run the command and it continues where it stopped. Nothing is
paid for twice. There is no separate job queue, no checkpoint file, no state
machine class — the database is all of it.

### The two halves

Stages split into two groups, and the split matters:

- **The expensive half** (discover, scrape_site, fetch_reviews) talks to the
  internet and spends API credits. It saves every raw response forever in
  `raw_payloads`.
- **The free half** (extract_signals, score) only reads what is already saved.

Because of that, changing your mind is cheap. Rewrite a scoring rule, delete the
derived tables, re-run the free half — costs nothing and takes seconds. You never
re-pay for data you already bought.

### The two scores

Every business gets **two** numbers out of 100, never blended into one:

- **fit** — can they afford this and do they look like the right shape of company?
- **pain** — is there evidence they are actually losing calls right now?

Those two numbers put the business in one of four boxes:

|  | high pain | low pain |
|---|---|---|
| **high fit** | `go_now` — email today | `nurture` — good company, no urgency yet |
| **low fit** | `low_fit` — hurting, can't pay | `cold` — ignore |

A single blended score would hide the difference between "perfect customer with
no problem" and "desperate company with no budget". Those need opposite actions.

### The rules live in a YAML file, not in code

`backend/config/rulesets/hvac_v1.yaml` holds the actual scoring rules. It is
versioned. Scores are saved against the ruleset version that produced them, so
tuning the rules **adds** a new set of scores rather than overwriting the old
ones — you can compare v1 against v2 on the same businesses.

### "Unknown" is not "no"

This is the subtlest part of the system and worth understanding properly.

If we could not find out whether a business runs Google Ads, that is **not** the
same as knowing they do not. So a rule marked `on_missing: skip` drops out of the
calculation entirely when its data is missing — it leaves the denominator, not
just the numerator. The score stays comparable to every other business, and a
separate `coverage` number records how much we actually knew.

Without this, a business we know nothing about would score identically to a
business we know is a bad fit, and you would waste emails on it.

---

## 4. What is in the repository

```
backend/
  app/
    core/          settings, database session, logging, error types
    models/        the database tables (SQLAlchemy)
    domain/        pure logic — no network, no database, no framework
      rules/         the scoring engine
      extractors/    turns raw data into facts
      hours.py       parses Google opening hours
      phone.py       validates US phone numbers
      segments.py    buckets businesses by review count
      booking.py     recognises booking-software vendors
      sampling.py    picks a fair sample across segments
    clients/       the outside world — Serper, Firecrawl, SerpApi, plus fakes
    pipeline/      the five stages
    services/      search plan, rulesets, budget guard, CSV export, outcomes
  cli.py           the Typer command line — the only entry point today
  config/          verticals, locations, and the scoring ruleset
  tests/           181 test cases
  alembic/         database migrations
frontend/                        the Next.js 16 dashboard (App Router)
  app/                             the five screens: /login, /leads,
                                   /leads/[cid], /runs, /runs/new, plus the
                                   /api/export CSV proxy
  components/                      shadcn/ui primitives plus the five domain
                                   components (ScorePair, QuadrantBadge,
                                   CoverageIndicator, EvidenceQuote, SignalBadge)
  lib/                             api.ts — the ONLY path to the backend, and
                                   the only place the API key exists; auth.ts,
                                   types.ts, format.ts
  middleware.ts                    the password gate: everything but /login
  e2e/                             Playwright specs and page objects, run
                                   against the real seeded backend
  Dockerfile                       standalone build, served by `node server.js`
docs/
  decisions/DECISIONS.md          why every choice was made
  superpowers/specs/              the design
  superpowers/plans/              the build plan
docker-compose.yml                Postgres 16, the API, and the dashboard
```

Roughly 2,600 lines of application code and 2,600 lines of tests.

**One rule is enforced automatically:** `app/domain/` may not import SQLAlchemy,
httpx, FastAPI, Firecrawl, SerpApi, YAML, or anything from `app.models` or
`app.clients`. A tool called `import-linter` fails the build if anyone breaks it.
That keeps the thinking part of the system free of plumbing, which is why the
rules engine can be tested without a database or an API key.

**All test data is real.** `tests/fixtures/` contains an actual 20-record Serper
response for "hvac businesses in Houston" and four real HVAC company web pages.
No invented data — see section 6 for why that turned out to matter.

---

## 5. Build status

All 17 tasks of Plan 1, all 11 of Plan 2, and all 9 of Plan 3 are implemented
and reviewed. Rather than repeat the task list, here is
what each command does — that is what you actually need:

| Command | What it does |
|---|---|
| `discover` | Serper Maps search → new `businesses` rows |
| `scrape` | Firecrawl the websites of a bounded, stratified sample |
| `extract` | Derive signals from what is already stored (free, re-runnable) |
| `score` | Apply the ruleset, write two scores per business (free, re-runnable) |
| `enrich` | SerpApi reviews for the top candidates, then re-extract and re-score |
| `run-all` | All of the above in order, under a `--max-cost` budget |
| `export` | Ranked CSV, filtered by quadrant and minimum fit |
| `outcome` | Record what actually happened with a lead — the feedback loop |
| `spend` | What this run, or everything, has cost so far |
| `POST /runs` | Queue a run (`status="queued"`); returns 201 immediately, does not execute inline |
| `GET /runs/{id}` | Poll a queued or in-progress run's status |
| `GET /leads`, `GET /leads/{cid}` | Filtered, paginated leads and lead detail for the dashboard |
| `PUT /leads/{cid}/outcome`, `PUT /leads/{cid}/manual-facts` | The same feedback loop and manual capture, from the API |

Plan 3 adds the dashboard — a Next.js App Router frontend, nine tasks:

| Screen | What it does |
|---|---|
| `/login` | One shared password, HMAC-signed cookie, everything else behind it |
| `/leads` | The ranked table. Defaults to `go_now` (ADR-004), filters by quadrant and outcome, exports CSV through a server-side proxy so the API key never reaches the browser |
| `/leads/{cid}` | Fit and pain broken down rule by rule, the review quotes behind them, the signals (with `unknown` never collapsed into `no`), and the two manual forms |
| `/runs` | Every run, with its error, and polling while one is in flight |
| `/runs/new` | Pick a vertical and a state, see the queries, the count and the honest search-only cost estimate, then confirm or cancel |

Two screens named in the spec were deliberately cut, both with an ADR:
ruleset compare (ADR-026's sibling — only one ruleset exists) and the contacts
form (ADR-027 — there is no contacts endpoint). 14 of the spec's 15 frontend
user stories are covered; each is asserted by a Playwright spec in
`frontend/e2e/` that runs against the real seeded API, not against mocks.

Plan 2 adds an in-process APScheduler, started with the app's lifespan: it polls
every 30 seconds and executes queued runs, so `POST /runs` only enqueues — the
scheduler is what actually calls `execute_run`.

320 backend tests and 60 frontend tests pass, `mypy app cli.py` is clean,
`tsc --noEmit` is clean, both import contracts hold, and the 18-case Playwright
suite (14 user-story specs plus axe on four screens) passes against the running
stack.
The API and CLI now share one Docker image (`backend/Dockerfile`, ADR-017); `docker
compose up db api` runs the service, and the CLI runs inside the same image via
`docker compose run --rm api python -m cli ...`.
**Nothing has been run against the live APIs yet.** The whole system is exercised
through fake clients replaying the saved fixtures, so the first real run is still
the first real run — budget it small.

---

## 6. What we got wrong, and how the code protects against it

Three guesses were made during design and all three were wrong. Each was caught
by checking against real data before the code shipped.

1. **Guessed HTML fingerprints.** Seven patterns were written to detect chat
   widgets on websites. Checked against 20 real HVAC sites, **all seven matched
   nothing**, and three matched the wrong thing entirely — `crisp` matched a
   WordPress CSS variable on 11 of 20 sites. Had this shipped, every business
   would have looked like it had no chat widget and been awarded 20 pain points
   for free, and no test would have failed. Replaced with three fingerprints
   confirmed against live pages, plus a written list of what was excluded and why.
2. **Guessed that a 200-review threshold would filter out most businesses.** In
   the real Houston data, 13 of 20 cleared it. The threshold was removed.
3. **Guessed the customer profile.** The original theory was that small growing
   companies answer their phones and big ones do not. The real data broke it:
   Royal Air has 8,758 reviews and still closes at 5pm and both weekend days.
   Company size is now recorded as a label, never used to filter or to score.
   What actually measures the gap is opening hours.

The lesson is now a standing rule in the project: **never write a detection
pattern you have not checked against a real page.**

### What the final review found

Every task passed its own review. The final pass then read the whole branch at once
and found four critical defects — all of them at the **seams between** components
that different agents had built. This is the part worth internalising: per-task
review structurally cannot see these.

1. **The error handling was entirely dead code.** `app/core/errors.py` defined a
   careful four-way taxonomy — retry this, give up on this business, kill the run,
   fail just this row — and *nothing ever raised it*. The retry logic, the circuit
   breaker and the advance-anyway path had never once executed. Every task's tests
   passed because each tested its own half.
2. **A dead website looked exactly like a scraped one.** With no HTML to read, the
   extractor returned `has_chat_widget=False` as a *fact*. So a business we knew
   nothing about was awarded 20 pain points for having no chat widget, and came out
   with the same `coverage` as a business we had fully read. This is precisely the
   "unknown is not no" rule from section 3, broken one layer below where the rule
   lives. There is now a test that a dead site ends with measurably lower coverage.
3. **Review data could not be rebuilt.** SerpApi responses were never saved to
   `raw_payloads`, so the "drop the derived tables and re-run the free half" recovery
   — the whole point of section 3's two halves — silently destroyed complaint counts
   and could never re-fetch them.
4. **The budget guard could be overspent 12×.** The ceiling was checked between
   stages, but scraping is the stage that spends the money and it ran to completion
   once entered. `--max-cost 0.05` still spent about $0.60.

Then the fixes for those introduced two regressions of their own, which a re-review
caught: making the cost log durable had quietly disabled the retry it was meant to
work with, and a failed enrichment was being recorded as "enriched, found nothing".

The honest summary: **sixteen clean per-task reviews did not add up to a working
system.** What found the real problems was one reviewer reading everything at once
and running the code, and then a second one checking the fixes the same way.

### What the API's final review found

The same thing happened again, one layer up. Eleven clean per-task reviews, then a
final pass found two more critical defects — both invisible from inside any single
task:

1. **`GET /leads/{cid}` returned 400 for every scored lead.** The API's schema for a
   scoring reason declared fields (`id`, `applicable`) that the scoring engine does
   not write; it writes `rule`, `track`, `matched`, `points`, `label`, `evidence`.
   The CSV exporter read the same JSON correctly, so the codebase had two consumers
   of one structure with one of them wrong. Both tests that should have caught it
   missed: one used an empty fixture, the other invented the shape it was testing.
2. **Two processes could execute the same run at once.** The API's startup routine
   requeued any run left in progress, on the reasoning that a freshly started process
   owns nothing — but the CLI is a documented second entrypoint into the same image
   and database, so a restart could requeue a run the CLI was actively executing and
   bill it twice.

The second one is worth dwelling on: it was introduced by a *fix* for a different
problem, removed after review found the race, and then found to still be wrong from
the other direction. Three passes to get one lifecycle rule right.

**The rule that came out of it:** without a way to know which process owns a run,
no automatic reconciliation is safe. So there is none — recovery is an explicit
`python -m cli reset-stuck-runs`, run by a person who knows what is running.

### The pattern behind most of these

Six defects in Plan 2 came from the same source: the plan described an interface
from memory rather than from the file. A field that did not exist, a keyword spelled
wrong, a credit cost off by 3×, two arguments silently dropped, ruleset keys that
were never there, and finally the reason shape above. Every one was caught by an
implementer or reviewer opening the actual source.

**Read the interface. Do not recall it.**

### What the dashboard's final review found

Same shape a third time. Nine clean per-task reviews, then a broad pass found a
critical defect none of them could see — and this one destroyed data.

**The manual-facts form flattened "unknown" into "no".** Two of its fields are
three-state in the database (`true`, `false`, or *not yet researched*), but the
form rendered them as plain checkboxes, which have only two states. So every
save wrote an explicit `false` for anything unticked. Typing only a note flipped
both columns from "unknown" to "no" in `manual_facts` — the one table a pipeline
rerun must never overwrite — and "unknown" became unreachable from the UI
forever.

That is the same unknown-is-not-no rule from section 3, broken a third time, in
a third place: first in the extractor, then at the API's schema boundary, now in
a form control. The fix was to replace each checkbox with a three-option
control, because a checkbox cannot represent three states and no amount of form
plumbing changes that.

**Why the browser tests caught it and the unit tests did not.** The spec insisted
Playwright run against a real seeded backend rather than mocked responses. That
decision paid for itself twice over here: mocked responses would have happily
echoed whatever the form sent.

### The tests that could not catch their own bugs

Three separate times on this branch, a test was written around the bug it was
supposed to catch:

- "Shows a dash instead of a phone number" only checked that one specific number
  was absent — rendering a *different* fake number passed.
- The mock for a page redirect did not throw the way the real one does, so the
  regression it existed to guard could not fail it.
- The fix for the CSV export filter mismatch introduced the same bug in the
  opposite direction, and its own test was scoped around the gap.

All three were caught the same way: by **mutating the code and checking the test
fails**. None were caught by reading the test. That is now the standard for any
test guarding a rule in this document — break the code first, watch it go red.

---

## 7. Open items

**No known bugs.** One critical and five important findings from the dashboard's
final review are fixed and independently re-verified against the running stack.

**Decisions waiting on you**, not defects:

- **`estimated_cost` reads about 4× low** — the preview prices the search step but
  not the scraping. You decided to leave it, so the dashboard labels it
  "Estimated search cost" and says scraping is extra. Read it that way; the real
  figure is `actual_cost`, and `--max-cost` guards against real spend.
- **An API restart mid-run does not self-heal.** `python -m cli reset-stuck-runs`
  is the recovery. The proper fix is a heartbeat column, which needs a migration.
- **Neither lead-detail form confirms a save.** The value persists, but nothing
  says so — a `<Toaster />` is mounted and unused. The most-used screen in the
  app, so worth doing before real daily use.

**Deliberately deferred**, none with a failure scenario today:

- `datetime.utcnow()` is deprecated in 3.12 and used across the whole schema. Do
  it as one sweep.
- `Stage.select` ignores `run_id` and the per-segment scrape cap is cumulative, so
  a **second vertical would count the first one's leftovers against its caps.**
  The fix is a `Business.vertical` filter. Latent until vertical #2.
- A retried scrape re-fetches pages that already succeeded, billing them twice.
- `safeNextPath` does not strip CR/LF, and a future-dated session token is
  accepted. Both currently inert; both on the auth path.
- `?page=abc` yields `page=NaN` on both list screens; `?page=99` renders
  "Page 99 of 1"; the runs pagination drops other query parameters.
- Outcome notes are write-only — saved, never displayed back.
- The Dockerfiles run as root; the compose services have no restart policy.

**Not built yet:** contact discovery and email outreach. The `contacts` table
exists with no API and no UI (ADR-007, ADR-027) — that is the seam, and it is
where the next plan starts. Also unbuilt: the ruleset-compare screen, which waits
until a second ruleset exists, and any vertical beyond HVAC.

**Machine note:** Homebrew's `postgresql@14` is stopped because it collides with
the Docker database on port 5432. Starting it breaks this project until you stop
it again. Moving this project to 5433 would end that permanently.

---

## 8. Running it

```bash
# All three services: Postgres on 5432, the API on 8000, the dashboard on 3000.
export API_KEY=... DASHBOARD_PASSWORD=... SESSION_SECRET=...   # 32+ chars
docker compose up -d --build
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m cli seed-demo    # idempotent demo data
open http://localhost:3000                             # sign in with DASHBOARD_PASSWORD
```

`web` reaches the API at `http://api:8000` — the compose service name, never
`localhost`. Only the browser talks to Next.js and only Next.js talks to the
API, so `API_KEY` lives in the `web` container's environment and is never
prefixed `NEXT_PUBLIC_`.

Backend checks, without Docker:

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env             # fill in SERPER_KEY, FIRECRAWL_KEY, SERPAPI_KEY
alembic upgrade head
pytest                           # 320 tests, no API keys needed
lint-imports                     # enforces the domain-layer boundary
```

Frontend checks:

```bash
cd frontend
npm ci
npx vitest run                   # 60 unit tests
npx tsc --noEmit
npx playwright test              # needs the compose stack up and seeded
```

Tests never touch the real APIs. Tests that would are marked `live` and are
excluded by default. The Playwright suite is the exception to "no live
services": it drives a real browser against the real `web` and `api`
containers and the seeded database, deliberately — mocked responses would hide
exactly the frontend/backend contract mismatches the suite exists to catch.

---

## 9. Where to look next

| Question | File |
|---|---|
| Why is it built this way? | `docs/decisions/DECISIONS.md` |
| What is the full design? | `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md` |
| What is left to build? | Deployment (ADR-026), the contacts endpoint and its form (ADR-027), ruleset compare once a second ruleset exists |
| What happened during the build? | the `git log` — one commit per feature, `fix:` where a review found something |
| How is a business scored? | `backend/config/rulesets/hvac_v1.yaml` |
