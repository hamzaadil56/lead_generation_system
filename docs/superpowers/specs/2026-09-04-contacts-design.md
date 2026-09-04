# Contacts Discovery — Design

**Date:** 2026-09-04
**Status:** approved in brainstorming, pending implementation plan
**Supersedes:** ADR-027 (the contacts form is out of scope for the dashboard)
**Parent spec:** `docs/superpowers/specs/2026-08-27-lead-generation-system-design.md`

---

## 1. Goal

Turn a scored lead into a person you can email.

The pipeline already tells you *which businesses are worth contacting*. It has
never told you *who to contact there*. This closes that gap: contacts can be
typed by hand or harvested for free from HTML already in the database, they are
confirmed by a human before they can leave the system, and they leave as a CSV
one row per contact that an email tool can import directly.

This implements spec user story 11 ("Add a contact email"), the last of the
fifteen frontend stories left unbuilt, and puts the `contacts` and
`suppressions` tables — both created in the initial migration, both empty and
unreachable since — into service.

## 2. Scope decisions

Four questions were settled in brainstorming. Each rejected alternative is
recorded because the reasons will not survive in anyone's memory otherwise.

**Discovery is manual entry plus a free harvest from cached HTML.**
`raw_payloads.raw_text` already holds the full HTML of every page Firecrawl
scraped, permanently and append-only (ADR-003). Extracting addresses from it
costs nothing and calls no provider. Rejected: manual-only, which throws away
data already paid for; and a paid finder API (Hunter, Apollo), which would add
a fourth external provider, a fourth key, a fourth budget line and a fourth
failure mode in exchange for a free tier of roughly 25 lookups a month.

**Contacts leave as their own CSV, one row per contact.** Rejected: bolting a
`primary_email` column onto the existing leads export, which can only ever emit
one of a business's contacts and emits a blank-email row for every business
that has none. The leads export is not modified at all.

**A human confirms a harvested contact before it can be exported.** Rejected:
exporting everything and relying on eyeballing the CSV. Harvesting a footer
returns `noreply@`, `privacy@` and stray vendor addresses alongside the real
ones; mailing those produces hard bounces, and bounce rate is the single
largest input to cold-email sender reputation. The cost of the gate is one
click per harvested contact. Manually typed contacts are confirmed on save —
typing an address is looking at it.

**Confidence is scored in tiers with fuzzy domain matching, and the reason is
stored.** Rejected: exact domain equality, which scores `john@tryleisuration.com`
against site `leisuration.com` as 0.3 — bottom of the list, indistinguishable
from third-party junk, when it is almost certainly the owner. Section 5 covers
this in full.

## 3. What this is not

Explicitly out of scope, so no task invents them:

- **No email verification.** Nothing checks whether an address is deliverable.
  `verification_status` stays NULL for every row in v1.
- **No sending, templates, sequences or tracking.** This produces a CSV.
- **No unsubscribe webhook.** `suppressions` is filtered against but populated
  only by hand, via a new CLI command.
- **No LinkedIn scraping.** `linkedin_url` is a field you type into.
- **No automated harvest during a pipeline run.** Section 6 explains why.
- **No `GET /leads/{cid}/contacts`.** Contacts ride along on the lead detail
  response the page already fetches. A second read path for the same data is a
  second way to be wrong about it.

## 4. Data model

No new tables. `contacts` was created in `cf221e601a3b_initial_schema` with
exactly the columns spec section 8 named, and has never held a row — no
endpoint or service has ever written to it, and `seed_demo` does not create
any. A migration that adds constraints therefore cannot fail on existing data.

### 4.1 Migration

One Alembic revision on top of `2583d9590873`:

| Change | Reason |
|---|---|
| `ADD COLUMN confirmed_at TIMESTAMP NULL` | The export gate. NULL means no human has vouched for this contact. |
| `ADD COLUMN discovery_note VARCHAR NULL` | Why the harvester assigned the confidence it did, in words a person can act on. NULL for manually typed contacts. |
| `UniqueConstraint("business_id", "email", name="uq_contacts_business_email")` | Harvest is re-runnable; without a natural key, running it twice doubles every row. |
| `Index("uq_contacts_one_primary", "business_id", unique=True, postgresql_where=text("is_primary"))` | At most one primary contact per business, enforced by the database rather than by application discipline. |
| `ALTER COLUMN created_at SET DEFAULT now()` and a model-side `default=datetime.utcnow` | The column exists and is nullable but nothing ever sets it. |

Emails are stored lowercased and stripped (section 5.1), so the unique
constraint is effectively case-insensitive without needing a functional index.
Postgres treats NULLs as distinct, so a business may hold several contacts with
no email at all — a name and a phone number is a legitimate row.

### 4.2 Both halves of every constraint go in the model

`tests/conftest.py` builds the test schema with `Base.metadata.create_all`, not
by running Alembic. **A constraint declared only in the migration is invisible
to every test in the suite** — the duplicate-email test would pass against a
schema that has no unique constraint, and the defect would ship.

Every constraint in the table above is therefore declared in
`app/models/manual.py` under `Contact.__table_args__`, and the migration is
written to match it. This is not belt-and-braces; the model is the side the
tests see.

### 4.3 `confirmed_at` is not `verification_status`

The `contacts` table already has `verification_status` with the values spec
section 8 lists: `unverified | valid | risky | invalid | catch_all`. Reusing it
for the confirm gate would need no migration. It is still wrong, because the
two columns record different facts:

- `verification_status` answers **is this address deliverable?** Nothing in v1
  knows. It stays NULL.
- `confirmed_at` answers **did a human decide this is a person worth emailing,
  and when?**

A human confirming `info@acme.com` tells you nothing about whether it bounces.
Collapsing the two would mean the export could not distinguish "verified as
deliverable by a service we have not built" from "a person clicked a button",
and the v2 verifier would arrive to find its column already occupied by a
different meaning. This is the same distinction `on_missing: skip` draws
between *unknown* and *false*.

For the same reason `verification_status` is deliberately **omitted from
`ContactOut`** and never shown in the UI. Rendering a permanent "unverified"
badge beside a "Confirmed" badge invites exactly the conflation this section
exists to prevent.

### 4.4 A manually typed contact has no confidence

`confidence` is left NULL on manual creation, not set to 1.0. It is the
harvester's model score; a human typing an address is not producing a value on
that scale. NULL means "this number does not apply here", and the UI renders
nothing rather than a fabricated certainty.

## 5. Domain layer — pure, no I/O

Two new modules under `app/domain/`, which import-linter forbids from importing
sqlalchemy, httpx, fastapi, firecrawl, serpapi, yaml, `app.models` or
`app.clients` (ADR-024). Both are pure functions over strings, testable in
milliseconds without a database.

### 5.1 `app/domain/email.py`

Mirrors the shape of the existing `app/domain/phone.py`.

```python
def normalize_email(raw: str | None) -> str | None:
    """Return a lowercased, stripped address, or None if it is not valid."""

def email_domain(email: str) -> str:
    """The part after the @, lowercased."""
```

One definition of a valid email, used by **both** the harvester and the API
schema. Two definitions is how a harvested address gets saved by the pipeline
and then rejected when a human tries to edit it.

`pydantic.EmailStr` is deliberately not used: `email-validator` is not among
the project's dependencies, the harvester needs a regex of its own regardless,
and a shared domain function keeps the two sides from drifting.

Rules: one `@`, a non-empty local part, a domain with at least one dot and no
consecutive dots, total length ≤ 254, no whitespace or angle brackets.

### 5.2 `app/domain/extractors/emails.py`

```python
@dataclass(frozen=True)
class HarvestedEmail:
    email: str
    confidence: float
    note: str          # -> Contact.discovery_note

def extract_emails(raw_html: str, *, site_domain: str | None,
                   business_name: str | None) -> list[HarvestedEmail]:
    """Candidate addresses from one page of HTML, best first."""
```

Finds `mailto:` hrefs first, then bare addresses in the remaining text.
Deduplicates within the page, keeping the highest confidence.

