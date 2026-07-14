# CLAUDE.md — Working notes for Claude Code sessions in Frontdoor

> Read this and [README.md](./README.md) before changing anything. This file is
> the running record of what Frontdoor is, the plan it's following, everything
> built so far, and the architectural commitments future sessions must honor.

---

## Mission, in one paragraph

**Frontdoor** is a legal front door **+ CLM**, wedged on NDAs. It closes the loop
nobody else owns: a request comes in → it's classified and triaged → routed
through the right approval ladder → an engine drafts the NDA from the company's
playbook → a human governs each step → it's executed, filed, and its renewal is
tracked — **every transition on a tamper-evident audit chain**. The value story
is speed with governance: most NDAs handled fast, many without a lawyer, none
without an audit trail. Deployed to Render as `Legalised_AI`
(`saketgande/Legalised_AI`); the live frontend is `legalised-web.onrender.com`,
API `legalised-api.onrender.com`.

The differentiator is the **whole loop on one spine**: intake, drafting,
redlining, approval, e-signature, filing, and renewal all hang off a single
`Request` record and a single append-only `AuditEvent` ledger — not a pile of
disconnected tools.

---

## The plan — where we started, what's done, what's left

Frontdoor began as a **walking skeleton** (the thinnest outbound-NDA slice that
proves the spine) and has grown outward one reviewable slice at a time. The demo
must keep working end-to-end at every checkpoint.

### ✅ Done

**Core spine & foundation**
- **Outbound NDA path**, end to end: `NEW → CLASSIFIED → ROUTED → DRAFTED →
  IN_REVIEW/APPROVED → OUT_FOR_SIGNATURE → EXECUTED → FILED`.
- **Deterministic triage** forking AUTO / ASSISTED / ESCALATED, returning the
  *reasons* it fired (explainable automation).
- **Generation by assembly** — the NDA is stitched from the playbook's
  *preferred* clauses (lowest-hallucination path), stored as
  `Document → DocumentVersion → Clause[]` with a content hash.
- **Approval ladder assembled from triage** — deduped by rung (VP Legal, GC),
  rung-gated so an attorney can't clear a GC-level deviation.
- **Append-only, hash-chained `AuditEvent` ledger** — every mutation writes a
  row whose hash folds in the previous row's; `GET /api/audit/verify` re-walks
  and reports the first break. Header badge reads "✓ Audit chain intact".
- **Inbound redline engine** (`/inbound`) — paste or upload (.docx/.pdf) a
  counterparty NDA → segmented, classified against the playbook, checked by a
  **hybrid** engine: deterministic validators for what LLMs get wrong (liability
  cap / term months, governing-law jurisdiction, missing mandatory clauses) +
  **semantic checks routed through Claude** (`services/ai.py`) with a keyword
  fallback so it runs with no API key. Each finding is a **PENDING redline** (the
  AgentDecision gate); nothing enters the counter-proposal until a human approves.
- **Multi-channel intake** — form (`/new`), chatbot (`/chat`), email webhook
  (`POST /api/intake/email-webhook`) — all funnel through one `services/intake`
  core, so triage/drafting/redlining/audit are identical per channel.
- **Auth + RBAC** — JWT email/password login, 8 roles, permission model, plus
  **rung-gated approval** (a GC-rung deviation needs GC rank — else 403).
  Requesters see only their own requests.
- **Playbook admin + learning flywheel** (`/admin/playbook`) — manage clause
  rules in-app; when a lawyer edits a proposed redline, one click adopts that
  language as the rule's new preferred position (`playbook.rule.learned`).
  Every change bumps the playbook version and is chain-sealed.
- **Word add-in** (`/word-addin` + `word-addin/`) — Office.js task pane that runs
  the open doc through the redline engine and inserts **tracked changes**.
- **Real e-signature seam** — `send` routes through `get_esign_client()`:
  DocuSign when `DOCUSIGN_*` env vars are set, else a stub that signs the demo
  end-to-end. Completion arrives via the HMAC-verified `POST /api/esign/webhook`.
