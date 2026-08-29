# ANCHOR

**AI-Powered Adaptive Learning**

ANCHOR turns a student's own course materials into a personalized study workspace.
Upload the lectures, slides and notes for a course, and ANCHOR builds summaries,
quizzes and flashcards from *that* material — answering questions with citations back
to the source document and page, and adapting what it asks next based on which topics
the student has actually mastered.

---

## Project status

> **Phase 6 — Knowledge intelligence and assessment. Complete.**
> A knowledge map derived from the material itself, deterministic knowledge-gap
> detection over it, short-answer questions marked against a rubric with an honest
> "could not mark" verdict, a persisted study guide, and per-student timezones so a
> day starts where the student is.

| Area | Status |
|---|---|
| PostgreSQL + Alembic migrations | **Live** — verified against PostgreSQL 17 |
| pgvector `vector(1536)` chunk storage | **Live** |
| Registration, login, session identity | **Live** — JWT, bcrypt |
| Course CRUD, document upload/delete | **Live** |
| Text extraction (PDF, TXT, MD) | **Live** — page numbers preserved, no OCR |
| Background processing with status transitions | **Live** |
| Semantic search (`/search`) | **Live** — cosine, ownership-scoped |
| AI Tutor (`/ask`) with citations | **Live** |
| AI provider | **Gemini** by default; OpenAI optional |
| Topic extraction from material | **Live** |
| Grounded quiz generation (MCQ) | **Live** — standard and adaptive |
| Mastery tracking and weak-topic detection | **Live** — deterministic |
| Adaptive topic and difficulty selection | **Live** — deterministic |
| Grounded flashcards | **Live** |
| Study recommendations | **Live** — template-built, no model call |
| Effective mastery (calendar decay) | **Live** — derived on read, never stored |
| Mastery history and trends | **Live** — event-sourced |
| Spaced-repetition flashcard review | **Live** — ANCHOR heuristic |
| Exam Readiness and Exam Prep mode | **Live** — optional per course |
| Knowledge map (prerequisite / related) | **Live** — chunk-evidenced, cycle-free |
| Knowledge-gap detection | **Live** — deterministic, no model call |
| Short-answer questions and grading | **Live** — rubric-based, `uncertain` supported |
| Prompt-injection containment on student answers | **Live** — fenced input + output validation |
| Grounded study guide | **Live** — persisted, staleness-tracked |
| Per-student IANA timezone | **Live** — local-day queue, charts and countdown |
| Sample data anywhere in the UI | **None** — every value is real or an empty state |

Two rules this repo follows, and will keep following:

1. **No fake APIs.** An endpoint either works or returns `501` naming the phase that
   will deliver it. Nothing returns invented data dressed up as a real response.
2. **Sample UI is labelled as sample.** Every screen driven by placeholder data
   carries a visible *Interface preview* notice. Sample content carries **no course
   id**, so it can never appear to belong to one of your real courses.

---

## Architecture

```
┌─────────────────────┐
│ React + TypeScript  │  Vite, Tailwind CSS, TanStack Query
└──────────┬──────────┘
           │ HTTP + Bearer token (/api)
┌──────────▼──────────┐
│      FastAPI        │  routes → schemas → services
└──────────┬──────────┘
     ┌─────┴───────────────┐
     ▼                     ▼
┌──────────────┐   ┌────────────────┐
│  PostgreSQL  │   │ StorageService │  local disk today,
│  + pgvector  │   └────────────────┘  object store later
└──────────────┘
```

### The RAG pipeline

Ingestion runs once per upload, in a background task:

```
upload  ─▶  StorageService.save()
            │
            ▼  (background, after the response is sent)
        status: processing
            │
            ▼
     extraction/  ──▶  [ (page 1, text), (page 2, text), … ]   pypdf, no OCR
            │
            ▼
       chunking     ──▶  512-token chunks, 64 overlap, never spanning a page
            │
            ▼
   EmbeddingProvider ──▶ batched provider call ──▶ 1536-float vectors
                         (Gemini: task_type=RETRIEVAL_DOCUMENT, L2-normalised)
            │
            ▼
   document_chunks (content + page_number + embedding) committed WITH status: ready
```

Answering runs per question:

```
question
   │
   ▼  EmbeddingProvider.embed_query()   (Gemini: task_type=RETRIEVAL_QUERY)
query vector
   │
   ▼  RetrievalService — ONE SQL statement:
       document_chunks ⋈ documents ⋈ courses
       WHERE courses.user_id = :user      ← ownership
         AND courses.id      = :course    ← no cross-course leakage
         AND documents.processing_status = 'ready'
       ORDER BY embedding <=> :query      ← cosine distance
       LIMIT :top_k
   │
   ├─ nothing above RAG_MIN_SIMILARITY ─▶ decline, NO model call
   │
   ▼  build_context() within RAG_MAX_CONTEXT_TOKENS
   ▼  LLMProvider.generate()
answer  +  citations built from the retrieved DB rows (never from model text)
```

Reference diagrams: [system architecture](docs/architecture/system-architecture.jpg) ·
[RAG pipeline](docs/architecture/rag-pipeline.png)

### Repository layout

```
anchor/
├── docker-compose.yml        PostgreSQL (pgvector) + API
├── .env.example              docker-compose values (all have defaults)
├── docs/architecture/        Reference diagrams
├── frontend/
│   └── src/
│       ├── components/ui/    Presentational primitives (Button, Dialog, Card, …)
│       ├── components/layout/ App shell, marketing shell, nav, footer
│       ├── features/         Domain UI: auth/, landing/, dashboard/, courses/, workspace/
│       ├── hooks/queries/    TanStack Query hooks — the only callers of services/api
│       ├── pages/            One file per route; composes features
│       ├── routes/           Router config, guards, and the single source of paths
│       ├── services/api/     Typed HTTP client + per-resource modules + DTO mapping
│       ├── mocks/            ALL sample data, quarantined in one folder
│       ├── types/            Domain types shared across features
│       └── lib/              Pure helpers (formatting, class names, token storage)
└── backend/
    ├── alembic/versions/     Committed migrations
    ├── scripts/              evaluate_retrieval.py — retrieval quality harness
    └── app/
        ├── main.py           Application factory
        ├── core/             Settings, security (hashing + JWT), domain exceptions
        ├── db/               Engine, session, declarative base
        ├── models/           SQLAlchemy ORM
        ├── schemas/          Pydantic request/response contracts
        ├── services/         Business logic + StorageService abstraction
        │   └── rag/          extraction/, chunking, embeddings, retrieval,
        │                     generation, processing, rag_service
        ├── api/v1/endpoints/ HTTP layer only
        └── tests/            Run against a real PostgreSQL test database
```

### Why this structure

- **`components/ui/` vs `features/`** is the most important boundary in the frontend.
  `ui/` is generic and knows nothing about learning; `features/` knows about courses
  and mastery. Without that line, a project like this collapses into one enormous
  `Dashboard.tsx`.
- **`hooks/queries/` is the only consumer of `services/api/`.** Components never call
  `fetch`, and never call the API modules directly — they use a query or a mutation,
  so caching and invalidation have exactly one home.
- **`services/` on the backend keeps routes thin.** Retrieval, chunking, embedding and
  LLM orchestration are slow and heavily tested and have nothing to do with HTTP. They
  go behind a service boundary so Phase 3 never touches the route layer.
- **`schemas/` is separate from `models/`** because the API shape is not the table
  shape. `DocumentRead` omits `storage_path`; `UserRead` omits `hashed_password`. The
  response model, not the ORM row, decides what leaves the API.
- **`api/v1/`** is versioned from the start. Health sits at `/api/health`, unversioned,
  because infrastructure probes should not track an API version.

---

## Tech stack

**Frontend** — React 19, TypeScript (strict, `exactOptionalPropertyTypes`), Vite 8,
Tailwind CSS 4, React Router 7, TanStack Query 5, lucide-react, oxlint.

**Backend** — Python 3.13, FastAPI, SQLAlchemy 2.0, Pydantic v2 + pydantic-settings,
Alembic, psycopg 3, PyJWT, bcrypt, pytest, ruff.

**AI** — `google-genai` SDK (**default provider**), `openai` SDK (optional
provider), `pypdf` (extraction), `tiktoken` (chunk sizing), `pgvector` (vector
column type).

**Database** — PostgreSQL 17 with the `vector` extension (`pgvector/pgvector:pg17`).

### AI providers

**Gemini is the default**, for both embeddings and generation, because its free tier
makes the project runnable during development without a billing account. OpenAI
remains fully supported as an optional provider.

```
        RagService  /  DocumentProcessor
                    │
                    ▼
     EmbeddingProvider        LLMProvider          ← ABCs; the pipeline sees only these
        ├── Gemini  (default)    ├── Gemini  (default)
        └── OpenAI  (optional)   └── OpenAI  (optional)
                    │
                    ▼
                 pgvector
```

Selection happens in exactly two functions — `get_embedding_provider()` and
`get_llm_provider()` — each a dict lookup on a config value. There is no
`if provider == "gemini"` anywhere in the services, routes or RAG logic, and no RAG
code is duplicated per provider. The two are chosen **independently**, so embeddings
can stay on one vendor while generation moves to another.

| Setting | Default | Purpose |
|---|---|---|
| `AI_PROVIDER` | `gemini` | Which vendor generates answers |
| `EMBEDDING_PROVIDER` | `gemini` | Which vendor produces vectors |

To switch to OpenAI, set both to `openai`, provide `OPENAI_API_KEY`, and re-embed
(see *Changing the embedding provider* below). Neither key ever reaches the frontend
— all provider calls happen server-side.

#### Models