**Rejected outright** (never returned at any confidence):

- Junk local parts: `noreply`, `no-reply`, `donotreply`, `postmaster`,
  `abuse`, `webmaster`, `hostmaster`, `mailer-daemon`, `unsubscribe`,
  `privacy`, `legal`.
- Vendor domains that leak from embedded scripts and CMS boilerplate:
  `wixpress.com`, `wix.com`, `sentry.io`, `squarespace.com`, `godaddy.com`,
  `wordpress.com`, `example.com`, `example.org`, `domain.com`, `email.com`,
  `sentry-next.wixpress.com`.
- Anything ending in an image or asset extension — `.png`, `.jpg`, `.jpeg`,
  `.gif`, `.svg`, `.webp`, `.css`, `.js`. Filenames containing `@` (retina
  assets such as `logo@2x.png`) are the most common false positive in real
  HTML.
- Anything `normalize_email` rejects.

### 5.3 Confidence tiers

Both domains are reduced to a **stem**: strip `www.`, lowercase, take the
registrable domain (last two labels, or three when the last two match a
short hard-coded compound-suffix list -- `co.uk`, `com.au`, `co.nz`, `co.za`,
`com.br`, `co.in`), then drop the TLD.
`https://www.tryleisuration.com/about` → `tryleisuration`.

Evaluated top to bottom, first match wins:

| Confidence | Rule | `discovery_note` |
|---|---|---|
| 0.9 | Stem equals the site stem, same TLD; or the email domain is a subdomain of the site domain | `matches the website domain` |
| 0.85 | Stem equals the site stem, different TLD | `same name as the website, different domain ending` |
| 0.8 | Stems are equal after stripping affixes | `variant of the website domain` |
| 0.8 | One stem contains the other at a prefix or suffix boundary, both guards passing | `variant of the website domain` |
| 0.75 | Stem matches the normalised business name, both guards passing | `matches the business name` |
| 0.6 | Free mail provider | `free mail provider — common for owner-run businesses` |
| 0.3 | Anything else | `unrelated domain — may be a third party` |

Affixes stripped for the 0.8 tier: leading `try`, `get`, `go`, `my`, `the`,
`use`, `visit`; trailing `hq`, `co`, `inc`, `llc`, `online`, `site`, `web`.
This is the tier that catches `john@tryleisuration.com` against site
`leisuration.com`.

Free providers: `gmail.com`, `googlemail.com`, `yahoo.com`, `ymail.com`,
`hotmail.com`, `outlook.com`, `live.com`, `msn.com`, `aol.com`, `icloud.com`,
`me.com`, `comcast.net`, `sbcglobal.net`, `verizon.net`, `att.net`, `bellsouth.net`,
`cox.net`, `charter.net`, `earthlink.net`, `protonmail.com`, `proton.me`.

**The free-provider check runs before every similarity rule.** Otherwise a
business named "Mail Masters" reaches the containment tier against `gmail.com`.

Business-name normalisation for the 0.75 tier: lowercase, drop everything that
is not a letter or digit, then remove the generic tokens below. "Leisuration
Air Conditioning, LLC" → `leisuration`.

### 5.4 The two guards on fuzzy matching

Loosening the match is the easy half. These two are what keep it from
degenerating, and both must be implemented or the 0.8 and 0.75 tiers become
noise:

**Length floor.** The shorter stem must be at least 5 characters. Without it,
site `air.com` matches `john@repair.com` — `air` is a suffix of `repair`. The
floor also excludes `hvac`, `pro`, `gas`, `cool`, `ac`.

**Generic-token denylist**, applied regardless of length: `hvac`, `air`,
`heating`, `cooling`, `plumbing`, `service`, `services`, `repair`, `repairs`,
`home`, `homes`, `comfort`, `mechanical`, `electric`, `heat`, `cool`, `climate`,
`energy`, `solutions`, `company`, `contractors`.