- **Production hardening** — fail-loud secret guards, login rate-limiting, 401
  auto-logout, sanitized error handling, deep health checks; **Alembic** owns the
  schema (no more `create_all`/startup ALTERs).

**Built this session**
- **Multi-playbook support** — org-default + named playbooks; per-request and
  per-mailbox selection; resolver picks specific-if-named else org-default,
  always org-scoped. (Fixed a cross-org IDOR found in review.)
- **Real email polling** — `services/email_poller.py` drains a configured IMAP
  inbox on a cadence; each message runs the same intake pipeline as the webhook.
  Credentials sealed with an `AUTH_SECRET`-derived keystream (dev-grade). A live
  Gmail intake account is connected on production.
- **UI/UX redesign** — a "refined-enterprise" shell (AppShell sidebar, light/dark
  tokens in `globals.css`) plus genuinely distinct *layouts* per surface:
  **Document Desk** redline (clause rail + serif doc + margin comments),
  **triage table** inbox, **morning-brief** home with sparkline, **package
  status tracker** for requesters, **guided intake** with live auto-approve
  prediction.
- **SLA & deflection dashboard** (`/sla`) — deflection rate, SLA compliance
  against per-lane turnaround targets, average cycle time, 7-day volume, and
  per-request SLA posture. The SLA clock stops at the **immutable ledger approval
  event** (`request.approved`/`request.auto_approved`), never `updated_at`.
  Adversarially reviewed; 4 bugs fixed.
- **CLM half — contract registry + renewal tracking** (`/contracts`) — executed
  NDAs become tracked contracts (`executed_at`, `expires_at = executed_at +
  term`, backfilled from the ledger), surfaced with renewal posture (active /
  expiring / expired / renewed) and one-click renewal that spawns a fresh request
  through the intake pipeline, linked via `renewed_from_id`. The requester status
  page now shows the real expiry date — the "renewal is tracked" copy is finally
  a fact. Adversarially reviewed; 4 bugs fixed (idempotent renewal via unique
  index + atomic link, non-destructive renew errors, SLA-KPI isolation of demo
  contracts).

### ✅ Also done (the intake-platform slice, commits `843d88a` + `2fa3ee6`)
- **Request-type catalog** — `/new` is a "What do you need from legal?" picker;
  6 seeded org-scoped types. CONTRACT types run the CLM engine; ADVICE types
  run the second resolution engine.
- **ADVICE resolution engine** — triage → assign → AI-drafted answer as a
  governed PENDING proposal (`resolution_draft`, reviewer-eyes-only — gated in
  `_detail`) → lawyer approves/edits → `request.approved` ledger anchor →
  requester sees the answer on a 3-stage tracker. Chat + email classify to it.
- **Routing rules** — admin WHEN→THEN rows (`/admin/routing`) with dry-run,
  which-rule-fired stamping, fire-time assignee re-validation; rule-escalated
  AUTO requests ladder on the fired rules.
- **Playbook position ladders** — per-rule fallbacks (each with an approval
  rung) + walk-away lines; the redline engine emits ACCEPTABLE_FALLBACK /
  walk-away-breach findings. The heuristic ladder abstains whenever a semantic
  check contributed to the deviation — numbers never bless prose breaches.
- **Obligations** — extracted deterministically at execution; unique on
  (request, kind); surfaced in the registry with audited mark-done.
- **Triage power UX** — ⌘K palette, j/k/enter/x/m/s keys, snooze, My queue,
  saved views, bulk ops (queue ops = review:decide OR intake:manage, mirrored
  in UI affordances).
- **Type-to-confirm** on send-to-counterparty and rule delete.

### ✅ Also done (Phase 2 — the platform generalizes beyond NDA)
- **Type-scoped playbooks** — `Playbook.contract_type_key` (+ index); `active`
  now means "the org default *for this type*" so NDA and DPA defaults coexist.
  `resolve_playbook(db, org, playbook_id, contract_type)` type-checks named
  books when the caller states a type (admin passes `None`); the default branch
  resolves per type. Activation deactivates only same-type siblings.
