# Development Log — Lead Pipeline Core

**Last updated:** 2026-08-31
**Branch:** `feat/lead-pipeline-core` (38 commits, not yet merged)
**Status:** backend pipeline complete and reviewed — 181 tests pass, `mypy` clean.
Not yet run against live APIs; no UI yet.

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
| Building | The code in `backend/` — all 17 tasks | Complete, reviewed |

Every design choice made along the way is written down in
`docs/decisions/DECISIONS.md` — 23 numbered decisions, each in the form
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
docs/
  decisions/DECISIONS.md          why every choice was made
  superpowers/specs/              the design
  superpowers/plans/              the build plan
docker-compose.yml                Postgres 16
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

All 17 tasks are implemented and reviewed. Rather than repeat the task list, here is
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

181 tests pass, `mypy app` is clean, and the domain-layer import contract holds.
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

---

## 7. Open items

**No known bugs.** The confirmed bug listed here previously is fixed, as are ten
findings from the final review and two regressions those fixes introduced.

**Deliberately deferred**, none with a failure scenario today:

- `datetime.utcnow()` is deprecated in 3.12 and produces naive timestamps. It is used
  across the whole schema (~2,900 warnings in a test run). Internally consistent, so
  nothing breaks — but it should be the first commit after this branch merges, done as
  one sweep rather than file by file.
- `Stage.select` ignores `run_id`, and the per-segment scrape cap is now cumulative,
  so a **second vertical would count HVAC leftovers against its own caps**. The fix is
  a `Business.vertical` filter, not a run filter. Latent until vertical #2 — which
  means it belongs to whoever adds one.
- A retried scrape re-fetches pages that already succeeded, billing them twice. Now at
  least logged honestly.
- A business whose enrichment repeatedly half-fails can be re-enriched on later runs.
  This is the deliberate trade for not stranding it permanently.
- `Outcome` has no database-level unique constraint on `business_id`; the upsert is
  check-then-insert, which is safe only because the CLI is single-process.
- Smaller: 408 handling in one client, `RunPermanentError` leaving no `error_message`,
  overnight opening hours (`8 PM–2 AM`) treated as unparseable.

**Not built yet:** the FastAPI routers, the scheduler, and the Next.js dashboard.
Those are Plan 2, which has not been written.

**Machine note:** Homebrew's `postgresql@14` was stopped during this work because it
occupied port 5432 and blocked the Docker database. Starting it again will break this
project until you stop it once more.

---

## 8. Running it

```bash
docker compose up -d db          # Postgres 16 on 5432
cd backend
pip install -e ".[dev]"
cp .env.example .env             # fill in SERPER_KEY, FIRECRAWL_KEY, SERPAPI_KEY
alembic upgrade head
pytest                           # 181 tests, no API keys needed
lint-imports                     # enforces the domain-layer boundary
```

Tests never touch the real APIs. Tests that would are marked `live` and are
excluded by default.

---

## 9. Where to look next

| Question | File |
|---|---|
| Why is it built this way? | `docs/decisions/DECISIONS.md` |
| What is the full design? | `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md` |
| What is left to build? | Plan 2 — not yet written (API, scheduler, dashboard) |
| What happened during the build? | the `git log` — one commit per feature, `fix:` where a review found something |
| How is a business scored? | `backend/config/rulesets/hvac_v1.yaml` |