The denylist matters more than the floor in this vertical. `plumbing` is eight
characters and clears the floor easily, but `acmeplumbing.com` and
`joesplumbing.com` sharing it means nothing — and HVAC domains are saturated
with precisely these words. Without this guard a large fraction of harvested
contacts would score 0.8 against businesses they have no relationship to.

### 5.5 Confidence is a sort key, not a gate

Nothing is exported on the strength of its confidence. `confirmed_at` is the
only gate, and only a human sets it. Confidence orders the list and, through
`discovery_note`, explains itself.

This asymmetry is why the tiers are generous. Scoring a bad row 0.8 costs a
glance. Scoring a good row 0.3 — which exact-equality matching does routinely —
buries the owner's real address at the bottom of a list that looks like junk,
where it will be skipped.

### 5.6 `role` is never guessed

The harvester sets `role = None`. Inferring "Owner" from `info@` is
fabrication. Designation is typed by a human who knows.

## 6. Harvest is a service, not a pipeline stage

The pipeline is pipes-and-filters over `Business.status`: each stage selects one
status, does one job, advances it. Harvesting does not belong there.

- A new status would force every existing business through a new state and
  couple contact discovery to a run's lifecycle and its circuit breaker.
- Harvesting is retrospective. It must work on businesses scraped last week,
  which are already past any status a new stage could select on.
- `contacts` is a PERMANENT table (ADR-008). The pipeline's free half rebuilds
  what it owns; a stage that rebuilt `contacts` would delete contacts a human
  typed.

`app/services/contact_harvest.py`:

```python
def harvest_for_business(session, business_id: int) -> HarvestResult
def harvest_for_filters(session, filters: LeadFilters) -> BulkHarvestResult
```

**Insert-only.** It never updates and never deletes. Re-running is therefore
idempotent — the unique constraint on `(business_id, email)` is the guard — and
an address you edited by hand survives every subsequent harvest.

It reads **every** `RawPayload` row for the business where `source ==
"firecrawl"`, not only the most recent. `scrape_site` stores one payload per
page in the allowlist (`/about`, `/contact`, `/services`, `/team`), and
`/contact` and `/team` are exactly the pages that carry addresses. Scanning
only the newest would miss most of them.

Candidates are deduplicated **across all of a business's pages** before any
insert, keeping the highest confidence for each address. Deduplicating only
within a page (section 5.2) is not enough: the same address appears in the
footer of all four allowlisted pages on most sites, and two inserts of it in
one transaction would raise `IntegrityError` against the unique constraint and
abort the whole harvest.

Per candidate it writes: `email`, `confidence`, `discovery_note`,
`source="website"`, `created_at=utcnow()`, `confirmed_at=NULL`, `role=NULL`,
`is_primary=False`.

A business with no scraped HTML yields `created=0`. That is a result, not an
error — it is the `BusinessPermanentError` distinction the pipeline already
draws between absent data and failure.

**Harvest does not run automatically as part of `execute_run`.** It is free and
pure, so wiring it in later is a small change, but doing it now puts another
operation inside the run loop that the circuit breaker and the four-way failure
taxonomy have to account for, for no benefit the two buttons below do not
already provide.

## 7. API

```
POST   /leads/{cid}/contacts              create        -> 201 ContactOut
PUT    /contacts/{id}                     edit          -> 200 ContactOut
DELETE /contacts/{id}                     delete        -> 204
POST   /contacts/{id}/confirm             confirm       -> 200 ContactOut
POST   /leads/{cid}/contacts/harvest      harvest one   -> 200 HarvestOut
POST   /contacts/harvest?<lead filters>   harvest many  -> 200 BulkHarvestOut
GET    /contacts/export.csv?<lead filters>              -> text/csv
```

A new `app/api/routers/contacts.py`, registered in `create_app` behind
`require_api_key` like every other router. `export.csv` is declared before the
`/{id}` routes.

Reads live in `app/repositories/contacts.py`, writes in
`app/services/contacts.py` — ADR-024 keeps the repositories layer read-only.

### 7.1 `LeadDetailOut` gains `contacts`

`get_lead_detail` returns `contacts: list[ContactOut]`, ordered
`is_primary DESC`, then confirmed before unconfirmed, then
`confidence DESC NULLS LAST`, then `id`.

