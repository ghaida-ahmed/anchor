# Deploying ANCHOR

This document covers what the application needs from a host, the options that
actually fit it, and the exact procedure. It stops short of choosing an account or
a plan — those are decisions with a bill attached.

---

## What ANCHOR needs

| Requirement | Why it constrains the choice |
|---|---|
| **PostgreSQL 15+ with the `vector` extension** | Embeddings live in `document_chunks.embedding vector(1536)`. A managed Postgres without pgvector cannot run this schema at all — the first migration fails on `CREATE EXTENSION vector`. |
| **A long-lived Python process** | FastAPI is ASGI, and document processing runs as a FastAPI `BackgroundTask` *after* the response is sent. A serverless function that freezes once it returns will kill ingestion halfway, leaving documents stuck in `processing`. |
| **Persistent file storage** | Uploaded PDFs are written to disk. On an ephemeral filesystem they vanish on every deploy while their database rows survive, giving courses whose materials 404. |
| **Outbound HTTPS** | To reach the Gemini API. |
| **Static hosting for the frontend** | A Vite build is plain files. Anything can serve them. |

The second row is the one that eliminates most of the trendy answers.

---

## Options considered

### Frontend

Genuinely interchangeable — it is static output. **Vercel**, **Netlify** and
**Cloudflare Pages** all have free tiers that comfortably cover this, deploy from
a GitHub push, and give HTTPS and a CDN without configuration. Vercel is assumed
below because it is the one you already prefer; nothing in the codebase depends
on that choice, and switching is changing one build command.

### Backend + database

| Option | pgvector | Long-lived process | Persistent disk | Verdict |
|---|---|---|---|---|
| **Render** — Web Service + Managed Postgres | Yes, `CREATE EXTENSION vector` is permitted | Yes | Yes, a paid add-on; free tier has none | **Recommended.** The only one where every requirement is met by default rather than worked around. Free tier spins down when idle, so the first request after a pause is slow — acceptable for a portfolio, and honest to mention in a demo. |
| **Railway** — service + Postgres | Yes | Yes | Yes, volumes supported | Close second, and arguably nicer to use. Its free allowance is a monthly credit rather than a standing free tier, so a project left running can stop without warning. |
| **Fly.io** — machine + Fly Postgres | Yes | Yes | Yes, real volumes | Technically the best fit, and the most configuration. Fly Postgres is an unmanaged cluster you are responsible for. More operational surface than a portfolio project should carry. |
| **Vercel** for the backend | n/a | **No** | **No** | Rejected. Vercel's Python runtime is serverless: the function is frozen after the response, so background document processing would be killed mid-ingest. This is a real incompatibility, not a preference. |
| **Supabase** for the database only | Yes, pgvector is available | n/a | n/a | A reasonable pairing with any of the above if you want a database with a good dashboard. Adds a second vendor for no capability the others lack. |

### Storage

Uploads are the one place where "just deploy it" quietly loses data.

1. **A persistent volume on the backend host** — no code change, `STORAGE_BACKEND=local`. Usually a small paid add-on.
2. **Object storage** (Cloudflare R2, Supabase Storage, S3) — needs a new `StorageService` subclass, which is why `get_storage_service()` is a factory with a branch. R2 has a free tier and no egress fee.
3. **Accept the loss for a demo** — documents disappear on redeploy. Only defensible if the demo re-uploads them, and only if you say so.

There is no default here that is both free and correct, which is why this is a
decision and not a recommendation.

---

## Recommended architecture

```
Vercel (static)            Render (web service)          Render (managed Postgres)
┌────────────────┐         ┌──────────────────┐          ┌────────────────────┐
│  React build   │  HTTPS  │   FastAPI        │   TLS    │  PostgreSQL 17     │
│  Vite output   │ ──────▶ │   uvicorn        │ ───────▶ │  + pgvector        │
└────────────────┘         │   1 worker       │          └────────────────────┘
                           └────────┬─────────┘
                                    │ HTTPS
                                    ▼
                             Gemini API
```

One frontend, one backend, one database. No queue, no cache, no second service —
none is needed at this size, and each would be something to explain in an
interview without a reason behind it.

**Why one worker.** The rate limiter keeps its counters in process memory. Two
workers means two independent sets of counters and therefore double the effective
limit. Fixing that properly means Redis, which is not worth a fourth service here;
scaling up is the point to revisit it.

---

## Procedure

### 1. Database

Create the Postgres instance, then enable the extension once:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Take the connection string and append `?sslmode=require` if the provider does not
already include it.

### 2. Migrations — explicitly, never on startup

```bash
DATABASE_URL='postgresql+psycopg://...' python -m alembic upgrade head
```

Run this as a one-off command (a Render "Job", a `railway run`, or `docker exec`)
**before** the new code starts serving.

The application does not migrate on boot, deliberately. On boot it would mean a
rollback silently mutates the schema, two containers starting together race each
other, and a failed migration takes down a previously healthy deployment.

Verify:

```bash
python -m alembic current   # should print the head revision
python -m alembic check     # should report no new operations
```

### 3. Backend service

* **Build:** `pip install -r requirements.txt`
* **Start:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`
* **Health check path:** `/api/ready`

Environment variables — set these in the platform's dashboard, never in a file:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `SECRET_KEY` | 48+ random chars — `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `DATABASE_URL` | the connection string from step 1 |
| `CORS_ORIGINS` | `["https://your-frontend-domain"]` — a JSON array |
| `GEMINI_API_KEY` | your key |
| `UPLOAD_DIR` | the mount path of the persistent volume, if you attached one |

If any of these is wrong the process **refuses to start** and logs which variable
and why. That is intentional: a boot failure you can read is better than a running
service with forgeable tokens.

### 4. Frontend

* **Build:** `npm ci && npm run build`
* **Output:** `dist`
* **Environment:** `VITE_API_BASE_URL=https://your-api-domain/api`

Remember that everything `VITE_*` is compiled into the bundle and publicly
readable. The only value that belongs there is the API's own URL.

### 5. After deploying

```bash
curl https://your-api-domain/api/health   # {"status":"ok",...}
curl https://your-api-domain/api/ready    # database: true
```

Then register an account, upload a document, and confirm it reaches `ready` —
that single path exercises the database, storage, and the embedding provider
together.

---

## Cost

Free tiers cover the frontend and, on Render, the backend and database — with the
free instance spinning down when idle and the free database expiring after a
limited period on current terms. Persistent storage is the one line that is not
free anywhere.

Gemini's free tier has request and token limits that vary by model and change over
time; check AI Studio for your account's current figures. The application's
`ai` rate-limit bucket exists to stop a runaway client emptying whatever those
limits are.

**Confirm current pricing and free-tier terms with each provider before signing
up.** Anything written here about a specific plan is a snapshot, not a promise.