- **DPA is a full CONTRACT engine** — new `dpa` request type + seeded 9-rule
  "Standard DPA (controller → processor)" playbook (sub-processor / breach-
  notification / audit / liability ladders with fallbacks + walk-aways).
  Outbound: drafted by assembly from the DPA book, **type gate** forces
  attorney review (non-NDA contract types can never be AUTO; the ladder cites
  the gate + fired routing rules, never triage's pro-approval lines). Inbound:
  counterparty DPAs classify against a **rule-derived keyword map**
  (`keyword_map_for` — no more NDA-hardcoded taxonomy), missing-mandatory
  flagged, PENDING redlines as ever. Then the same approve → send → sign →
  FILED → registry (`type: dpa`) → obligations loop.
- **Founding-type fallback** — `nda` stays valid on an unseeded catalog
  (tests/legacy); any other type must exist in the catalog or intake raises.
- **Per-type frontend** — `/new` renders one `ContractForm` for every CONTRACT
  type (NDA-only affordances gated on `isNda`, playbooks filtered by type);
  `/inbound` gains a "What did they send?" selector; playbook admin creates
  typed books and labels them `[nda]` / `[dpa]`; requester status + contracts
  registry are type-aware.

### ✅ Also done (the workflow engine — score-driven ladders + the negotiation loop)
- **AI risk score per round** (`services/risk.py`) — deterministic factor core
  (walk-away breaches, deviations priced by playbook rung, missing mandatory
  clauses, off-policy facts, sanctions posture) + an AI adjustment that can
  only RAISE severity (clamped server-side; heuristic mode abstains). A lone
  walk-away or a flagged counterparty is CRITICAL on its own.
- **The band picks the ladder** — per-contract-type band→rungs matrix stored
  on the request type; governance as data, editable at `/admin/workflows`,
  validated so non-NDA types can never be blanked into auto-send and inbound
  paper never auto-clears. `finalize_round_governance()` is the single
  chokepoint: assess → matrix → rebuild ladder → AUTO or IN_REVIEW.
- **The negotiation loop** — `APPROVED → WITH_COUNTERPARTY → (their markup
  returns) → round N+1`: new DocumentVersion, fresh redline vs the playbook,
  changed-vs-our-last-position diff, fresh score, fresh ladder — every round
  governed exactly like round 1, on one ticket, on one audit chain. Email
  replies naming a ref thread-match into the loop **only when the sender
  looks like the counterparty** (domain/name check — refs are guessable).
  `/send` (signature) is the separate convergence path, and its packet is
  always the decisions-applied counter-proposal when a review exists.
- **APPROVED requires BOTH gates** (`approval_blockers()`): the risk-built
  ladder cleared AND every redline decided — neither the ladder path nor the
  decide-changes path can flip state alone.
- **Workflow templates** (`services/workflows.py`) — the pipeline as
  versioned data per contract type: pinned/always/conditional rungs over the
  canonical spine (intake → … → seal), ordering-validated, instantiated
  against matter attributes with fired AND dormant rules audited, snapshot
  pinned on the request (publish never rewrites in-flight matters). H-kind
  gate rungs (the DPA ships a DPO gate) join every round's ladder. The
  executor advances the snapshot from the existing chokepoints and
  accumulates time-at-stage.
- **Surfaces** — `/admin/workflows` designer (templates + live risk matrix),
  cockpit risk badge + factor breakdown + workflow ladder rail + negotiation
  panel (review-vs-signature fork, paste/upload return recording), inbox
  risk chips + round markers, `/sla` workflow insights (clock by rung kind,
  autonomy %, override rate per template).

### ⏳ Not yet built (next slices)
1. **Real DocuSign** — the `send → executed` step is stubbed. The seam
   (`get_esign_client()`, the HMAC webhook) is in place; wiring a real provider
   is the natural productionize step.
2. **More CONTRACT engines** — MSA / vendor paper are ADVICE-tracked today.
   The Phase 2 machinery makes each new engine a *seed problem*: add the type
   to the catalog + seed a typed playbook; intake, generation, redlining,
   approval, and the registry generalize already.
3. **Design sweep** of the older surfaces (`/inbound`, `/chat`, `/email-sim`,
   `/admin`, `/admin/playbook`, `/login`) to match the redesigned core.
4. **OCR for scanned PDFs** — image-only PDFs error with a clear message today.
5. **M365 Graph email polling** — IMAP polling covers the need; a Graph-native
   poller would call the same intake adapter per message (no pipeline change).

---

## Stack & layout

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 (sync) |
| Database | Postgres 16 (Neon in prod), Alembic migrations |
| Frontend | Next.js 14 (App Router) + TypeScript |
| AI | Anthropic Claude (optional — deterministic assembly is the default) |
| Deploy | Render (`Legalised_AI`): web + api services, `render.yaml` |

```
backend/
  app/
    routers/     HTTP surface: auth, requests, inbound, intake, esign, playbook,
                 mailbox, metrics (SLA), contracts (CLM), admin, meta
    services/    core logic: intake, triage, generation, redline, approvals,
                 ai, audit, esign, email_poller, email_intake, secrets,
                 playbooks, metrics, contracts, extract, ratelimit
    models.py    SQLAlchemy models (single Request spine + AuditEvent ledger)
    schemas.py   Pydantic response models
    permissions.py  Permission enum + ROLE_PERMISSIONS
    main.py      app wiring, startup (migrations + idempotent demo helpers + poller)
    seed.py      org, users, counterparties, playbook (no Request rows)
  alembic/versions/  migration chain (see below)
frontend/
  app/           App Router pages + components (AppShell, Sidebar, Icons, …)
  lib/           api.ts (typed client), auth.ts
word-addin/      Office.js task pane
```

### Migration chain (Alembic owns the schema; runs on startup)
```
749f2185531e  baseline_schema
7fcbc30669ee  esign_envelope_tracking_on_request
76632dab1ed8  unique_playbook_rule_key_per_playbook
a1b2c3d4e5f6  request_playbook_link
b2c3d4e5f6a7  email_mailbox
c3d4e5f6a7b8  contract_lifecycle (executed_at, expires_at, renewed_from_id)
d4e5f6a7b8c9  unique_renewed_from (partial unique index — one renewal per contract)
e5f6a7b8c9d0  intake_platform (request_type, routing_rule, obligation, queue-ops columns)
f6a7b8c9d0e1  unique_obligation_per_request_kind
a7b8c9d0e1f2  playbook_contract_type (contract_type_key + per-org type index)
b8c9d0e1f2a3  risk_assessment (score + band + factors per request round)
c9d0e1f2a3b4  risk_ladder_matrix (band -> rungs JSON on request_type)
d0e1f2a3b4c5  negotiation_rounds (WITH_COUNTERPARTY/RETURNED states, round counters)
e1f2a3b4c5d6  workflow_templates (versioned rung blueprints + pinned instance snapshot)
```
New schema changes are ordinary Alembic revisions chained from the current head.
Never re-edit a migration that has shipped to production — add a new one on top.

---

## Non-negotiable architectural commitments

1. **One `Request` spine.** Intake, redline, approval, e-sign, filing, and
   renewal all attach to a single `Request` row. Don't fork parallel tables.
2. **The audit row is the legal anchor.** Every state-changing path writes an
   `AuditEvent` via `services/audit.record_audit`. The ledger is append-only and
   hash-chained; tamper detection re-computes hashes from stored fields,
   independent of any trigger. Never UPDATE/DELETE an audit row — correct with a
   new one.
3. **The ledger is the source of truth for "when did X happen."** Denormalized
   timestamps on `Request` (`updated_at`, etc.) drift. When a computation needs
   the moment a state was *first* reached (SLA resolution clock; contract
   `executed_at` backfill), read the earliest matching `AuditEvent`, not the
   mutable column. This is why the SLA cycle-time and the contract expiry are
   both anchored to `request.approved` / `request.executed` ledger events.
4. **Assemble, don't free-generate.** Outbound NDAs are built from pre-approved
   clauses, so the AUTO path is on-playbook by construction and safe to
   auto-send. Claude is used for *judgement* (semantic redline checks, extraction),
   never to hallucinate contract text.
5. **Claude is optional.** The whole product runs with no `ANTHROPIC_API_KEY` —
   generation falls back to deterministic assembly, semantic checks to a keyword
   heuristic. The demo never breaks.
6. **AgentDecision gate.** Every AI-proposed change (inbound redline finding)
   enters PENDING and cannot reach the counter-proposal until a human approves.
   Conservative AI governance is the product, not a future feature.
7. **Provider-abstracted seams.** E-signature (`get_esign_client()`), M365/IMAP
   intake, and the AI client are all behind interfaces. Swapping a provider is a
   new implementation behind the same seam — no caller moves.
8. **Every mutation is permission-gated** through `require(Permission.X)` on the
   route, with rung checks where approval rank matters. No "trust the client".
9. **The demo never breaks.** Every change keeps the end-to-end flow working:
   request an NDA → AUTO auto-approves & files; 36-month/foreign-jurisdiction →
   ASSISTED → clear the ladder → send → sign → Filed → tracked in `/contracts`.

---

## Permission model

The `Permission` enum in `backend/app/permissions.py` is the single source of
truth; roles pick from it in `ROLE_PERMISSIONS`. Current permissions:

`request:create`, `request:read_all`, `request:read_own`, `review:decide`,
`request:send`, `playbook:read`, `playbook:manage`, `intake:manage`,
`admin:manage_users`.

Add new values, never repurpose existing ones (breaks the seeded roles). Gate
both the UI affordance and the server mutation.

---

## Demo data discipline

- `seed.py` creates the org, 6 users, counterparties, and the playbook — **no
  `Request` rows**. Demo requests accumulate at runtime through the real intake
  flow.
- Idempotent startup helpers in `main.py` (`_ensure_demo_playbooks`,
  `_ensure_demo_contracts`) add demonstrable fixtures guarded by name/ref, and
  only ever add or self-heal — never destructively touch existing rows.
- **Demo contracts carry `channel="SEED"`** (pre-platform historical) so
  `ops_metrics` excludes them from the SLA/deflection KPIs — a fabricated
  instant-resolve must not distort the real ops picture. Any future
  synthetic-but-resolved fixtures must do the same.
- Auto-create / backfill patterns belong in seed + dev-mode fallbacks only.
  Production runtime code fails loud on missing references.

---

## House rules for future sessions

- **Ship one reviewable slice per change**, with the demo working at every
  checkpoint. Keep commits focused.
- **All schema changes are Alembic migrations** chained from head. Never
  re-edit a shipped migration; never `create_all` or ALTER at startup.
- **New backend logic goes in `services/`**, exposed through a thin router.
  Routers gate permissions and translate errors to HTTP; services hold the logic.
- **Frontend talks to the API only through `frontend/lib/api.ts`** (typed
  client). New surfaces reuse the AppShell + `globals.css` design tokens and the
  existing atoms (`.stat`, `.seg`, `.tbl`, `.pill`, `.sla-clock`, `.notice`).
- **Adversarially review substantive features before calling them done** — the
  SLA and CLM slices each went through a multi-dimension review (correctness,
  edge cases, integration) with every finding independently verified, then fixes
  applied and re-deployed. Prefer this over trusting a green build.
- **Verify end-to-end, not just tests** — drive the real flow (screenshots
  against the running stack, authenticated API round-trips) before shipping.
- **Never commit the model identifier**, secrets, or the Gmail app password to
  the repo. Screenshot scripts and recorded media stay untracked.
- Push to the working branch; open a PR only when explicitly asked.

---

## Local development

```bash
docker compose up -d postgres          # or point DATABASE_URL at any Postgres

cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head                   # also runs on app startup
python -m app.seed                     # org, users, counterparties, playbook
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
cp .env.local.example .env.local
npm run dev                            # http://localhost:3000
```

Demo logins (password `demo1234`, all `@northwind.example`): `admin@` /
`priya.nair@` (gc) / `dana.osei@` (vp_legal) / `marcus.reid@` (attorney) /
`sam.carter@` (requester) / `val.ng@` (viewer).

Backend tests: `cd backend && . .venv/bin/activate && pytest` (triage fork,
audit hashing, and per-feature suites — 65 passing).

Set `ANTHROPIC_API_KEY` to turn on real Claude semantic analysis; without it the
deterministic/heuristic fallbacks keep everything working.

---

## Changelog (newest first)

Each entry landed as one commit, demo green at every step.

| Commit | What |
|---|---|
| `6203551` | **AI-native spine (slice 4/4) — nav rewire** — Home (the supervisor feed) leads; the 18 nav items regroup by purpose into **Work** (Home · Intake queue · Cockpit · Ops · Contracts · SLA), **AI tools** (Assistant · Tabular · Editor · Agent — now also docked on every matter), **Intake** channels, **Platform**. Reads as a workspace with one daily driver, not a flat feature menu |
| `7be9056` | **AI-native spine (slice 3/4) — case-file matter + docked copilot** (`/t/[id]`) — the matter page becomes the living record (workflow stepper + SLA custody legs + chain-sealed timeline) **plus a docked Copilot scoped to that matter**: Ask + Run tabs (reusing the assistant + agent engines, pre-scoped, no re-picking) + quick links to Editor / redline cockpit. Closes the loop — a decision on the feed opens the matter and you work it with AI right there; the four AI surfaces become in-context tools, not destinations |
| `c65ba7f` | **AI-native spine (slice 2/4) — brief-driven filter** (`/`) — the Daily-brief count chips + criticals filter the decision feed in place; the brief is an actionable control, not static text |
| `7944c10` | **Supervisor feed — the AI-native spine (slice 1/4)** (`/`) — reframes the home from a feature menu into one **decision stream**: everything the AI/pipeline has done that awaits a human call, aggregated across modules into a single prioritized feed (proposed redlines, drafted advice answers, contracts cleared to send, renewals due), critical-first. Each card names *what the AI did + why* and offers the **governed action** (approve/edit/send/renew/review) — which routes through the existing chain-sealed endpoints (verified: send-for-signature from the feed removes the card). Topped by a **Daily-brief** strip ("4 need you first — 28 redlines to clear · 7 cleared to send · 1 renewal"). Backend `services/decisions.py` (read aggregation, permission-scoped, no new schema) + `GET /api/decisions`. Old Mission Control preserved at `/overview`. Next slices: narrated brief, case-file timeline, nav rewire |
| `98251a7` | **Agentic workflow runner** (`/agent`) — Harvey's Workflow-Agent surface: state a goal in plain language → the agent **plans** a multi-step run, **executes** each step against Frontdoor's real engines (goal interpretation, contract summary, the risk engine, the redline engine, workspace search), streams progress as a live step timeline, and **synthesizes** a recommendation. Backend `services/agent.py` + `POST /api/agent/run` SSE (`plan` → `step*` with results/sources → `delta*` streamed recommendation → `done`); the recommendation is a synthesized Claude plan when `ANTHROPIC_API_KEY` is set, else a decisive plan assembled from the findings. Composes the existing engines as read-only tools — advisory, never mutates state; one `agent.run` row seals the run on the audit chain. Frontend: goal composer, scope selector, step timeline with status dots + per-step source links + streamed recommendation card |
| `6fb1489` | **Drafting Editor** (`/editor`) — Harvey/Legora's "Editor": draft or revise contract language in a live document, get a **streamed** AI suggestion grounded in your playbook, and **accept/reject it in place**. Select text → the AI revises it (red strike-through before / green after diff); no selection → it drafts at the cursor. Backend `services/editor.py` (`POST /api/editor/draft` SSE `grounding` → `delta*` → `done`); Claude streams a clean clause when `ANTHROPIC_API_KEY` is set, else it **assembles from the best-matching playbook clause** (assemble-don't-free-generate). DB grounding retrieval runs before streaming. Advisory — nothing applied until Accept; each generation sealed on the audit chain (`editor.generate`). Frontend: document canvas, selection-aware instruction bar + presets, suggestion card with grounding chips, Load-document picker |
| `ac11b9b` | **Tabular Review** (`/tabular`) — Legora's signature surface: pick a set of documents → each becomes a **row**, each question you write becomes a **column**, each **cell** an extracted answer linked to its source section (`§N →`), the grid filling progressively. Backend `services/tabular.py` (`GET /api/tabular/documents` corpus + `POST /api/tabular/run` SSE `meta` → `cell*` → `done`); per-cell extraction is Claude (crisp value + section) when `ANTHROPIC_API_KEY` is set, deterministic best-clause extract otherwise; DB (authorize rows + fetch clauses) runs before streaming. Advisory & read-only — one `tabular.review` row seals the whole run on the audit chain (not one per cell). Frontend: document picker, column editor with presets, sticky-first-column grid, per-cell source links + spinners, row filter, column sort, CSV export |
| `9049ce2` | **Grounded Assistant** (`/assistant`) — the Harvey-style daily driver: a document-grounded chat that answers **only** from the caller's readable workspace (clauses, playbook positions, requests) with a **source citation on every claim** and **streaming** responses. Backend `services/assistant.py` (deterministic keyword retrieval, permission- + org-scoped) + `POST /api/assistant/ask` SSE stream (`sources` → `delta*` → `done`); DB work runs before streaming so the generator never touches a closed session. Real Claude streaming when `ANTHROPIC_API_KEY` is set, honest deterministic extract otherwise. Advisory only — never mutates state; **every query sealed on the audit chain** (`assistant.query`). Frontend chat with inline `[n]` citation chips linking to the matter/playbook, a Sources panel, scope selector (all matters / one request), suggested prompts |
| `6d7e082` | **Intake port — Slice C: Ops Workspace tab set** (`/workspace`) — the AEGIS intake tab set ported onto Frontdoor's existing data (pure frontend, no backend change). Five tabs: **Board** (5-column pipeline Kanban grouped by governed state — read-only, cards link to `/t`; viewport-capped, columns scroll internally), **Pool Ops** (reviewer utilization bars + lane mix + unassigned overflow, from listRequests × assignableUsers), **Smart Routing** (WHEN→THEN rule cards from listRoutingRules; gated with an honest "needs intake:manage" message for non-managers rather than a false "no rules" empty state; edit link to `/admin/routing`), **Teams** (reviewer roster grouped by role with per-person open load), **Request Types** (CONTRACT/ADVICE engine catalog with filed counts). Tab bar + nav entry |
| `5cfb8e2` | **Intake port — Slice B: Triage Cockpit** (`/cockpit`) — keyboard-first single-ticket review ported from the AEGIS intake module. Header status bar (Queue N of M · Triaged this session · Reviewer), ticket card (ref/lane/risk/state/round pills + serif subject + purpose + "why it triaged here"), context-aware recommendation panel (advice → approve drafted answer / write answer when none / edit; contract → open redline cockpit or send-for-signature when APPROVED), other-actions (open/reassign/assign-to-me/snooze), sticky hint bar + `?` cheatsheet. Shortcuts: `j`/`k`/arrows navigate, `a` primary, `e` edit, `o`/`↵` open, `r` reassign, `m` mine, `s` snooze, `/` search, `?` help, `Esc` cancel. Polling pauses mid-edit so a queue reshuffle can't discard an in-progress answer; empty answers can't be approved |
| `b78caa9` | **Intake port — Slice A: ticket-detail workflow view** (`/t/[id]`) — ported from AEGIS: header strip (pills + live SLA-window clock), 4-stage workflow stepper computed from request state, **SLA custody legs** (`GET /api/requests/{id}/sla-legs` + `services/sla_legs.py`) derived from the hand-off ledger — one window partitioned by every baton pass (queue/agent/human), breach lands in exactly one leg — beside the chain-sealed timeline. Inbox rows now open `/t/[id]` |
| `5b19820` | Fix 16 review findings on the workflow engine — dual-gate APPROVED (ladder AND redlines), round-2 send uses the counter-proposal not raw markup, thread-match sender validation, CRITICAL floors for walk-away/sanctions, 409s for racing returns, honest step reasons |
| `541a70d` | **Slice 5**: workflow designer UI (`/admin/workflows`), matter ladder rail + risk badges in the cockpit, negotiation panel, live risk matrix, SLA workflow insights |
| `c344ec3` | **Slice 4**: workflow-as-data — versioned templates, pinned/conditional rungs, instance pinning, stage executor with time-at-stage |
| `aa1e720` | **Slice 3**: the negotiation loop — rounds, counterparty returns (paste/upload/email thread-match), per-round re-redline + re-score + rebuilt ladder |
| `02accbf` | **Slices 1+2**: AI risk score (deterministic core + raise-only AI adjustment) + score-driven approval ladders via per-type band matrix |
| `d2a5701` | **Phase 2 — second CONTRACT engine**: type-scoped playbooks (one default per type, schema-enforced), DPA type + seeded 9-rule playbook, type gate (non-NDA never AUTO), rule-derived clause taxonomy, typed intake surfaces; 3-pass adversarial review, all findings fixed (DPA renewal 500, NDA-policy leak into DPA checks, advice/contract boundary, mailbox playbook guard, email/chat DPA detection) |
| `2fa3ee6` | Fix 24 review findings — draft-leak gate, semantic-aware ladder, org scoping, routing hardening, queue-ops permissions |
| `843d88a` | **Intake platform**: request-type catalog + ADVICE resolution engine, routing rules + dry-run, playbook fallback/walk-away ladders, obligations, ⌘K + single-key triage + snooze + saved views + bulk, type-to-confirm |
| `ca40293` | Fix CLM review findings — idempotent renewal (unique index + atomic link), non-destructive renew errors, SEED-channel SLA isolation |
| `bf869c3` | **CLM half**: contract registry + renewal tracking (`/contracts`, `executed_at`/`expires_at`/`renewed_from_id`, ledger backfill) |
| `151be19` | Fix SLA review findings — ledger-anchored cycle time, reconciling in-flight breakdown, unit formatting |
| `4ee1a12` | **SLA & deflection dashboard** (`/sla`, `/api/ops/summary`) |
| `84f8a68` | Rebuild home / new-request / status-tracker to match Document Desk |
| `51bc425` | Rebuild review screen as **Document Desk** + inbox as **triage table** |
| `0a69e33` | **Email intake**: poll a real IMAP legal inbox into the pipeline |
| `2b0fb10` | **Multi-playbook** support per organisation |
| `1ed325f` | Redesign UI to refined-enterprise premium SaaS shell |
| `48d5aa3` | Fix playbook review findings (cross-org IDOR + governance + dup key) |
| `fd30887` | Playbook admin UI + learning flywheel |
| `9dce1d1` | Word add-in: redline engine in an Office.js task pane |
| `2743fbd` | Real e-signature: DocuSign behind the esign seam + webhook |
| `cc2bc52` | Harden 2/2: Alembic migrations replace create_all + startup ALTERs |
| `b6b02ec` | Harden 1/2: prod secret guards, rate-limiting, 401 auto-logout, health |
| `e79e0ee` | Multi-channel intake: email webhook + chatbot through one pipeline |
| `965397e` | .docx / PDF ingestion for inbound review |
| `e58c289` | Real LLM semantic checks via Claude with heuristic fallback |
| `8b3c35e` | Auth + RBAC: JWT login, 8-role model, rung-gated approvals |
| `57a12d1` | **Inbound redline engine** + gated AgentDecisions + redline cockpit |
| `2c1f8c8` | Deployment config: Dockerfile, render.yaml, env-driven CORS, seed-on-start |
| `71501bc` | **Walking skeleton**: outbound-NDA spine (FastAPI + Next.js + Postgres) |

When you add a feature, add a row here and update the plan's Done/Not-yet lists.