Confirmed status outranks confidence deliberately. A manually typed contact has
`confidence = NULL` (section 4.4), so ordering on confidence alone would sort
the address you typed yourself *below* a harvested 0.3 that is probably a
stranger.

The lead detail page needs no second request, and there is one read path for
the data.

### 7.2 Schemas — `app/schemas/contacts.py`

```python
class ContactIn(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    role: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=254)
    phone: str | None = Field(default=None, max_length=50)
    linkedin_url: str | None = Field(default=None, max_length=500)
    is_primary: bool = False
```

- `email` is validated and normalised through `app.domain.email.normalize_email`;
  an unparseable address is a 422.
- `phone` is **not** run through `validate_phone`. That gate exists because
  Serper returns street addresses in `phoneNumber` (ADR-013). A hand-typed
  direct line or extension is trusted as entered.
- `linkedin_url`, if present, must start with `http://` or `https://`.
- **At least one of `name` or `email` must be non-empty.** A row with neither
  is not a contact. Recording "the owner is John Smith, address unknown" is
  legitimate contact discovery and stays allowed.

`ContactOut` exposes `id, name, role, email, phone, linkedin_url, source,
confidence, discovery_note, is_primary, confirmed_at, created_at`. Not
`verification_status` (section 4.3), not `business_id` (the caller already
knows which lead it asked about).

### 7.3 Endpoint behaviour

**Create** sets `source="manual"`, `created_at=utcnow()`,
`confirmed_at=utcnow()`, `confidence=NULL`, `discovery_note=NULL`.

**Edit** applies `model_dump(exclude_unset=True)`, so an omitted field is left
alone rather than nulled. Editing does **not** confirm: one action, one
meaning. A harvested contact whose address you corrected still needs its
Confirm click.

**Confirm** sets `confirmed_at = utcnow()` only if it is currently NULL, so
repeat calls are idempotent and do not move the timestamp. There is no
un-confirm; a mis-click is corrected with Delete.

**`is_primary`** — when a create or edit sets it true, every sibling contact of
the same business is cleared in the same transaction before the write. The
partial unique index is the backstop, not the mechanism. Deleting the primary
contact promotes nobody; the business simply has no primary until you set one.

### 7.4 Errors

| Case | Response |
|---|---|
| Duplicate email for the same business | **409**, `"that email is already a contact for this lead"` — the `IntegrityError` is caught, never surfaced as a 500 |
| Unknown `cid` | 404 |
| Unknown contact `id` | 404 |
| Malformed email, both of `name`/`email` empty, bad LinkedIn URL | 422 |
| Business with no scraped HTML | 200, `{"created": 0, ...}` |

The 409 matters. The unique constraint is load-bearing for harvest
idempotency, which means an ordinary user action — typing an address that was
already harvested — hits it on a normal path, and an unhandled `IntegrityError`
there is a 500 that also poisons the session.

## 8. Export

`app/services/contact_export.py`, alongside the existing `export.py` rather
than inside it: that module is about leads, and this one is about contacts.

```python
def export_contacts(session, filters: LeadFilters, path: Path) -> int
```

Columns, one row per contact:

```
email, contact_name, role, source, confidence,
business_name, city, state, website, segment,
fit_score, pain_score, quadrant
```

The business columns are there for mail-merge personalisation. Ordering is
`fit_score * pain_score DESC, business.id, contact.id` — the same ranking
`GET /leads` and the leads export use, so the best leads are at the top of the
file.

### 8.1 Three predicates

Built on `filtered_leads(session, filters)` — the identical predicate the leads
list, the leads export and the bulk harvest use — then:

1. `contacts.confirmed_at IS NOT NULL`
2. `contacts.email IS NOT NULL` — a contact with no address cannot appear in an
   email export, confirmed or not
3. `LEFT JOIN suppressions ON lower(suppressions.email) = contacts.email`
   `WHERE suppressions.email IS NULL`

Emails are stored normalised on both sides, so the join is a plain equality.