| Role | Model | Why |
|---|---|---|
| Generation | **`gemini-3.5-flash-lite`** | Grounded Q&A over supplied context needs faithful instruction following, not frontier reasoning: retrieval has already found the passage, and the model's job is to explain it and decline when it does not cover the question. Flash-Lite is the current-generation cost-efficient tier and is well within free-tier reach. `gemini-2.5-flash-lite` is a proven fallback; set `GEMINI_LLM_MODEL` to change it. |
| Embeddings | **`gemini-embedding-001`** | Chosen over the newer `gemini-embedding-2` because **only `-001` supports `task_type`**. ANCHOR embeds stored passages as `RETRIEVAL_DOCUMENT` and questions as `RETRIEVAL_QUERY`, which is exactly the asymmetric case retrieval faces. `gemini-embedding-2` requires the task be described in the prompt instead. |

Both roles use one embedding model for documents and queries — only the task type
differs. Using different models would put the two in incomparable spaces.

### Why not LangChain

The pipeline is five steps, each of which already has a home in this codebase, and
each provider call is about a dozen lines. LangChain would add a large dependency
tree to wrap those.

The deciding factor was ownership. Retrieval must join
`document_chunks → documents → courses → user` **inside the same statement as the
vector search**, so PostgreSQL restricts the candidate set before ranking. LangChain's
PGVector retriever expresses filtering as metadata predicates over its own schema;
getting a three-table ownership join in there means dropping to raw SQL anyway,
having paid for the abstraction and hidden the one query that most needs to be
readable. Direct SDK calls behind our own `EmbeddingProvider` / `LLMProvider` ABCs
keep it plain.

---

## Local setup

Requires Node 20+, Python 3.11+, and Docker (or a PostgreSQL 15+ instance with
pgvector available).

### 1. Database

```bash
docker compose up -d db
```

This runs `pgvector/pgvector:pg17` — stock PostgreSQL 17 plus the `vector` extension —
on port 5432 with database/user/password `anchor`.

Create the test database once:

```bash
docker compose exec db psql -U anchor -d postgres -c "CREATE DATABASE anchor_test"
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

- API: <http://localhost:8000>
- Interactive docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/api/health>

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server proxies `/api` to `127.0.0.1:8000`.

### 4. Create an account

Go to <http://localhost:5173/register>, or:

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"name":"Your Name","email":"you@university.edu","password":"at-least-8-chars"}'
```

Registering signs you in and returns an access token directly — no separate login
call is needed. From the UI you land on the dashboard, where **New course** opens the
create dialog; the course workspace's **Materials** tab accepts uploads.

### Getting a Gemini API key

1. Go to <https://aistudio.google.com/apikey> and create a key.
2. Put it in `backend/.env` as `GEMINI_API_KEY=…` and restart the API.

The Gemini API has a free tier that is suitable for development at this project's
scale. It is **not unlimited and not permanently free**: Google sets per-model
request and token limits that change over time, and the current limits for your
account are shown in AI Studio rather than published as fixed numbers. Free-tier
usage may also be used to improve Google's products — do not upload material you are
not willing to share. A production deployment would need a paid tier or raised quota.

### Processing a document and testing the AI Tutor

1. Put a real key in `backend/.env` (`GEMINI_API_KEY=…`), then restart the API.
2. Sign in, open a course, and upload a **text-based** PDF, TXT or MD file on the
   **Materials** tab. (A scanned PDF will fail — there is no OCR.)
3. Watch the status badge: *Uploaded → Processing → Ready*. The list polls every two
   seconds while anything is pending and stops when everything settles.
4. Open the **AI Tutor** tab. It stays disabled with a clear message until at least
   one document is `Ready`.
5. Ask something the document covers. The answer appears with *document · page*
   citations; the external-link button opens the source file.
6. Ask something it does not cover. The tutor declines rather than inventing an
   answer, and no model call is made.

From the command line:

```bash
TOKEN=...   # from POST /api/v1/auth/login
COURSE=...

curl -X POST localhost:8000/api/v1/courses/$COURSE/search \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"query": "why is the congestion window halved?", "top_k": 5}'

curl -X POST localhost:8000/api/v1/courses/$COURSE/ask \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"question": "Explain the difference between TCP and UDP."}'
```

### Checks

```bash
cd backend && pytest && ruff check . && ruff format --check .
```

```bash
cd frontend && npm run typecheck && npm run lint && npm run build
```

---

## Migrations

Alembic reads the database URL and target metadata from the application itself, so
there is no second connection string to keep in sync.

```bash
cd backend
alembic upgrade head          # apply
alembic downgrade -1          # roll back one
alembic revision --autogenerate -m "description"
alembic check                 # fail if models have drifted from migrations
```

Committed migrations:

| Revision | Description |
|---|---|
| `7dae0b01330c` | Initial schema — `users`, `courses`, `documents`, `study_progress` |
| `9c41f2b7a0e5` | `CREATE EXTENSION vector` |
| `924dcf437b93` | `document_chunks` with `vector(1536)`, plus `documents.processing_error` |
| `c1f83d5a47b2` | Clears chunks for the Gemini provider switch; fixes the `processing_status` column default |
| `546e7760abfa` | Adaptive learning: `topics`, `topic_mastery`, `quizzes`, `quiz_questions`, `quiz_attempts`, `quiz_answers`, `flashcards`. Drops the unused `study_progress` |
| `2cf565e0f3bd` | Retention: `mastery_events`, `flashcard_review_states`, `flashcard_reviews`, `courses.exam_date`, `topic_mastery.flashcard_reviews` |

Both were autogenerated or verified against PostgreSQL 17, so the column types are the
ones the real database produces rather than a guess.

---

## The pgvector decision

ANCHOR stores embeddings in **the same PostgreSQL database** as its relational data,
rather than running a separate vector service such as ChromaDB or Qdrant.

Why:

- **One database to run, back up and migrate.** A portfolio project that needs two
  stateful services to boot is a portfolio project nobody runs.
- **Chunks can be joined to their documents in one query.** Retrieval needs the source
  document name and page for citations. With a separate store, that means a vector
  query followed by a relational lookup and a manual join in Python.
- **Ownership stays enforceable in SQL.** A user must only ever retrieve chunks from
  their own documents. With pgvector that is a `JOIN … WHERE courses.user_id = :user`
  in the same statement as the similarity search — not a filter applied after the fact
  in application code.

The extension is enabled by migration `9c41f2b7a0e5` rather than baked only into the
container image, so any environment that runs migrations can hold vectors.

`document_chunks.embedding` is a `vector(1536)` column in that same database, so a
similarity search and its ownership join are one statement. There is deliberately no
`VECTOR_DB_URL` setting — `DATABASE_URL` covers both.

**Switching the AI provider did not change this.** Gemini replaced the external model
vendor, not the vector store: the pipeline is still
`Document → Extraction → Chunking → Embeddings → pgvector → Retrieval → LLM → Answer`.

---

## Authentication

**Strategy:** stateless JWT bearer tokens.

- `POST /api/v1/auth/register` — creates the account and returns a token
- `POST /api/v1/auth/login` — exchanges credentials for a token
- `GET /api/v1/auth/me` — the signed-in user

**Passwords** are hashed with bcrypt (`bcrypt` directly, not passlib, which is
unmaintained and warns on modern bcrypt releases). Plaintext never reaches the ORM and
never appears in a response — `UserRead` has no password field at all. Passwords over
bcrypt's 72-byte limit are rejected rather than silently truncated, which would make
two different long passwords interchangeable.

**Ownership** derives only from the verified token. `CurrentUser` is the single source
of caller identity and no endpoint accepts a `user_id` from the client. Ownership is
enforced *in the query* (`WHERE user_id = :current_user`), not checked after loading a
row, so there is no code path that reads another user's data at all. Documents are
scoped by joining through their owning course.

Another user's course or document returns **404, not 403** — a resource you do not own
should be indistinguishable from one that does not exist. Login failures return one
message for both "no such account" and "wrong password", so the endpoint cannot be
used to enumerate registered addresses.

**There is no `/logout` endpoint.** Nothing server-side holds a session, so signing out
is the client discarding its token. A route that pretended to revoke something would be
worse than none. Real revocation needs a token denylist — noted as a limitation below.

### Token storage on the client, and the tradeoff

The access token is kept in **`localStorage`**.

- *Cost:* `localStorage` is readable by any script on the origin, so a successful XSS
  can steal a live session.
- *The alternative:* an `httpOnly` cookie is not script-readable, which removes that
  risk — but the SPA and API are separate origins in development, so it pulls in CSRF
  protection, `SameSite`/`credentials` handling and CORS configuration.
- *The call:* for a portfolio application with short-lived tokens carrying nothing but
  a user id and an expiry, `localStorage` is the proportionate choice. For anything
  handling real student records, the cookie route is the right one.

The client drops the token and signs the user out automatically whenever the API
rejects it, and the query cache is cleared on sign-out so one account's data can never
appear under the next.

---

## Documents and storage

**Supported formats: PDF, TXT, Markdown.** Deliberately narrow — every format on this
list must have a working text extractor by Phase 3, so nothing is accepted
speculatively. Maximum upload size is **25 MB** (`MAX_UPLOAD_BYTES`).

Validation on upload:

- the extension must be on the allow-list (the extension decides the type, not the
  browser-supplied content type, which is inconsistent for Markdown)
- a file claiming to be a PDF must actually start with `%PDF-`
- empty files and oversized files are rejected

**Storage** goes through a `StorageService` abstraction. Route handlers never touch the
filesystem; they hold an opaque key. `LocalStorageService` writes under
`backend/storage/documents/` for development, and swapping in S3, R2 or Supabase
Storage means adding one class and changing a factory — no route changes.

Stored filenames are **generated**, never taken from the upload:
`{course_id}/{uuid4}.{ext}`. The user's original name is kept in the database only.
A filename like `../../../etc/passwd.txt` is stored under a generated key and displayed
as `passwd.txt`; the storage layer additionally refuses any resolved path that escapes
its root.

