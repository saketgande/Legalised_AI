# Deploying Frontdoor

Three services: **Postgres**, the **FastAPI backend**, the **Next.js frontend**.
The app is env-driven, so any host works. Two recommended paths below.

---

## Option A — Render blueprint (whole stack, one repo)

The repo ships a [`render.yaml`](./render.yaml) blueprint that provisions all
three services.

1. Push this repo to GitHub.
2. In [Render](https://render.com) → **New +** → **Blueprint** → pick the repo.
   Render reads `render.yaml` and creates the database + both web services.
3. First deploy finishes with two URLs, e.g.
   `https://legalised-api.onrender.com` and `https://legalised-web.onrender.com`.
4. Set the two cross-referencing env vars (marked `sync: false`), then redeploy:
   - On **legalised-api** → `CORS_ORIGINS = https://legalised-web.onrender.com`
   - On **legalised-web** → `NEXT_PUBLIC_API_URL = https://legalised-api.onrender.com`
5. The backend auto-seeds on first boot (`SEED_ON_START=true`), so the playbook
   and reviewers are ready. Visit the web URL.

> Free-tier services sleep when idle — the first request after a nap takes a few
> seconds to wake. Fine for a demo.

---

## Option B — Vercel (frontend) + Neon (db) + a host for the API

Best if you want the slickest frontend hosting.

**Database — [Neon](https://neon.tech):** create a project, copy the connection
string.

**Backend — [Render](https://render.com) / [Railway](https://railway.app) / [Fly](https://fly.io):**
deploy `backend/` (a `Dockerfile` is included). Set:
- `DATABASE_URL` = the Neon connection string
- `SEED_ON_START` = `true`
- `CORS_ORIGINS` = your Vercel URL (e.g. `https://legalised-ai.vercel.app`)

**Frontend — [Vercel](https://vercel.com):** import the repo, set **Root
Directory** to `frontend`. Add env var:
- `NEXT_PUBLIC_API_URL` = your backend URL

Deploy. Done.

---

## Environment variables (reference)

| Service | Var | Example | Notes |
|---|---|---|---|
| backend | `DATABASE_URL` | `postgresql://…` | `postgres://` / `postgresql://` auto-normalized to the psycopg2 driver |
| backend | `CORS_ORIGINS` | `https://legalised-web.onrender.com` | comma-separated; must include the frontend origin |
| backend | `SEED_ON_START` | `true` | idempotent — seeds only when the DB is empty |
| backend | `ENVIRONMENT` | `production` | turns on fail-loud secret guards; refuses to boot without the two secrets below |
| backend | `AUTH_SECRET` | *(random)* | JWT signing secret — must be a strong random value (>=16 chars) in prod |
| backend | `INTAKE_WEBHOOK_SECRET` | *(random)* | required in prod; email webhook then requires the `X-Intake-Secret` header |
| backend | `AUTH_DEMO_PASSWORD` | `demo1234` | password the seed sets on demo logins |

> **Enabling production hardening on an existing deploy:** Render applies
> `render.yaml` env changes only on a manual **blueprint sync**, so an existing
> service keeps running in development mode until you either sync the blueprint or
> set `ENVIRONMENT=production` + `INTAKE_WEBHOOK_SECRET` + a strong `AUTH_SECRET`
> on the service. Once `ENVIRONMENT=production`, the app refuses to start unless
> those secrets are present — a clear boot failure instead of a silent weak-secret
> deploy.
| backend | `ANTHROPIC_API_KEY` | *(optional)* | absent → deterministic generation, demo still works |
| frontend | `NEXT_PUBLIC_API_URL` | `https://legalised-api.onrender.com` | baked at build; redeploy after changing |

## Production hardening still to do
The skeleton uses `create_all` (swap for Alembic migrations), has no auth
(add before real data), and the e-signature step is stubbed. See the README's
"next slices."