### 8.2 Populating suppressions

A new CLI command, without which the suppressions table can never hold a row
and predicate 3 is dead code:

```
python -m cli suppress <email> --reason unsubscribed|bounced|complained|manual
```

It normalises the address through the same `normalize_email`, and upserts on
the `email` primary key so suppressing twice is not an error.

### 8.3 The filter set is shared, not re-listed

Both `POST /contacts/harvest` and `GET /contacts/export.csv` take **every**
filter `GET /leads` takes, and validate them identically. The frontend derives
all three from `LEAD_FILTER_KEYS` in `frontend/lib/filters.ts`.

FastAPI silently ignores query parameters an endpoint does not declare, so a
filter missing from one of these does not fail — it quietly operates on the
whole table under a URL that claims otherwise. That is how the leads export
shipped honouring one filter of five (commit `f7b1ef2`), and harvest has the
same failure mode with a worse blast radius: a bulk harvest that ignores its
filters walks every business in the database.

## 9. Frontend

### 9.1 Types

`frontend/lib/types.ts` gains `ContactOut` and `contacts: ContactOut[]` on
`LeadDetailOut`.

### 9.2 `frontend/components/contacts-card.tsx`

On the lead detail page, below Manual facts:

- The contact list, primary first. Each row shows name, designation, email,
  and — for harvested rows — a muted confidence chip and the
  `discovery_note` text.
- Unconfirmed rows carry an **Unconfirmed** badge and a **Confirm** button.
  Every row has **Delete**.
- The card footer reads: *"Unconfirmed contacts are not included in the
  export."* Without that line the export silently drops rows and reads as
  broken.
- An **Add contact** form: name, designation, email, phone, LinkedIn URL, and
  a "primary contact" checkbox.
- A **Harvest from website** button, disabled with an explanatory note when the
  lead has no website.

**Designation** is a free-text `<Input>` backed by a `<datalist>` of Owner,
General Manager, Office Manager, Operations Manager, Service Manager,
Dispatcher, Marketing Manager. Free text so no one is ever blocked by a missing
option; suggestions so the values stay consistent enough to filter on in v2.

Every input has a `<Label>`; the existing `@axe-core/playwright` assertion on
the lead detail screen must keep passing.

### 9.3 Server actions

In `frontend/app/leads/[cid]/page.tsx`, following the existing
`saveOutcome` / `saveManualFacts` pattern: `addContact`, `deleteContact`,
`confirmContact`, `harvestContacts`, each calling `apiSend` and then
`revalidatePath`. A 409 is caught and surfaced as an inline message on the
form, not an error page.

### 9.4 Leads list

`frontend/app/leads/page.tsx` gains **Harvest emails** (a server action posting
to `/contacts/harvest`, reporting the created count through the existing
`sonner` toast) and **Export contacts CSV**. Both build their parameters from
`LEAD_FILTER_KEYS`, exactly as the existing export link does.

### 9.5 CSV proxy

`frontend/app/api/contacts-export/route.ts`, mirroring
`frontend/app/api/export/route.ts` — forwarding every key in
`LEAD_FILTER_KEYS`, filename `contacts.csv`. The proxy exists so the API key
stays server-side; a direct browser link to FastAPI would require shipping it
to the client.

## 10. Testing

### 10.1 Fixtures are hand-written

The HTML fixtures for the extractor are **written by hand** using invented
domains (`example-hvac.test`, `tryleisuration.test`), never saved from a live
site. The last fixture captured from a real page carried a third party's Google
Maps API key into git history and needed `git filter-repo` to remove it.

### 10.2 Domain — `tests/domain/test_email_extractor.py`

Pure and fast. Must cover: `mailto:` extraction; bare addresses in text; every
junk prefix; every vendor domain; the `logo@2x.png` asset false positive;
in-page deduplication keeping the highest confidence.

And every confidence tier by name, including the two the guards exist for:

- `john@leisuration.com` vs site `leisuration.com` → 0.9
- `john@mail.leisuration.com` vs site `leisuration.com` → 0.9
- `john@leisuration.net` vs site `leisuration.com` → 0.85
- **`john@tryleisuration.com` vs site `leisuration.com` → 0.8**
- `john@leisurationhvac.com` vs site `leisuration.com` → 0.8
- `john@leisuration.com` vs site `leisurationair.com`, name "Leisuration Air" → 0.75
- **`john@gmail.com` → 0.6, never a similarity tier**
- `hello@somewebdesignco.com` → 0.3
- **`john@pipeline.com` vs site `pipe.com` → 0.3, not 0.8** — isolates the
  length floor: `pipe` is a prefix of `pipeline` and is not a generic token, so
  only the 5-character floor rejects it
- **`john@plumbing.com` vs site `acmeplumbing.com` → 0.3, not 0.8** — isolates
  the denylist: `plumbing` is a suffix of `acmeplumbing` and its 8 characters
  clear the floor, so only the denylist rejects it

The last two are the tests that fail if a guard is dropped, and each is
constructed so that **only one** guard rejects it. A case like
`john@repair.com` vs site `air.com` looks like a length-floor test but trips
both guards at once (`air` is under five characters *and* on the denylist), so
it would still pass with either guard deleted. A guard test that survives its
own guard's removal is not a test of that guard.

### 10.3 Service — `tests/services/test_contact_harvest.py`

- Harvesting twice creates one row.
- Editing a harvested contact, then harvesting again, leaves the edit intact.
- Harvest never deletes a contact.
- Harvest reads payloads from all four allowlisted pages, not only the newest.
- A business with no `firecrawl` payload returns `created=0` without raising.

### 10.4 API — `tests/api/test_contacts.py`

Duplicate email → 409 (not 500); unknown cid and unknown id → 404; confirm sets
`confirmed_at` and is idempotent; edit does not confirm; edit with
`exclude_unset` does not null omitted fields; setting `is_primary` clears the
previous primary; a contact with neither name nor email → 422.

### 10.5 Export — mutation-proven

Seed four contacts against one filtered lead: one confirmed with an email, one
unconfirmed, one confirmed whose address is in `suppressions`, one confirmed
with no email. Assert the CSV holds exactly one row.

**Then break each of the three predicates in section 8.1 individually and
confirm the test fails each time.** A test that passes with a predicate removed
is not testing that predicate.

This is not a general exhortation. Three tests on the dashboard branch were
written around the bug they were meant to catch and were found only by mutation
— and this is the test where that failure costs most, because a broken
predicate here means emailing someone who asked not to be emailed.

### 10.6 End-to-end — `frontend/e2e/`

Playwright against the real API and a real database, which is what caught the
manual-facts read path being entirely absent and then the tri-state form
flattening three states into two. Mocked responses echo whatever the form
sends and would have caught neither.

Add a contact → it appears; harvest → an unconfirmed suggestion appears with
its note; the export at that point does **not** contain it; confirm → the
export does. Plus an axe pass on the lead detail page with the new card
present.

`seed_demo` gains deterministic contacts and one `firecrawl` raw payload with
known addresses in its HTML, so the harvest step has something to find.

## 11. Decision records

Two ADRs are written as part of this work:

- **ADR-028** — Contacts are in scope; harvest is a service, not a pipeline
  stage. Reverses ADR-027 and records the pipes-and-filters reasoning from
  section 6.
- **ADR-029** — `confirmed_at` and `verification_status` record different
  facts. Section 4.3.

`docs/DEVELOPMENT-LOG.md` is updated in the same style as the previous three
plans.

## 12. Risks

**The harvester's yield is unknown.** Nobody has run it against real cached
HTML. It may return two good addresses per hundred businesses or none. The
design is cheap enough that finding out is the right move, and the manual form
works regardless — but the plan should not assume harvest carries the feature.

**Cold email has legal obligations this design does not discharge.** CAN-SPAM
requires a working unsubscribe mechanism and a physical postal address in every
message. The suppression table is the receiving end of that, and it is now
filtered against; the sending end does not exist yet and is out of scope. Do
not send from this data without building it.