Uploaded files are **gitignored** (`backend/storage/`) — course documents are user data
and must never be committed.

A freshly uploaded document sits at `processing_status = uploaded` and the UI labels it
**"Uploaded — awaiting processing"**. Nothing has read the file. It will not say
"indexed" or "analysed" until Phase 3 makes that true.

---

## Document processing

### Extraction

| Format | Extractor | Pages |
|---|---|---|
| PDF | `pypdf` text layer | Real page numbers, 1-based |
| TXT | direct read | Single page (page 1) |
| MD | direct read, syntax kept | Single page (page 1) |

**There is no OCR.** A scanned or image-only PDF has no text layer, so extraction
yields nothing and the document is marked `failed` with *"No readable text was found
in this PDF. Scanned or image-only documents are not supported."* It is never
silently indexed as empty. Password-protected and corrupt PDFs fail the same way.

Whitespace is normalised — hyphenated line breaks rejoined, column-alignment runs
collapsed, control characters stripped — while paragraph and list structure is kept,
because that structure helps both retrieval and a reader checking the source.

### Chunking

**512 tokens per chunk, 64 tokens of overlap, never spanning a page boundary.**

- *512 tokens* holds a complete idea — a definition plus its elaboration — so a
  retrieved chunk answers rather than teases. Five of them is ~2,560 tokens, leaving
  ample context for the question and instructions.
- *64 tokens overlap (12.5%)* stops a definition that lands on a boundary being split
  from the term it defines.
- *Never spanning a page* is the important one: a chunk covering pages 16–17 could
  not be cited honestly, and citations are the product. The cost is that slide decks
  produce some short chunks; `top_k` absorbs that.

Token counts come from `tiktoken` using the embedding model's own encoding, so "512
tokens" is what the API actually charges and truncates on.

### Statuses

```
uploaded ──▶ processing ──▶ ready
                       └──▶ failed
```

| Status | Meaning |
|---|---|
| `uploaded` | Stored. Nothing has read it. |
| `processing` | Extraction, chunking or embedding in progress. |
| `ready` | Chunks committed. Searchable by the tutor. |
| `failed` | See `processing_error` — a message written for a student. |

Processing runs in a **FastAPI background task** after the response is sent, so a
40-page PDF does not hold the upload request open. Chunks and the `ready` flag land
in the same transaction, so a document can never claim readiness the data does not
back up. A failed document has its partial chunks deleted, so it contributes nothing
to retrieval.

The frontend polls the document list every 2 seconds **only while something is
pending**, and stops once everything is `ready` or `failed`.

---

## Embeddings and retrieval

### Model and dimension

| Setting | Value |
|---|---|
| `EMBEDDING_PROVIDER` | `gemini` |
| `GEMINI_EMBEDDING_MODEL` | `gemini-embedding-001` |
| `EMBEDDING_DIMENSIONS` | **1536** |
| Column | `document_chunks.embedding vector(1536)` |
| Migrations | `924dcf437b93` (column), `c1f83d5a47b2` (provider switch) |

`gemini-embedding-001` emits **3072** dimensions by default and supports Matryoshka
truncation to any width from 128 to 3072. ANCHOR requests **1536** via
`output_dimensionality`, for three reasons:

1. **Quality is identical.** MTEB scores 68.17 at both 1536 and 3072. The larger
   vector buys nothing.
2. **pgvector cannot index beyond 2000 dimensions.** Verified directly:
   `CREATE INDEX … USING hnsw` on a `vector(3072)` column fails with
   *"column cannot have more than 2000 dimensions for hnsw index"*. Choosing 3072
   would permanently foreclose indexing as the corpus grows.
3. It matches the existing column, so no schema change was needed.

> **Normalisation matters here.** Only 3072-wide Gemini output is pre-normalised by
> the API. Any truncated width **must** be L2-normalised before cosine comparison, or
> ranking is silently wrong — no error, just bad results. `GeminiEmbeddingProvider`
> does this itself rather than leaving it to callers, and a test asserts unit length.

**Task types.** Stored passages are embedded as `RETRIEVAL_DOCUMENT`, questions as
`RETRIEVAL_QUERY` — the same model, tuned for each side of an asymmetric match. The
`EmbeddingProvider` interface makes this explicit with separate `embed_documents()`
and `embed_query()` methods. OpenAI has no task-type concept, so its implementation
treats both identically; the distinction stays in the interface because the
better-specified provider needs it.

> **Changing the embedding model or provider is not a config-only change.** Vectors
> from different models are not comparable, whatever their width — mixing them raises
> no error, it just returns nonsense. See below.

Embeddings are **batched** (`EMBEDDING_BATCH_SIZE=64`) — one request per chunk would
be slow and needlessly expensive on a 200-chunk document. Transient failures
(rate limits, timeouts, 5xx) retry three times with exponential backoff; credential
and 4xx failures fail immediately rather than burning retries on something that will
not fix itself. Failures are never swallowed: they mark the document `failed`.

### Changing the embedding provider

Vectors produced by different models occupy different spaces. Existing chunks must be
regenerated, never mixed.

1. Update `EMBEDDING_PROVIDER` (and the relevant key) in `backend/.env`.
2. Confirm the new model can emit `EMBEDDING_DIMENSIONS` exactly. If it cannot, a
   migration altering the `vector(N)` column is required first.
3. Run `alembic upgrade head`. Migration `c1f83d5a47b2` clears `document_chunks` and
   resets every `ready` document to `uploaded`.
4. Re-embed each document:

```bash
curl -X POST localhost:8000/api/v1/documents/$DOCUMENT_ID/reprocess \
  -H "Authorization: Bearer $TOKEN"
```

Uploaded **files are never touched** — only the derived chunks. A document left at
`uploaded` is simply not searchable until reprocessed; nothing is lost.

### Similarity metric: cosine

Retrieval orders by pgvector's `<=>` cosine-distance operator, and reports
`similarity = 1 - distance`.

OpenAI embeddings are unit-normalised, so cosine and inner product rank *identically*.
Cosine is chosen because its distance is bounded in `[0, 2]`, which makes similarity a
stable number in `[-1, 1]` that a threshold can be set against. Inner product has no
such bound, so no fixed threshold would be meaningful.

**No vector index exists.** With a small corpus, PostgreSQL's sequential scan beats an
approximate index, and IVFFlat needs a populated table to build meaningful lists. Add
one when retrieval latency justifies it:

```sql
CREATE INDEX ix_document_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops);
```

`vector_cosine_ops` must match the `<=>` operator the query orders by.

### Ownership — the security boundary

Every retrieval is a **single SQL statement** joining
`document_chunks → documents → courses` with `courses.user_id = :user_id` in the
`WHERE` clause, so PostgreSQL restricts the candidate set *before* ordering by
distance and applying `LIMIT`.

Retrieving a global top-k and filtering other users' rows out in Python would be wrong
twice: it reads data the caller may not see, and it silently returns fewer results
because the budget was spent on rows then discarded. The query also pins
`courses.id = :course_id` — a question asked in course A can never reach course B's
material. Cross-course retrieval is not a Phase 3 feature.

Both properties are covered by tests, including one that puts *identical* documents in
two accounts and asserts each user's search returns only their own chunks.

### No-answer behaviour

Two independent defences, because they fail differently.

**1. A relevance floor, calibrated against real embeddings.** If no retrieved chunk
reaches `RAG_MIN_SIMILARITY` (**0.55** cosine similarity), ANCHOR **does not call the
model at all**. The response is:

> "I couldn't find enough information in your uploaded course materials to answer
> that. Try rephrasing the question, or upload the material that covers it."

with `is_grounded: false` and no citations. This is both an honesty measure — the
alternative is the model answering from general knowledge while the UI implies the
course material supports it — and a cost measure, since the commonest wasted call is
one that had nothing to work with.

The threshold was **measured, not guessed**. Over 20 queries against a real course
PDF with `gemini-embedding-001` at 1536 dimensions:

| | best-match cosine similarity |
|---|---|
| Off-topic questions (n=10) | 0.449 – 0.489 |
| On-topic questions (n=10) | 0.635 – 0.771 |

0.55 sits in that 0.145-wide gap. **This floor is provider-specific**: a lexical
baseline scores unrelated text near 0.0, while Gemini rarely goes below 0.45, so a
value tuned for one is meaningless for the other. Re-measure when changing model.

**2. A relative margin on what reaches the prompt.** `RAG_CITATION_MARGIN` (0.15)
drops chunks that far below the best match before the context is built. Retrieval
returns a *ranked* list, not a relevance verdict — `top_k` is filled with the closest
chunks available, so on a narrow question the tail can be unrelated material that
merely cleared the absolute floor. Observed live: a DNS question against a
congestion-control lecture retrieved the DNS page at 0.727 and three congestion pages
at 0.51–0.55. Without the margin all four were cited, telling the student that
congestion-control pages supported a DNS answer.

**3. The prompt itself**, for the case neither catches: a question adjacent to the
material but not answered by it. Asked "What is the exact TCP retransmission timeout
formula?" against a lecture that discusses retransmission but never gives the formula,
retrieval legitimately returns related pages and the model replies *"The provided
course materials do not contain the TCP retransmission timeout formula."*

### Retrieval evaluation

```bash
cd backend && python scripts/evaluate_retrieval.py
```

Ingests a four-document sample course, runs eight student-phrased questions, and
reports hit@1, hit@3 and MRR.

Measured with `gemini-embedding-001` at 1536 dimensions:

| Metric | Gemini (real) | Lexical fake |
|---|---|---|
| hit@1 | **7/8 (88%)** | 3/8 (38%) |
| hit@3 | **8/8 (100%)** | 6/8 (75%) |
| MRR | **0.938** | 0.552 |

