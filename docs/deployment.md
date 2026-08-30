# Deploying ANCHOR

**Target architecture**

```
Vercel (static)          Render (Docker web service)      Supabase
┌──────────────┐         ┌────────────────────┐          ┌──────────────────────┐
│ React build  │  HTTPS  │ FastAPI + uvicorn  │   TLS    │ PostgreSQL 17        │
│ Vite output  │ ──────▶ │ 1 worker           │ ───────▶ │ + pgvector           │
└──────────────┘         │                    │          ├──────────────────────┤
                         │                    │  HTTPS   │ Storage              │
                         │                    │ ───────▶ │ private bucket       │
                         └─────────┬──────────┘          └──────────────────────┘
                                   │ HTTPS
                                   ▼
                             Gemini API
```

**Supabase is used for two things only: the Postgres database and a private file
bucket.** ANCHOR's own authentication is unchanged — registration and login stay
`React → FastAPI → bcrypt/JWT → users table over SQLAlchemy`. Supabase Auth is not
used, and the Supabase client library is not a dependency; storage speaks to a
documented REST endpoint with `httpx`.

---

## What you need to do, in order

Each numbered step below is something **you** do in a provider dashboard. Nothing
here needs a credit card.

> **Never paste a secret into a chat, a file in this repository, or a `VITE_`
> variable.** Every secret goes straight from the provider's dashboard into
> Render's environment variables.

---

## 1. Supabase — create the project

1. Go to <https://supabase.com> and sign in with GitHub.
2. **New project**. Choose your personal organisation.
3. Name it `anchor`.
4. **Database Password** — Supabase generates one. Click the copy icon and paste
   it into your password manager now. You cannot see it again, and you will need
   it in step 3.
5. Region: pick the one nearest you (it must match nothing else; latency only).
6. Plan: **Free**.
7. **Create new project**, then wait ~2 minutes for it to provision.

## 2. Supabase — enable pgvector

ANCHOR stores embeddings in a `vector(1536)` column. Without this extension the
very first migration fails.

1. Left sidebar → **Database** → **Extensions**.
2. Search for `vector`.
3. Toggle it **on** (it may be listed as `vector` — the extension behind pgvector).

To confirm, open **SQL Editor** and run:

```sql
select extname, extversion from pg_extension where extname = 'vector';
```

One row means you are done. If you prefer, the same thing works from the SQL
editor directly:

```sql
create extension if not exists vector;
```

## 3. Supabase — collect the connection string

1. Click **Connect** at the top of the project (or **Project Settings →
   Database**).
2. Find **Connection string** and select the **Transaction pooler** entry.
3. Copy it. It looks like:

   ```
   postgresql://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-<region>.pooler.supabase.com:6543/postgres
   ```

4. Two edits before you use it:
   - replace `[YOUR-PASSWORD]` with the password from step 1.4;
   - change the scheme `postgresql://` to **`postgresql+psycopg://`** — that is
     how SQLAlchemy selects the psycopg 3 driver.

   The result is the value of `DATABASE_URL`.

**Why the pooler and not the direct connection.** The free tier allows few direct
connections; the pooler multiplexes them. ANCHOR detects a pooler URL and disables
psycopg's prepared statements automatically — without that you get intermittent
`prepared statement "_pg3_0" does not exist` errors that never appear locally.

**For migrations, use the direct connection instead** — see step 8.

## 4. Supabase — create the private storage bucket

1. Left sidebar → **Storage** → **New bucket**.
2. Name: `course-documents`
3. **Public bucket: OFF.** This is the important one. Course materials are
   private student files; a public bucket makes every uploaded PDF readable by
   anyone with the URL.
4. Create.

You do not need to add any RLS policies. ANCHOR reaches the bucket with the
service role key and enforces ownership itself, in the same SQL queries that
already protect every other route.

## 5. Supabase — collect the API values

**Project Settings → API keys** (or **Connect → App Frameworks**):

| What to copy | Goes into the variable |
|---|---|
| **Project URL** (`https://<ref>.supabase.co`) | `SUPABASE_URL` |
| **`service_role` secret key** — click *Reveal* | `SUPABASE_SERVICE_ROLE_KEY` |

⚠️ **The `service_role` key bypasses every security rule in the project.** It goes
into Render and nowhere else. Never into Vercel, never into a `VITE_` variable,
never into this repository. The `anon` / publishable key is *not* used by ANCHOR
at all — you can ignore it.

---

## 6. Render — deploy the backend

1. Go to <https://render.com> and sign in with GitHub.
2. **New → Web Service**.
3. Connect the `ghaida-ahmed/anchor` repository (authorise Render for that repo).
4. Settings:

   | Field | Value |
   |---|---|
   | Name | `anchor-api` |
   | Language / Runtime | **Docker** |
   | Root Directory | `backend` |
   | Dockerfile Path | `./Dockerfile` |
   | Instance Type | **Free** |
   | Health Check Path | `/api/ready` |

   Leave the build and start commands empty — the Dockerfile supplies them, and it
   already binds to Render's `$PORT`.

