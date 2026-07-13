# Frontdoor — legal front door + CLM (NDA wedge)

A legal-operations platform that closes the loop nobody else owns: a request
comes in → it's classified and triaged → routed through the right approval
ladder → an engine does the work (drafts the NDA from the company's playbook) →
a human governs each step → it's executed and filed — every transition on a
tamper-evident audit chain.

This repo is the **walking skeleton**: the *outbound NDA* path, end to end, on a
real database with real screens. It is deliberately the thinnest slice that
proves the spine. Inbound third-party redlining (the hybrid playbook + redline
engine) is the next slice.

```
Request (the spine)
  └─ classify → triage(route) → generate(from playbook)
       ├─ AUTO      → auto-approved → send → executed → filed        (no lawyer)
       └─ ASSISTED  → approval ladder → send → executed → filed      (human gate)
```

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI + SQLAlchemy 2.0 (sync) |
| Database | Postgres 16 |
| Frontend | Next.js 14 (App Router) + TypeScript |
| AI | Anthropic Claude (optional — deterministic assembly is the default) |

## What's built

- **One `Request` spine** with a real state machine (`NEW → CLASSIFIED → ROUTED
  → DRAFTED → IN_REVIEW/APPROVED → OUT_FOR_SIGNATURE → EXECUTED → FILED`).
- **Deterministic triage** that forks AUTO / ASSISTED / ESCALATED and returns
  the *reasons* it fired (explainable automation).
- **Structured playbook** (12 seeded NDA clauses, each with a preferred body,
  a `rule_key` citation target, and the approval rung a deviation triggers).
- **Outbound generation by assembly** — the NDA is stitched from the playbook's
  *preferred* clauses (lowest-hallucination-risk path), stored as an addressable
  `Document → DocumentVersion → Clause[]` model with a content hash.
- **Approval ladder assembled from triage** — deduped by rung, assigned to the
  right reviewer (VP Legal, GC).
- **Append-only, hash-chained audit log** — every transition writes a row whose
  hash folds in the previous row's; `GET /api/audit/verify` re-walks and reports
  the first break. The header badge reads "✓ Audit chain intact".
- **Two faces, one spine**: a requester package-tracker (`/r/[id]`) and a lawyer
  review cockpit (`/review/[id]`), plus a triage inbox (`/inbox`).
- **Playbook admin + learning flywheel** (`/admin/playbook`) — GC/legal-ops manage
  the clause rules the engine reasons against (preferred language, which deviations
  need which sign-off rung, which clauses are mandatory) in-app instead of via the
  seed. Every change bumps the playbook version and is chain-sealed. The **flywheel**:
  when a lawyer edits a proposed redline, one click adopts that language as the
  rule's new preferred position (`playbook.rule.learned`) — the playbook improves
  every time it's corrected. Gated on the new `playbook:manage` permission.
- **Word add-in** (`word-addin/` + `/word-addin`) — an Office.js task pane that
  reads the open document, runs it through the inbound redline engine, and inserts
  proposed edits as **tracked changes** (`changeTrackingMode = trackAll`). Meets
  lawyers where they negotiate; falls back to a paste box in a plain browser.
- **Multi-channel intake** — a form (`/new`), a **chatbot** (`/chat`, natural
  language → extracted request), and an **email webhook**
  (`POST /api/intake/email-webhook`) all funnel through one `services/intake`
  core, so triage, drafting/redlining, and audit are identical per channel. The
  email adapter classifies inbound (they sent a contract — body or attachment)
  vs. outbound (they're asking for one) and routes accordingly; intent + field
  extraction uses Claude with a heuristic fallback.
- **Auth + RBAC**: email/password login (JWT bearer), 8 roles, and a permission
  model. Two authorization layers: permission grants (can you take this kind of
  action?) and **rung-gated approval** — a deviation that triggers the `gc` rung
  can only be cleared by someone of GC rank or above, so an attorney approving it
  is a 403, not a silent pass. Requesters see only their own requests; every
  mutation attributes to the authenticated user in the audit chain. Admin UI at
  `/admin` for role management (last-admin guard, chain-sealed).
- **Inbound redline engine** (`/inbound`): paste a counterparty's NDA **or
  upload their .docx / .pdf** (text extracted via python-docx / pypdf) → it's
  segmented into clauses, classified against the playbook, and checked by a
  **hybrid** engine — *deterministic* validators for the things LLMs get wrong
  (liability cap / term in months, governing-law jurisdiction, missing mandatory
  clauses) and *semantic* checks routed through **Claude** (`services/ai.py`) —
  "does this prose actually meet our position?" — with a keyword heuristic
  fallback so it runs with no API key. Set `ANTHROPIC_API_KEY` to turn on real
  model analysis; Claude failures degrade to the heuristic, never breaking the
  review. Each
  finding is a **proposed redline in PENDING state** (the AgentDecision gate);
  nothing enters the counter-proposal until a human approves it. The request
  becomes sendable only once every change is decided.

## Run it

**1. Postgres**
```bash
docker compose up -d postgres          # or point DATABASE_URL at any Postgres
```

**2. Backend**
```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head                   # build the schema (also runs on app startup)
python -m app.seed                     # org, reviewers, counterparties, playbook
uvicorn app.main:app --reload --port 8000
```

**3. Frontend**
```bash
cd frontend
npm install
cp .env.local.example .env.local
npm run dev                            # http://localhost:3000
```

## Try the flow

- Visit **http://localhost:3000/new**, request an NDA with *Acme Corporation*,
  purpose *Sales evaluation*, term *24 months* → lands in the **AUTO** lane,
  drafted and auto-approved, no lawyer.
- Request one with term *36 months* or jurisdiction *Germany* → **ASSISTED**:
  open it from the **Legal inbox**, clear the approval ladder, send, and
  simulate the counterparty signature to reach **Filed**.

## Tests
```bash
cd backend && . .venv/bin/activate && pytest        # triage fork + audit hashing
```

## Notable design decisions

- **Assemble, don't free-generate.** Outbound NDAs are built from pre-approved
  clauses, so the AUTO path is on-playbook by construction and safe to auto-send.
- **The audit row is the legal anchor.** The chain is verifiable independently of
  any immutability trigger — tamper detection re-computes hashes from stored
  fields.
- **The playbook is data, not a document.** Each rule carries structured params
  and the approval rung a deviation triggers — this is what lets the approval
  ladder be *assembled from findings* rather than fixed per document, and it's
  the seam the inbound redline engine plugs into next.
- **Claude is optional.** The whole product runs with no API key; generation
  falls back to deterministic assembly so the demo never breaks.
- **Schema is Alembic-managed.** Migrations run on startup: a fresh DB is built
  from `alembic upgrade head`; a DB that predates Alembic is adopted via `stamp`
  (no recreation, no data loss). New schema changes are ordinary Alembic revisions.
- **E-signature is provider-abstracted.** `send` routes through `get_esign_client()`
  — DocuSign when `DOCUSIGN_*` env vars are set, else a stub that signs the demo
  end-to-end. Completion arrives via the HMAC-verified `POST /api/esign/webhook`
  (flips the request to EXECUTED/FILED); the "simulate signature" button is a
  dev-only shortcut and is hidden once DocuSign is wired.
- **Production fail-loud.** With `ENVIRONMENT=production`, the app refuses to boot
  without a strong `AUTH_SECRET` and an `INTAKE_WEBHOOK_SECRET` — a clear failure
  instead of a silent weak-secret deploy.

## Not yet built (next slices)

1. **Real M365 email polling** — the webhook adapter is channel-agnostic; a Graph
   poller would call it per message (no code-path change).
2. **OCR for scanned PDFs** (image-only PDFs currently error with a clear message).
4. **OCR for scanned PDFs** (image-only PDFs currently error with a clear message).
5. **Playbook-learning flywheel** (learn positions from lawyer overrides) and a
   playbook admin UI.