Four of the five deliberately paraphrased questions rank first — including "How does
a computer turn a website name into a numeric address?" against a passage that says
"translates the human readable names people type into the numeric addresses", which
shares almost no distinctive vocabulary. Both out-of-scope questions fall below the
threshold (0.474, 0.487) and are declined.

It uses the **configured real provider** when its key is set and the deterministic
lexical fake otherwise — and prints which one ran. Five of
the questions are deliberately paraphrased ("How does a computer turn a website name
into a numeric address?" against "resolves domain names into IP addresses") because
keyword overlap would prove nothing about semantic retrieval.

---

## The adaptive learning engine

```
              Uploaded materials
                      │
       Extraction + the Phase 3 RAG pipeline
                      │
                   Topics
                      │
   ┌──────────────────┴───────────────────┐
   │  ADAPTIVE ENGINE  (deterministic)    │
   │                                      │
   │  Mastery ──▶ weak-topic detection    │
   │      │                               │
   │      ▼                               │
   │  Topic selection + difficulty mix    │
   └──────────────────┬───────────────────┘
                      │
               RAG retrieval          (ownership-scoped, per topic)
                      │
              Gemini generation       (questions / cards only)
                      │
        Grounded quiz or flashcards
                      │
              Student answers
                      │
               Mastery update ────────────┐
                      │                   │
                      └───────────────────┘
```

The division of labour is the point:

| Decision | Made by |
|---|---|
| Which topics to practise | **ANCHOR** — deterministic priority over the mastery table |
| At what difficulty | **ANCHOR** — a fixed mix per mastery band |
| How mastery changes | **ANCHOR** — a closed-form update, no model |
| What to recommend next | **ANCHOR** — templates over mastery |
| Writing the questions and explanations | **Gemini** |
| Writing the flashcards | **Gemini** |
| Naming the topics found in the material | **Gemini** |

Nothing in the left column calls a model. ANCHOR never asks Gemini *"what should this
student study?"* — the mastery table already answers that exactly, reproducibly and
for free. Gemini's job is to write good grounded questions about a decision already
made.

### Topic extraction

Topics are derived from a spread of the course's **ready** chunks — read in document
and chunk order so the sample follows the syllabus rather than whatever a search
happened to match. They are never derived from the course title: a proposal that
merely restates it is rejected, as are structural non-topics (*Introduction*,
*Summary*, *References*) and near-duplicates, which collapse on a normalised
(lower-cased, whitespace-folded) name enforced by a unique constraint.

**Regeneration is safe by construction.** Mastery rows reference topics, so deleting
a topic would destroy a student's history. A topic the material no longer supports is
**deactivated**: it stops being offered for new quizzes, its mastery stays readable,
and if later uploads bring it back it is reactivated rather than duplicated.

### The mastery formula

On every answered question, for that topic:

```
raw' = raw + (ALPHA · w) · (target − raw)      ALPHA = 0.30
target = 100 if correct else 0
```

`w` weights how *informative* the outcome was, not merely whether it was right:

| | correct | incorrect |
|---|---|---|
| easy | 0.6 (expected) | 1.2 (revealing) |
| medium | 1.0 | 1.0 |
| hard | 1.4 (revealing) | 0.7 (expected) |

This is an exponentially-weighted moving average, so recent answers dominate without
storing history — one float per topic. The displayed score is then damped by how much
evidence supports it:

```
confidence = min(1, questions_attempted / 5)
mastery    = raw · (0.5 + 0.5 · confidence)
```

Worked examples, all covered by tests:

| Situation | raw | displayed |
|---|---|---|
| One lucky easy-correct from zero | 18.0 | **10.8** — not mastery |
| One hard-correct from zero | 42.0 | 25.2 — not Strong |
| Strong (80) then one hard-miss | **63.2** | dented, not destroyed |
| Strong (80) then one easy-miss | 51.2 | a bigger dent, correctly |

**Bands:** Not started (0 attempts) · Needs practice (<40) · Developing (40–70) ·
Strong (≥70). "Not started" is a distinct band, never rendered as 0% — a topic never
practised has not been failed.

`raw_score` and `mastery_score` are both stored so the update stays a pure function of
the previous state. Mastery is credited from the **first** answer to a question: a
re-answer after the correct option has been revealed is not evidence of knowing it.

### Adaptive topic selection

Every topic gets a priority in `[0, 1]`:

```
priority = 0.45 · weakness        (100 − mastery) / 100
         + 0.25 · evidence_need   1 − min(1, attempted / 5)
         + 0.20 · recent_miss     1 if the last answer was wrong
         + 0.10 · staleness       days since practice / 14, capped; 1 if never
```

Weakness dominates, but `evidence_need` is what surfaces a topic with two lucky
answers that *looks* settled, and `recent_miss` reacts to a fresh mistake before the
smoothed score catches up.

**Spaced review.** Priority alone would rarely revisit a Strong topic, so a student's
best material would quietly decay. When a quiz covers 3+ topics *and no Strong topic
won a slot on merit*, the last slot goes to the stalest Strong topic. The "on merit"
check matters: staleness already feeds priority, so a long-unpractised strong topic is
often selected anyway, and substituting would drop a topic that earned its place.

Ties break on topic name, so selection is reproducible.

### Adaptive difficulty

Difficulty is a **mix**, not a switch. Each topic's band selects a target
distribution, allocated by the largest-remainder method:

| Band | easy | medium | hard |
|---|---|---|---|
| Not started | 50% | 50% | 0% |
| Needs practice | 60% | 40% | 0% |
| Developing | 25% | 50% | 25% |
| Strong | 10% | 40% | 50% |

Two consequences are deliberate: a weak student always gets 40% medium questions
rather than easy ones forever, and a strong student always gets 40% medium review
rather than only hard ones.

### How quiz grounding is enforced

Generation is four stages, and the model participates only in the third:

1. **Decide** topics and difficulty — deterministic, or the student's choice.
2. **Retrieve** chunks per topic through the existing ownership-scoped vector search.
   A topic with no supporting chunks above the relevance floor is skipped entirely.
3. **Generate** from *only* those numbered excerpts, via Gemini structured output.
4. **Validate**, then persist — or discard.

Validation rejects anything a JSON schema cannot catch: not exactly four options,
duplicate options, an out-of-range correct index, an empty explanation, an invalid
difficulty, a duplicate question, or **an excerpt number we never supplied**. One
retry, then honest failure. A partially valid quiz is never saved; if nothing
survives, the API answers *"Not enough information in your course materials to
generate this quiz."* rather than falling back to general knowledge.

### Source provenance

Questions and flashcards store **foreign keys** to the `DocumentChunk` and `Document`
they came from — not display strings. The document name and page are read from those
rows at render time, so a renamed file stays correct and a page number can never be
fabricated.

The model is shown numbered excerpts and must cite an excerpt *number*; the
application maps that number back to the chunk it supplied. It is never asked for a
document name or page, so it cannot invent one, and an index we did not supply is
rejected outright.

Pages are omitted rather than faked for TXT and Markdown, which have no real pages.

**Answers are never exposed before submission.** The quiz-taking schema
(`QuizQuestionRead`) has no `correct_index`, `explanation` or `source` field at all —
the shape that carries them is only used in the response to submitting an answer. A
test asserts the raw HTTP body contains neither.

---

## Retention and long-term adaptation

```
              Student evidence
                     │
          Stored mastery ──────────────┐
                     │                 │
            Mastery history            │
                                       ▼
                              Time + confidence
                                       │
                              Effective mastery
                                       │
                 ┌─────────────────────┴─────────────────────┐
                 ▼                                           ▼
          Adaptive practice                            Due reviews
                 │                                           │
           Grounded quiz                            Flashcard review
                 └─────────────────────┬─────────────────────┘
                                       ▼
                                 New evidence
                                       ↺

              Exam date
                  │
        Exam priority engine
                  │
   Effective mastery + coverage + due reviews
                  │
        Exam Readiness / Exam Prep
                  │
       Grounded RAG quiz generation
```

**Gemini generates educational content.** ANCHOR's deterministic backend owns
mastery, the forgetting heuristic, scheduling, adaptation, analytics, exam readiness
and recommendations. Not one of those calls a model.

### Stored vs effective mastery

Two different questions, kept apart:

| | meaning | changes when |
|---|---|---|
| **Stored** (`mastery_score`) | what the student demonstrated | they answer something |
| **Effective** | present estimate, given elapsed time | derived on every read |

There is **no scheduled job that subtracts points**. Decay is a pure function applied
at read time, so a student who returns after two months finds their record intact and
their estimate softened — not their evidence quietly deleted.

### The decay heuristic

```
effective = stored × [ FLOOR + (1 − FLOOR) × 0.5^(days / H) ]      FLOOR = 0.55

H = 30 × (0.5 + 0.5·min(1, evidence/5)) × (0.7 + 0.6·stored/100)
```

`H` is the half-life of the **uncertainty**, not of the knowledge. Two things lengthen
it: more evidence behind the score, and a higher score.

| stored | evidence | idle | H | effective | drop |
|---|---|---|---|---|---|
| 80 | 5 | 1 day | 35.4 | **79.3** | 0.7 |
| 80 | 5 | 30 days | 35.4 | **64.0** | 16.0 |
| 80 | 5 | 60 days | 35.4 | **55.1** | 24.9 |
| 50 | 2 | 30 days | 21.0 | **35.9** | 14.1 |
| 25 | 1 | 30 days | 15.3 | **16.6** | 8.4 |

Well-evidenced strong knowledge halves its uncertainty over ~35 days; a topic answered
once, over ~15. The floor stops decay at 55% of stored: two months of neglect costs a
strong topic about 25 points, enough to prompt review without pretending the student
has forgotten everything.

> **This is a transparent heuristic, not a validated cognitive model.** It is not
> fitted to recall data and predicts nothing about what any individual remembers. Its
> job is to rank topics for review in a way a student can follow.

### Mastery history

`mastery_events` is **event-sourced**: one immutable row when something actually
changes mastery, never a daily snapshot of everything. `effective_mastery_at_event` is
frozen at write time, so changing the decay heuristic later cannot rewrite what the
student was shown last month.

### Spaced repetition — the ANCHOR heuristic

**Not FSRS**, and not described as such. FSRS is a fitted model with published
parameters; implementing an approximation and borrowing the name would misrepresent
it. This is a deterministic interval-multiplier scheme in the SM-2 tradition, small
enough to explain in a paragraph and to test exhaustively.

Ease starts at 2.5, clamped `[1.30, 3.00]`; intervals clamped `[1, 365]` days.

| Rating | Interval | Ease |
|---|---|---|
| **Again** | reset to 0, due in 10 minutes | −0.20, lapse recorded |
| **Hard** | `max(1, round(base × 1.2))` | −0.15 |
| **Good** | 1 → 3 → `round(base × ease)` | — |
| **Easy** | first 3, then `round(base × ease × 1.3)` | +0.15 |

**Overdue credit:** for Good and Easy, `base = min(elapsed, prev × 2)`. Recalling a
card a fortnight late is stronger evidence than recalling it on time; the cap stops
one very late success launching a card years ahead.

| Sequence | Result |
|---|---|
| new → Good | 1 day |
| new → Easy | 3 days |
| Good, Good, Good | 1, 3, 8 days |
| Good → Again | 10 minutes, ease 2.50 → 2.30 |
| interval 10, 30 days overdue → Good | base 20 → 50 days |

The student supplies the rating. Nothing asks a model whether they remembered — the
person who just tried knows better, and it would cost money to ask.

### Do flashcards affect mastery? Yes, at reduced weight

Quiz answers remain the strongest evidence; a flashcard rating is self-reported.

| Rating | Evidence | Weight (quiz medium = 1.0) |
|---|---|---|
| Again | negative | 0.50 |
| Hard | **none** — too ambiguous to score | — |
| Good | positive | 0.35 |
| Easy | positive | 0.45 |

Two safeguards:

1. **Positive flashcard evidence cannot lift `raw_score` above 75.** Grinding Easy can
   reach Strong but never full mastery — only quizzes demonstrate that. Negative
   evidence is never capped: failing a card should always be able to lower a score.
2. **Reviews count 0.4 of a quiz question** toward confidence, and are stored in a
   separate `flashcard_reviews` counter so they never inflate "questions answered".

A quiz-earned score above the ceiling is not clawed back — verified: 92 raw + Easy
stays 92; 92 raw + Again drops to 78.

### Revised adaptive selection

```
priority = 0.50 · weakness          (from EFFECTIVE mastery)
         + 0.25 · evidence_need
         + 0.15 · recent_miss
         + 0.10 · review_pressure   (due cards on this topic)
```

Phase 4's explicit `0.10 · staleness` term is **removed, not reweighted**. Weakness is
now computed from effective mastery, which already contains elapsed time; keeping both
would count time twice and let the two representations drift apart. A test asserts
that passing a different `now` to `priority_for` changes nothing.

### Retention status

Separate from the mastery band, because they answer different questions:

| Status | Meaning |
|---|---|
| Not started · Fresh · Review soon · Due · Overdue | when to look at it again |

A **Strong** topic can be **Due**. Collapsing the two would either hide the review or
imply the student had got worse.

### Course mastery

Three numbers, because one is always misleading:

| Figure | Over |
|---|---|
| `course_mastery` | **all active topics**, never-started counting as 0 |
| `practised_mastery` | started topics only |
| `coverage` | started ÷ total |

Reporting only the first demoralises a student three topics in; reporting only the
second lets someone claim 90% having attempted one topic of ten. The dashboard shows
both, labelled.

### Exam Readiness

```
readiness = 100 × ( 0.60·mean_effective + 0.25·coverage + 0.15·review_currency )

mean_effective  = mean effective mastery over ALL active topics (unstarted = 0)
coverage        = started ÷ active topics
review_currency = 1 − min(1, overdue_cards / max(1, total_cards))
```

Unpractised topics are penalised twice, deliberately — for an exam both depth and
breadth matter. **Nothing practised returns exactly 0**, not a partial score for
having no overdue cards.

| Situation | Readiness |
|---|---|
| 5 of 5 topics at 60% effective | **76** |
| 1 of 5 at 100% effective | **32** |
| Nothing practised | **0** |

> **This is an indicator, not a predicted grade.** It knows nothing about the exam's
> content, weighting or difficulty. It is labelled *Exam Readiness* in the UI and
> never presented as a forecast.

### Exam-mode priority

```
exam_priority = 0.50·weakness + 0.30·coverage_gap + 0.20·recent_miss
```

`coverage_gap` (1 if never practised) replaces `evidence_need`: with days left, the
question is "have I touched this at all?".

Urgency does **not** scale priorities — multiplying every topic by the same factor
reorders nothing. Instead, as the exam nears ANCHOR widens each session (3 → 6 topics
over a 21-day horizon) and, inside 7 days, shifts each topic's difficulty up one band
so questions resemble the paper. Both are bounded, so the final day is not
qualitatively different from the day before. A past exam date falls back to
distant-exam breadth rather than maximum urgency.

### Timezone strategy

Every timestamp is `timestamptz`, stored and compared in **UTC**; naive datetimes
never enter the system, and `ensure_utc` coerces anything that arrives from a driver
or fixture. All wall-clock reads go through **`app/core/clock.now()`** — one seam,
which is what makes the 60-day test possible without monkey-patching `datetime`.

Storage stays UTC. What Phase 6 added is a **per-student IANA timezone**, used for
exactly one thing: deciding where a *day* starts and ends.

**Why a name and not an offset.** `Europe/London` carries the rule that the clock
moves on the last Sunday in March. `UTC+1` carries only today's arithmetic and is
wrong for half the year — and it cannot survive a government changing the rules.
`app/core/timezones.is_valid_timezone` checks candidates against the tz database and
**rejects fixed offsets deliberately**. A timezone is also not a location:
`Europe/London` says when someone's day starts, not where they are, and ANCHOR never
infers it from an IP address. The browser suggests what it already knows; the student
confirms it.

**What actually moves.** Three things, all of which would land on the wrong day for
anyone whose evening falls after midnight UTC:

| Behaviour | Before | Now |
|---|---|---|
| "Due today" | `due_at ≤ now()` | `due_at <` end of the student's local day |
| "Overdue" | due more than 24 h ago | due before the student's local day began |
| Activity chart | bucketed by UTC date | bucketed by local date |
| Exam countdown | days from the UTC date | days from the student's own today |

So opening ANCHOR in the morning shows the whole day's cards at once, rather than
trickling them in as their instants pass.

**DST is handled by construction.** `local_day_bounds` adds one day to the *date* and
re-localises, rather than adding 24 hours to an instant:

```python
start_local = datetime.combine(day, time.min, tzinfo=zone)
end_local   = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
```

Verified in `test_timezones.py` against London 2026: **29 March is 23 hours, 25
October is 25 hours**, and an ordinary June day is 24. A countdown across a DST change
counts calendar days, not multiples of 86 400 seconds.

Existing accounts default to `UTC`, which is what they effectively had before.

---

## Knowledge intelligence

### The knowledge map

Nodes are the course's topics. Edges say either **prerequisite** (directed: learn the
source first) or **related** (undirected: revise together). Both come from what the
material actually says.

