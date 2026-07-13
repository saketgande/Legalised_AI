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

## Not yet built (next slices)

1. **Inbound third-party review** — upload counterparty paper → parse to
   `Clause[]` → hybrid engine (deterministic checks for numbers/dates/defined
   terms + LLM for semantic comparison) → proposed redlines as pending
   `AgentDecision`s → approval gated.
2. **Word add-in + web editor** as two thin clients over one `editOps` protocol.
3. **Real e-signature** (DocuSign/Adobe) at the `esign.py` seam.
4. **Auth / RBAC**, Alembic migrations (skeleton uses `create_all`), and the
   playbook-learning flywheel (learn positions from lawyer overrides).