5. **Environment variables** — add each of these (names on the left, the values
   you collected above on the right):

   | Variable | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `DEBUG` | `false` |
   | `SECRET_KEY` | generate one, see below |
   | `DATABASE_URL` | from step 3 |
   | `CORS_ORIGINS` | `["https://REPLACE-ME.vercel.app"]` — a placeholder for now |
   | `GEMINI_API_KEY` | your existing key |
   | `STORAGE_BACKEND` | `supabase` |
   | `SUPABASE_URL` | from step 5 |
   | `SUPABASE_SERVICE_ROLE_KEY` | from step 5 |
   | `SUPABASE_STORAGE_BUCKET` | `course-documents` |

   Generate the signing key on your own machine and paste it straight into Render:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

6. **Create Web Service.**

If any of those variables is missing or unsafe, the container **refuses to start**
and the log says which variable and why. That is deliberate — a boot failure you
can read beats a running service with forgeable tokens.

> Render's free instances sleep after inactivity, so the first request after a
> quiet period takes ~30 seconds. Worth mentioning in a demo rather than being
> surprised by it.

## 7. Render — note the backend URL

After the first deploy, Render shows a URL like
`https://anchor-api.onrender.com`. You need it for Vercel.

## 8. Run the migrations — once, explicitly

**ANCHOR never migrates on startup.** On boot it would mean a rollback silently
mutates the schema, and two containers starting together race each other.

Use the **direct** connection for this, not the pooler: DDL and Alembic's
transactional migrations belong on a session-mode connection. In Supabase's
**Connect** dialog that is the *Direct connection* entry, on port `5432`.

From your own machine, in the repository:

```bash
cd backend
DATABASE_URL='postgresql+psycopg://postgres:YOUR-PASSWORD@db.<project-ref>.supabase.co:5432/postgres' \
  .venv/bin/python -m alembic upgrade head
```

Then confirm:

```bash
DATABASE_URL='<same>' .venv/bin/python -m alembic current   # prints the head revision
DATABASE_URL='<same>' .venv/bin/python -m alembic check     # "No new upgrade operations detected."
```

Only `upgrade head` is ever run against production. Never `downgrade`, never
`stamp`, and there is no seed step — ANCHOR ships no sample data.

## 9. Vercel — deploy the frontend

1. Go to <https://vercel.com> and sign in with GitHub.
2. **Add New → Project**, import `ghaida-ahmed/anchor`.
3. Settings:

   | Field | Value |
   |---|---|
   | Framework Preset | **Vite** |
   | Root Directory | `frontend` |
   | Build Command | `npm run build` (default) |
   | Output Directory | `dist` (default) |

   `frontend/vercel.json` already sets the SPA rewrite, so a deep link like
   `/courses/<id>` loads the app rather than 404ing.

4. **Environment variable** — exactly one, and it is not a secret:

   | Variable | Value |
   |---|---|
   | `VITE_API_BASE_URL` | `https://anchor-api.onrender.com/api` |

   Everything `VITE_*` is compiled into the JavaScript bundle and is readable by
   anyone who opens the site. **No Supabase key, no Gemini key, no database URL
   ever goes here.**

5. **Deploy**, and note the resulting URL.

## 10. Close the CORS loop

Back in Render, set `CORS_ORIGINS` to the real Vercel URL:

```
["https://anchor-<something>.vercel.app"]
```

It must be a JSON array, `https`, and no trailing slash. Save — Render redeploys
automatically.

Use the **production** domain, not a preview URL. Preview deployments get a new
hostname per commit, so pinning one would break on the next push.

---

## 11. Verify

```bash
curl https://anchor-api.onrender.com/api/health
# {"status":"ok","service":"ANCHOR API"}

curl https://anchor-api.onrender.com/api/ready
# {"status":"ready",...,"database":true,"ai_provider_configured":true}
```

`"database": true` proves Supabase Postgres is reachable through the pooler.

Then in the browser: register, create a course, upload a PDF, and wait for it to
reach **Ready**. That one path exercises the database, the storage bucket and the
embedding provider together. Check **Storage → course-documents** in Supabase and
you should see the object appear under a course-id folder.

---

## Free-tier limits worth knowing

| Limit | Effect on ANCHOR |
|---|---|
| Render free instances sleep when idle | ~30 s cold start on the first request |
| Supabase free projects pause after ~1 week of inactivity | Resume from the dashboard; no data is lost |
| Supabase free storage and database quotas | Generous for a portfolio; a few hundred PDFs is not close |
| Gemini free tier request/token limits | Vary by model and change over time — check AI Studio. ANCHOR's `ai` rate-limit bucket exists to stop a runaway client emptying them |

**Confirm current pricing and terms with each provider before signing up.**
Anything specific written here is a snapshot, not a promise.

---

## What is deliberately not here

- **No Supabase Auth.** Registration, password hashing, and JWT issue/verify stay
  in FastAPI. Moving them would replace a tested, self-contained system with a
  vendor dependency for no gain.
- **No Supabase client library.** The database is SQLAlchemy on `DATABASE_URL`;
  storage is four authenticated HTTP calls. The SDK's value is the Postgres and
  Auth surface, which ANCHOR does not use.
- **No signed URLs.** Downloads stream through FastAPI so the existing ownership
  check stays the only way in. A signed URL is a bearer credential that outlives
  the request and cannot be withdrawn.
- **No background worker.** Document processing runs as a FastAPI background task.
  See the README's limitations: a restart mid-processing leaves a document in
  `processing` until it is reprocessed. For a portfolio that is an acceptable,
  documented trade-off; Redis and Celery would be three moving parts for one.