**Candidates are found without the model.** Asking about every pair is O(n²) — 25
topics is 300 calls. Instead:

1. retrieve each topic's top chunks with the existing ownership-scoped vector search
2. a pair becomes a candidate only if the two topics **share at least one chunk** —
   the material physically discusses them in the same place
3. rank candidates by shared-chunk count, cap at 30
4. judge **8 pairs per call**, grounded in the shared chunks

Ten topics typically yield ~15 candidates, so **two calls rather than 45**. The real
smoke test on a five-topic course used **2 calls** and rejected 4 of 10 candidates.

Sharing a chunk is evidence of *proximity*, not of a relationship. That judgement is
what the model is for, and the prompt says explicitly that co-occurrence alone is not
enough — "none" is a first-class answer.

**Confidence is a count, not a probability.** `supporting_chunk_count` is the number
of real `DocumentChunk` rows cited for an edge, and the UI says *"supported by N
excerpts"* with the sources listed. A model's stated confidence is unverifiable; three
excerpts the student can click through are not. An edge whose citations do not resolve
to chunks **we supplied for that pair** is discarded rather than stored.

**Cycles are rejected at write time.** "A is a prerequisite of B" and "B is a
prerequisite of A" cannot both hold, and a cycle makes any study order impossible.
Edges are accepted one at a time against a transitive closure of what must come first;
an edge that would close a cycle is dropped. Candidates are processed best-evidenced
first, so the edge that survives a conflict is the better-supported one.

Regeneration replaces the map outright. Unlike topics, an edge carries no student
history — only derived structure — so nothing is lost.

### Knowledge-gap detection — the formula

**Gemini does not decide what the student does not know.** Gap detection is a pure
function in `services/learning/knowledge.py` over mastery and the graph; the endpoint
works with the AI provider entirely unavailable.

Weakness alone is not a gap. A topic the student has not reached is not a failure, and
a weak topic nothing depends on is ordinary revision. A topic is reported only when
**both** hold:

1. effective (retention-adjusted) mastery is below `GAP_THRESHOLD = 60`, and
2. there is evidence of engagement — the topic has been attempted, **or** something
   that depends on it has been.

Rule 2 is what stops a fresh course reporting every topic as a gap on day one.

```
deficit  = (60 - effective) / 60                       in (0, 1]
blocked  = transitive dependents, capped at 4
severity = min(1, deficit × (1 + 0.15 × blocked) + 0.35 if a dependent was attempted)
```

`GAP_THRESHOLD` sits between `NEEDS_PRACTICE_BELOW` (40) and `STRONG_AT_OR_ABOVE`
(70): a *Developing* topic can still be an unmet prerequisite, a *Strong* one cannot.
The `UNMET_BONUS` fires when the student is building on ground that is not solid,
which is the single most useful thing this feature can say.

| Situation | Severity |
|---|---|
| effective 30, nothing depends on it, attempted | 0.50 |
| effective 30, two dependents, neither attempted | 0.65 |
| effective 30, two dependents, one attempted | 1.00 |
| never started, a dependent attempted | 1.00 |
| effective 55, one dependent, none attempted | 0.10 |

Ties break on topic name, so refreshing never reshuffles the list. At most five gaps
are reported — more is a to-do list, not a recommendation. The `reason` string is
assembled from the same facts as the score, so the explanation cannot drift from the
ranking.

### Drawing it — no graph library

`features/knowledge/layout.ts` does a longest-path layering over prerequisite edges
and renders inline SVG. The project already draws its charts that way, and this needs
one deterministic layered layout rather than the force simulation, zoom and
hit-testing a library brings — plus its bundle. If the map ever needs dragging or
panning, that is the point to reconsider, and that file is what gets deleted.

Prerequisites read left to right, so the columns *are* a study order. Below `md` the
graph is replaced by a list with the same ordering and explicit "Builds on …" lines —
a graph squeezed into 375 px is decoration, not information.

---

## Short-answer assessment

Multiple choice is unchanged and remains the default: a request with no `quiz_format`
gets exactly the quiz Phase 4 built. `mixed` converts the **hardest** questions across
the whole quiz to written ones, since that is where explaining beats recognising.

### The grading pipeline

Three layers, because a model judgement that changes a student's record needs
deterministic guards on both sides.

| Layer | What it does |
|---|---|
| 1 — input | Neutralise forged fence markers and control characters; mark an empty answer without spending a call; truncate at 2 000 characters |
| 2 — assessment | One structured call: the rubric, the reference answer, and the student's text **inside a labelled fence** |
| 3 — output | Match results back onto **our** stored concepts; reject a verdict that contradicts them; strip feedback that echoes the prompt |

**Embedding similarity is not the grader, nor a tie-breaker.** It scores topical
overlap, not correctness: *"TCP halves the window on loss"* and *"TCP doubles the
window on loss"* embed almost identically and mean opposite things. Similarity cannot
represent negation, and negation is most of what separates right from wrong here.

### Prompt injection

The student's answer is untrusted content and is handled as such:

- it is placed **last**, inside `-----BEGIN/END STUDENT ANSWER-----`, and the system
  prompt says in advance that the block is data and never instructions;
- **forged fences cannot escape**: `sanitise_student_answer` NFKC-normalises (catching
  lookalike dashes), strips control characters, and neutralises any line that looks
  like a fence marker — without altering the student's actual words;
- **the rubric is ours**: concepts the model invents are discarded, ones it omits count
  as unsatisfied, so the mark scheme shown is always the one the question was written
  with;
- **a self-contradicting verdict is downgraded**: "correct" with nothing satisfied, or
  "incorrect" with everything satisfied, becomes `uncertain` rather than being trusted;
- feedback echoing the fence markers is replaced.

Verified against the live API: three separate injection attempts (plain override,
forged fence, role hijack) were each marked **incorrect with zero concepts satisfied**.

### `uncertain` — and why it is not "wrong"

Rubric marking is fallible, so the grader is given a way to say so. An `uncertain`
verdict:

- changes mastery **not at all** — no reward, no penalty, and no evidence counted, so
  it cannot dilute the confidence damping either;
- is **excluded from the score denominator**, never counted as a miss;
- is shown as *"Not marked"* in neutral styling, with the answer preserved.

A grading **failure** (the provider could not be reached, or returned something
unusable) behaves the same way and stores `grading_state = failed`. The student
answered; a provider outage is not their mistake, and the response is kept so it can
be graded again.

```
correct            1.0
partially_correct  0.5
incorrect          0.0
uncertain          excluded from the denominator
unanswered         counted — skipping is not the same as not being markable
```

### Short-answer mastery weights

Folded into the same `raw' = raw + (α·w)(target − raw)` rule, α = 0.30. A written
answer is stronger evidence than a multiple-choice one — there is nothing to eliminate
and nothing to guess — so correct weights are higher:

| Verdict | target | easy | medium | hard |
|---|---|---|---|---|
| `correct` | 100 | 0.8 | 1.3 | 1.7 |
| `incorrect` | 0 | 1.3 | 1.1 | 0.8 |
| `partially_correct` | 60 | 0.6 | 0.6 | 0.6 |
| `uncertain` | — | no change at all | | |

`partially_correct` pulls towards 60 — above *Needs practice*, below *Strong* — with a
small weight, because a partial judgement is the least certain thing this grader
produces. It can pull a strong score **down**, which is intended: a student sitting at
85 who can only half-answer has overestimated the topic. Partial credit does **not**
count as a correct answer, so the accuracy figure beside mastery stays honest.

One correct medium written answer from zero: `step = 0.30 × 1.3 = 0.39` → raw 39.0,
displayed **23.4** after confidence damping — against 18.0 for the equivalent MCQ, and
still nowhere near *Strong* on one answer.

### What is stored, and what is not

`quiz_answers` keeps the verdict, the per-concept results, the feedback shown to the
student, `graded_at`, and `grader_model`. It stores **no prompt, no excerpts, and no
chain of thought**. Stored reasoning is unverifiable text that reads like a
justification, and keeping it would invite treating it as one.

---

## The study guide

One grounded call per topic, then a single synthesis call over the summaries those
produced — **n + 1 calls for n topics**. One prompt holding the whole course would not
fit a real syllabus, and what it produced would be grounded in whatever survived
truncation.

Only the per-topic calls see excerpts, so only they cite. The overview is written from
summaries and carries no citations, because it has nothing first-hand to cite. A
section whose citations do not resolve to real chunks is dropped rather than shown.

**Mastery is not baked in.** The guide is stored text about the material; the mastery
badges beside each section are overlaid at read time. Freezing a badge into generated
prose would make the guide wrong the moment the student answered a question.

**Staleness.** The guide records a SHA-256 fingerprint of what it was built from: the
ready documents with their chunk counts, and the active topic set. On read that is
compared with the course as it stands. A mismatch marks the guide `stale` — still
readable, clearly labelled, regenerated only on request. It is never silently
regenerated (that spends the student's quota without asking) and never silently served
as current (that would be a lie about provenance). Answering a quiz does **not** make
it stale; uploading a document or re-extracting topics does.

---

## Citations

Citations are built **from the database rows that were put in the prompt** — never
parsed out of the model's text. The system prompt explicitly forbids the model from
writing document names or page numbers, and a test asserts that a model returning
*"See Imaginary Textbook.pdf page 999"* still yields citations naming only the real
document and page.

```json
{
  "answer": "Loss is treated as a signal that the path is saturated…",
  "is_grounded": true,
  "citations": [
    {
      "chunk_id": "…",
      "document_id": "…",
      "document_name": "Lecture 05 — Congestion Control.pdf",
      "page_number": 17,
      "excerpt": "On loss, cwnd is reduced multiplicatively…"
    }
  ]
}
```

Citations describe exactly the excerpts that **fitted** in the context window, not
everything retrieval happened to find. In the UI each renders as
*document name · page N* with the excerpt, and an external-link button that fetches
the original file (with the bearer token, as a blob) and opens it in a new tab.

---

## API cost safeguards

This is a portfolio project, but API calls cost real money.

| Safeguard | Setting |
|---|---|
| Maximum question length | `MAX_QUESTION_CHARS=1000` |
| Bounded `top_k` | `RAG_TOP_K_MAX=20`, rejected as 422 beyond that |
| Bounded context | `RAG_MAX_CONTEXT_TOKENS=4000` |
| Weak matches dropped before the prompt | `RAG_CITATION_MARGIN=0.15` |
| Upload size limit | `MAX_UPLOAD_BYTES` (25 MB) |
| Batched embeddings | `EMBEDDING_BATCH_SIZE=64` |
| No re-embedding | A `ready` document is skipped unless reprocessing is forced |
| No LLM call on empty retrieval | Below `RAG_MIN_SIMILARITY`, the model is never called |
| Mastery, weak-topic detection, recommendations | Pure database reads — **never** a model call |
| Generated quizzes and flashcards are persisted | A page refresh re-reads; it never regenerates |
| Topic extraction is explicit | Runs only when the student asks, not on page load |
| One retry on malformed generation | Then honest failure, rather than burning quota |
| Decay, scheduling, due queue, analytics, readiness, recommendations | **Arithmetic only** — the services have no provider dependency at all |
| Knowledge-map candidates found without the model | Chunk co-occurrence, then **8 pairs per call**, capped at 30 candidates |
| Knowledge-gap detection | **Never** a model call — pure function over mastery and the graph |
| Study guide | **n + 1** calls for n topics, persisted; reading it costs nothing |
| Map and guide are read-only by default | `GET` never generates; only an explicit `POST` spends |
| Empty or trivial written answers | Marked without a grading call |
| Written answers bounded | 2 000 characters, rejected at the schema and truncated at the grader |
| One failed batch does not lose the rest | A map batch or guide section that fails is skipped, not retried in a loop |

There is deliberately no billing or quota system.

---

## Environment variables

Three files, each owned by the thing that reads it. Nothing is hardcoded, and no real
secret is committed.

**`backend/.env`** (from `backend/.env.example`)

| Variable | Purpose |
|---|---|
| `ENVIRONMENT` | `development` \| `staging` \| `production` |
| `DEBUG` | Enables SQL echo in development |
| `DATABASE_URL` | SQLAlchemy URL, psycopg 3 driver |
| `TEST_DATABASE_URL` | Database the test suite runs against |
| `SECRET_KEY` | JWT signing key. Startup **fails** outside development if left at the default |
| `JWT_ALGORITHM` / `ACCESS_TOKEN_TTL_MINUTES` | Token settings (HS256, 12 hours) |
| `UPLOAD_DIR` / `MAX_UPLOAD_BYTES` | Local storage root and size limit |
| `CORS_ORIGINS` | JSON array of allowed browser origins |
| `AI_PROVIDER` / `EMBEDDING_PROVIDER` | `gemini` / `gemini`. Chosen independently |
| `GEMINI_API_KEY` | **Required by default.** Without it uploads still succeed but processing fails with a clear message, and the RAG endpoints answer 503 |
| `GEMINI_LLM_MODEL` / `GEMINI_EMBEDDING_MODEL` | `gemini-3.5-flash-lite` / `gemini-embedding-001` |
| `OPENAI_API_KEY` | Only needed when a provider is set to `openai` |
| `OPENAI_LLM_MODEL` / `OPENAI_EMBEDDING_MODEL` | `gpt-4o-mini` / `text-embedding-3-small` |
| `EMBEDDING_DIMENSIONS` | `1536` — a property of the column; every provider must emit exactly this |
| `EMBEDDING_BATCH_SIZE` | Inputs per embedding request (64) |
| `CHUNK_TOKENS` / `CHUNK_OVERLAP_TOKENS` | `512` / `64` |
| `RAG_TOP_K_DEFAULT` / `RAG_TOP_K_MAX` | `5` / `20` |
| `RAG_MIN_SIMILARITY` | Relevance floor below which the tutor declines (`0.55`, measured) |
| `RAG_CITATION_MARGIN` | Drop chunks this far below the best match (`0.15`) |
| `RAG_MAX_CONTEXT_TOKENS` / `MAX_QUESTION_CHARS` | `4000` / `1000` |
| `EVAL_DATABASE_URL` | Scratch DB for the retrieval harness |

**`frontend/.env`** — `VITE_API_BASE_URL`; leave blank in development.

**`.env`** at the root — PostgreSQL credentials for docker-compose. Every value has a
working default, so `docker compose up` works without creating the file.

---

## API

| Method | Path | Status |
|---|---|---|
| `GET` | `/api/health` | Live · unauthenticated |
| `POST` | `/api/v1/auth/register` | Live · 201, returns a token |
| `POST` | `/api/v1/auth/login` | Live |
| `GET` | `/api/v1/auth/me` | Live |
| `GET` `POST` | `/api/v1/courses` | Live |
| `GET` `PATCH` `DELETE` | `/api/v1/courses/{course_id}` | Live |
| `GET` `POST` | `/api/v1/courses/{course_id}/documents` | Live · POST is multipart |
| `GET` `DELETE` | `/api/v1/documents/{document_id}` | Live |
| `POST` | `/api/v1/documents/{document_id}/reprocess` | Live · rebuild chunks (202) |
| `GET` | `/api/v1/documents/{document_id}/download` | Live · serves the original file |
| `POST` | `/api/v1/courses/{course_id}/search` | Live · semantic search, no generation |
| `POST` | `/api/v1/courses/{course_id}/ask` | Live · grounded answer + citations |
| `GET` | `/api/v1/courses/{id}/topics` | Live |
| `POST` | `/api/v1/courses/{id}/topics/extract` | Live · derives topics from material |
| `GET` `POST` | `/api/v1/courses/{id}/quizzes` | Live · POST generates (201) |
| `GET` | `/api/v1/quizzes/{id}` | Live · taking view, no answers |
| `POST` | `/api/v1/quizzes/{id}/attempts` | Live (201) |
| `POST` | `/api/v1/attempts/{id}/answers` | Live · reveals the result |
| `POST` | `/api/v1/attempts/{id}/complete` | Live · scores the attempt |
| `GET` | `/api/v1/courses/{id}/mastery` | Live · pure DB read |
| `GET` | `/api/v1/courses/{id}/recommendations` | Live · templates, no model |
| `GET` | `/api/v1/courses/{id}/attempts` | Live |
| `GET` `POST` | `/api/v1/courses/{id}/flashcards` | Live · POST generates (201) |
| `GET` | `/api/v1/courses/{id}/mastery/history` | Live · event-sourced, immutable |
| `GET` | `/api/v1/courses/{id}/analytics` | Live · trends from persisted events |
| `GET` | `/api/v1/courses/{id}/flashcards/due` | Live · due / overdue / upcoming |
| `POST` | `/api/v1/flashcards/{id}/reviews` | Live · rate and reschedule (201) |
| `GET` `PUT` | `/api/v1/courses/{id}/exam` | Live · optional exam date + readiness |
| `POST` | `/api/v1/attempts/{id}/short-answers` | Live · grades one written answer |
| `GET` `POST` | `/api/v1/courses/{id}/knowledge-map` | Live · GET never generates; POST costs calls (201) |
| `GET` | `/api/v1/courses/{id}/knowledge-gaps` | Live · deterministic, **no model call** |
| `GET` `POST` | `/api/v1/courses/{id}/study-guide` | Live · GET 404s until built; POST generates (201) |
| `PATCH` | `/api/v1/auth/me/timezone` | Live · IANA identifier only |

Two conventions the Phase 6 routes follow deliberately:

* **Reading never generates.** `GET` on the map or the guide returns what is stored,
  so opening a tab cannot spend the student's quota. Generation is always a `POST`.
* **Written answers get their own route** rather than optional fields on `/answers`.
  The two submissions carry different data and fail in different ways; one shape would
  make "which field is required" depend on a row the client cannot see.

Errors are consistent across every endpoint: a JSON body with a `detail` string
suitable for showing to a user. Database errors are caught and replaced with a generic
message — driver text leaks schema details and connection strings.

| Situation | Status |
|---|---|
| Missing, malformed or expired token | 401 (with `WWW-Authenticate: Bearer`) |
| Wrong email or password | 401, identical message either way |
| Email already registered | 409 |
| Duplicate course code for the same user | 409 |
| Another user's course or document | 404 |
| Unsupported type, empty file, oversized file | 422 |
| Blank/overlong question, `top_k` out of bounds | 422 |
| Blank or overlong written answer, invalid timezone | 422 |
| Not enough material to build a map, guide or quiz | 400 |
| Wrong submission route for the question's format | 400 |
| Provider key not configured | 503 |
| Not built yet | 501, with `planned_phase` |

---

## Data model

```
User ──1:N──▶ Course ──1:N──▶ Document ──1:N──▶ DocumentChunk
 │  (timezone)   │                                (embedding vector(1536))
 │              ├──1:N──▶ Topic ──1:N──▶ TopicMastery ◀──1:N── User
 │              │            ▲  ▲
 │              │            │  └── TopicRelationship ──▶ TopicRelationshipEvidence
 │              │            │           (source, target)          └──▶ DocumentChunk
 │              │            └──── QuizQuestion ──▶ DocumentChunk (provenance)
 │              ├──1:N──▶ Quiz ──1:N──▶ QuizQuestion   (mcq | short_answer)
 │              └──1:N──▶ Flashcard ──▶ DocumentChunk (provenance)
 ├──1:N──▶ QuizAttempt ──1:N──▶ QuizAnswer   (verdict, rubric_results)
 └──1:1 per course──▶ StudyGuide ──1:N──▶ StudyGuideSection
                                              └──▶ StudyGuideSectionSource ──▶ DocumentChunk
```

| Table | Notes |
|---|---|
| `users` | `hashed_password`; unique, case-insensitively matched email |
| `courses` | Unique `(user_id, code)` — two users may share a code, one user may not repeat one |
| `documents` | `filename`, `original_filename`, `file_type`, `file_size`, `storage_path`, `processing_status` |
| `document_chunks` | `chunk_index`, `page_number`, `content`, `token_count`, `embedding vector(1536)`; composite index on `(document_id, chunk_index)` |
| `topics` | Unique `(course_id, normalised_name)`; `is_active` retires rather than deletes |
| `topic_mastery` | Unique `(user_id, topic_id)`; `raw_score` and `mastery_score` both 0–100 |
| `quizzes` / `quiz_questions` | Mode, rationale, difficulty plan; questions carry provenance FKs |
| `quiz_attempts` / `quiz_answers` | One answer per question per attempt; `is_correct` stored, not derived |
| `flashcards` | Per user and course, with provenance FKs |
| `mastery_events` | Immutable history; indexed by (user, topic, time) and (user, course, time) |
| `flashcard_review_states` | Scheduling per **(user, card)** — a card is content, a schedule belongs to a person |
| `flashcard_reviews` | One immutable row per rating given |
| `topic_relationships` | Unique `(source, target, type)`; `CHECK source <> target`; `supporting_chunk_count` is an evidence count, not a model confidence |
| `topic_relationship_evidence` | Unique `(relationship_id, chunk_id)`; real FKs to the chunk and document |
| `study_guides` | Unique `(user_id, course_id)`; `status`, `material_fingerprint` (SHA-256), student-safe `error_message` |
| `study_guide_sections` | One per topic, ordered by `position`; `key_concepts` JSONB |
| `study_guide_section_sources` | Unique `(section_id, chunk_id)` — provenance as rows, not a JSON list, so it shares the same cascade and integrity rules as every other citation |

Phase 6 relaxed four columns to nullable rather than adding a parallel table:
`quiz_questions.options` / `correct_index` (a written question has neither) and
`quiz_answers.selected_index` / `is_correct`. `is_correct` is the interesting one —
an `uncertain` verdict is neither true nor false, and forcing a boolean would lose
exactly the distinction the verdict exists to record. `question_type` defaults to
`MCQ` with a server default, so every pre-existing row is correct without a backfill.

UUID primary keys throughout, timezone-aware timestamps, `ON DELETE CASCADE` on every
foreign key, and a naming convention on the metadata so migrations stay readable.
Deleting a course removes its rows by cascade and its files afterwards — a failed
unlink leaves a harmless orphan file rather than losing a committed delete.

Deleting a document deletes its chunks; deleting a course cascades through documents
to chunks. Both are covered by tests.

---

## Testing

Backend tests run against **a real PostgreSQL database**, not SQLite: the application
depends on PostgreSQL behaviour (UUID columns, timezone-aware timestamps, `ON DELETE
CASCADE`, check constraints) and a SQLite stand-in would verify a different system.

The schema is built by running the **real Alembic migrations**, so every test run also
checks that the committed migrations produce the schema the code expects.

Each test gets a session inside a transaction that is always rolled back
(`join_transaction_mode="create_savepoint"`, so the service layer's own `commit()`
releases a savepoint instead). Uploads go to a per-test temp directory. Tests never
touch the development database or the real storage root.

```bash
cd backend && pytest
```

Point `TEST_DATABASE_URL` elsewhere to use a different database. Coverage includes
registration, duplicate and case-insensitive duplicate registration, login success and
failure, forged and garbage tokens, course CRUD, document upload and validation
(type, magic bytes, empty, oversized), path-traversal filenames, cascade deletion, and
user isolation on every course and document route.

**448 tests pass.** The Phase 6 suites are worth naming, because most of what they
assert is what must *not* happen:

| Suite | What it pins down |
|---|---|
| `test_knowledge_map.py` | Edges need resolvable chunk evidence; `"none"` produces no edge; a prerequisite with no stated direction is dropped; direct, transitive and self cycles are rejected while a shortcut along a chain is not; regeneration replaces rather than duplicates; gap ranking is deterministic and traversal terminates even on a cyclic graph |
| `test_short_answer.py` | The taking view carries no reference answer, rubric or key concepts; five injection payloads cannot escape the fence; a contradictory verdict becomes `uncertain`; an invented concept cannot change the rubric; grading failure stores the answer and leaves mastery alone; re-answering cannot farm mastery; `uncertain` leaves the denominator; MCQ generation is unchanged |
| `test_study_guide.py` | One section per topic with resolvable citations; a section citing nothing real is dropped; new material marks the guide stale while answering a question does not; a deactivated topic's section disappears; reading never generates |
| `test_timezones.py` | Fixed offsets and unknown zones are rejected; an unknown stored zone falls back to UTC rather than raising; London 2026 gives a 23-hour day on 29 March and a 25-hour day on 25 October |
| `test_local_day_semantics.py` | A card due tonight is in this morning's queue; the same instant is "today" in Los Angeles and "tomorrow" in UTC; overdue means before the local day began; two evening answers are one local day, not two; the exam countdown uses the student's own today |

---

## Current limitations

- **No token revocation.** Signing out discards the client's token; that token stays
  valid until it expires. Real revocation needs a denylist or short-lived access
  tokens plus refresh tokens.
- **No password reset or email verification.** Any well-formed email can register.
- **No rate limiting** on login or registration.
- **Uploads are not virus-scanned**, and the PDF check is a magic-byte sniff, not
  validation. It exists to save Phase 3's extractor from unparseable files.
- **Local disk storage only.** The abstraction is in place; no cloud backend is written.
- **Deleting a user is not exposed** through the API, though the schema cascades.
- **Gemini's free tier has limits** on requests and tokens that vary by model and
  change over time; check AI Studio for your account's current figures. Sustained or
  production use needs a paid tier.
- **Chunk sizing uses `cl100k_base`**, which is exact for OpenAI and an approximation
  for Gemini. Harmless at 512 tokens against a much larger input limit, but it means
  chunk boundaries are not tokenizer-exact for Gemini.
- **Switching embedding provider or model invalidates every stored chunk** and
  requires reprocessing. There is no automatic backfill — reprocess is per document.
- **No OCR.** Scanned PDFs fail rather than being processed.
- **No cross-course retrieval.** A question only ever sees one course's material.
- **No conversation memory.** Each question is answered independently; follow-ups
  like "explain that further" have no antecedent.
- **Citations are answer-level, not sentence-level.** They list what the model was
  shown, not which sentence came from where.
- **No vector index**, so retrieval is a sequential scan. Fine at this size; add HNSW
  before it is not.
- **The relevance threshold is a single global constant.** It is calibrated against
  real Gemini embeddings on one sample corpus (20 queries), not tuned per course or
  per embedding model. Changing the embedding provider requires re-measuring it.
- **An adjacent-but-unanswered question still returns citations.** The model
  correctly says the material does not cover it, but `is_grounded` stays true and the
  pages it consulted are listed. That is accurate — those pages were shown to the
  model — but a reader may take citations as support rather than as provenance.
- **The mastery constants are reasoned, not tuned.** ALPHA, the difficulty weights and
  the band thresholds were chosen to satisfy stated properties and are covered by
  exact-value tests; they have not been fitted against real learning outcomes.
- **Adaptive selection considers at most four topics per quiz.**
- **Regenerating topics can strand mastery** on a deactivated topic: the history is
  preserved and readable, but that topic stops appearing in new quizzes.
- **The decay and scheduling constants are reasoned, not fitted.** `FLOOR`, the
  30-day base half-life, the ease deltas and the interval multipliers were chosen to
  satisfy stated properties and are covered by exact-value tests. They have not been
  calibrated against real review outcomes, and the heuristic makes no claim to model
  memory.
- **Effective mastery is not shown in the quiz flow**, only on Progress and Exam Prep,
  to avoid implying a number changed mid-session.
- **Exam Prep does not model the exam.** It knows a date, not a syllabus, weighting or
  format.
- **No review undo.** A misclicked rating cannot be corrected; the next review adjusts
  for it.
- **The knowledge map only relates topics that share retrieved chunks.** Two topics a
  course genuinely connects but never discusses in the same passage will have no edge.
  That is the cost of not paying for O(n²) calls, and it biases the map towards
  relationships the material states in one place.
- **Map generation is capped at 30 candidate pairs.** On a course with many topics the
  weakest-evidenced candidates are never judged, so the map is a subset by design.
- **A knowledge gap is only as good as the graph.** Without a generated map, gap
  detection can still find weak topics but cannot tell *blocking* from *isolated*, and
  `related` edges are ignored by the algorithm entirely — only prerequisites imply
  consequence.
- **The gap constants are reasoned, not fitted.** `GAP_THRESHOLD`, `BLOCKED_WEIGHT`
  and `UNMET_BONUS` were chosen to satisfy stated properties and are covered by
  worked-example tests. They have not been calibrated against real outcomes.
- **Short-answer grading happens in the request path.** One model call per submitted
  answer, so submitting is measurably slower than a multiple-choice answer — 1–40
  seconds against the live API in testing. A queue would be worse: it would show the
  student an answer with no verdict attached.
- **A failed grading cannot be retried from the UI.** The answer and its state are
  stored so a regrade is possible, but no endpoint exposes one; re-answering before
  submission is the only path, and that does not re-credit mastery.
- **The grader is a language model, and it is fallible in both directions.** It can
  mark a correct answer wrong, and `uncertain` exists precisely because it sometimes
  cannot tell. The deterministic layers around it catch self-contradiction and
  injection, not misjudgement. This is not a substitute for a marker.
- **Prompt-injection containment is defence in depth, not a proof.** Fencing,
  sanitising and validating the output raise the cost of an attack and were verified
  against three live attempts; none of that is a guarantee about a future model or a
  cleverer payload. The blast radius is deliberately small: the worst outcome is one
  wrongly-marked answer on the attacker's own account.
- **Study guide generation is synchronous** and costs n + 1 calls, so a large course
  takes a visibly long request. There is no background job and no partial streaming.
- **The timezone affects day boundaries only.** Spaced-repetition intervals are still
  whole days added to the review instant, so a card reviewed at 23:00 comes back at
  23:00 — it simply now appears in the queue from the start of that local day.
- **One timezone per account, not per course.** A student studying across a move or a
  term abroad has to change it themselves; nothing is inferred.

---

## Roadmap

**Phase 1 — Foundations** ✅
Design system · four routes · FastAPI service · database schema · health endpoint.

**Phase 2 — Persistent application foundation** ✅
PostgreSQL with migrations · pgvector enabled · JWT authentication · course CRUD ·
document upload with a storage abstraction · TanStack Query data layer · real
frontend/backend integration.

**Phase 3 — Document processing + RAG** ✅
PDF and text extraction with page provenance · token-aware chunking · OpenAI
embeddings in pgvector · ownership-scoped semantic search · LLM provider abstraction ·
source-grounded answers · citations with document and page · background processing
with real status transitions.

**Phase 4 — Adaptive learning engine** ✅
Topic extraction from course material · grounded MCQ quiz generation · quiz attempts
and scoring · deterministic mastery tracking · weak-topic detection · adaptive topic
and difficulty selection · template-built recommendations · grounded flashcards.

**Phase 5 — Retention and long-term adaptation** ✅
Stored vs effective mastery · calendar decay heuristic · event-sourced mastery
history · spaced-repetition scheduling · due-review engine · retention status ·
progress analytics · Exam Readiness and Exam Prep mode · all sample data removed.

**Phase 6 — Knowledge intelligence and assessment** ✅
Knowledge map from chunk co-occurrence with real excerpt evidence and cycle
rejection · deterministic knowledge-gap detection · short-answer questions with a
layered grading pipeline, an honest `uncertain` verdict and prompt-injection
containment · persisted, staleness-tracked study guide · per-student IANA timezone
with local-day queue, charts and exam countdown.

**Phase 7 — Ideas**
Calibrating the decay, scheduling and gap constants against real outcomes ·
background generation for long study guides · a regrade path for failed markings ·
cross-course knowledge maps · sentence-level citations.
