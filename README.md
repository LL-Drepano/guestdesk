# guestdesk

A backend service that receives guest messages, queues them, and processes them
concurrently in the background — with duplicate deliveries blocked at the database
level, and a live cloud deployment. Built with FastAPI, PostgreSQL, and a
Postgres-backed job queue; deployed on Render with managed Postgres on Neon.

> **In one sentence:** a guest message arrives at an API endpoint, gets validated and
> stored exactly once, and a separate worker picks it up and processes it — with the
> whole thing running live in the cloud.

![Scenario canvas](images_guestdesk/worker1.png)
![Scenario canvas](images_guestdesk/worker2.png)

---
## Highlights

- **Handles each message exactly once, enforced by the database.** Duplicate deliveries
  are blocked by two independent uniqueness rules in PostgreSQL, so a repeated message
  physically can't be stored twice. The guarantee is built into the storage itself, which
  means application code has no way to let a duplicate slip through even under heavy load.
- **Processes the queue with multiple workers, collision-free.** Using PostgreSQL's
  row-locking (`SKIP LOCKED`), two workers drain the same queue in parallel while each job
  goes to exactly one of them — demonstrated live with two workers running side by side.
- **Relational database design (SQL / PostgreSQL) doing real work.** Data modelled as
  tables with enforced rules — uniqueness for deduplication, a constrained status for a
  valid job lifecycle — so whole categories of bad data are refused at the point of
  writing. Structure managed through versioned migrations that any environment can replay
  to rebuild the schema identically.
- **Deployed live in the cloud, and runnable locally.** Running on Render with managed
  PostgreSQL on Neon, database migrations applied automatically on deploy, secrets kept in
  the platform's settings, and auto-redeploy on every push.

## What this is

This is the **reliability spine** of a larger guest-operations system, built first and on
purpose. The hard part of a service like this isn't the AI that eventually reads the
messages; it's making the plumbing underneath correct: accepting work without blocking,
handling each message exactly once, and letting more than one worker drain the queue
without them colliding.

I built this layer to completion and stopped there deliberately. The stages that sit on
top of it (listed near the bottom) are designed but intentionally unbuilt. I wanted to
prove I can build the part that has to stay correct under load, which is the part most
portfolio projects skip. And plainly: this scope is also what I set out to demonstrate
for my job search — real database design, a managed cloud deployment, and safe
concurrent processing. Stopping at a complete, coherent foundation made more sense than
half-building the entire system.

---

## The problem

A service that processes incoming messages has three constraints that are easy to get
wrong and painful to discover once it's live:

- **The response has to be fast.** The real work — eventually, reading a message with an
  LLM — is slow. Running it inside the request means the caller waits seconds, the API
  can only handle a few requests at a time, and a processing failure shows up as a failed
  web request.
- **The same message must be handled only once.** Message providers deliver
  at-least-once, so duplicates are normal. Handling one twice means a guest gets replied
  to, billed, or actioned twice.
- **Processing has to survive scale and failure.** Multiple workers should be able to
  drain the queue at once while still handling each job exactly once.

The service is built around these three constraints from the first line.

---

## What I built

A message-processing spine, in the standard producer/consumer shape:

1. **Ingest** — a FastAPI endpoint receives a guest message as JSON, validates it, and
   stores it exactly once, creating a job to process it.
2. **Deduplicate** — repeated messages are blocked by the database itself, using two
   independent fingerprints, before any processing happens.
3. **Queue** — the job waits in a database table marked `pending`. The `jobs` table acts
   as the queue; there's no separate queue service to run.
4. **Process** — a separate worker program claims pending jobs one at a time, does the
   work, and marks them `done`, staying safe even with several workers running together.

**Stack:** FastAPI · PostgreSQL 16 · SQLAlchemy 2 · Alembic (database migrations) ·
psycopg 3 · Docker Compose (local) · Render (app) + Neon (managed Postgres) for the live
deployment.

![The live API documentation page](images_guestdesk/API_docs.png)

---

## How it works

### 1. Ingest — validate at the door

The entry point is a FastAPI `POST /ingest` endpoint. Incoming JSON is checked against a
strict schema before anything reaches the database, so a malformed sender or an oversized
body is turned away immediately with a clear error. This is the first of two safety
layers: validation handles bad input politely at the door, and the database rules behind
it are the final backstop.

### 2. Deduplicate — the guarantee lives in the database

This is the core of the reliability story.

The tempting way to prevent duplicates is to look before storing: check whether the
message already exists, and if it doesn't, insert it. That approach has a hidden flaw —
two identical messages arriving at the same instant can both pass the check before either
one is stored, and a duplicate slips through. The check and the store happen as two
separate steps, so under load they can overlap.

Instead, the service just tries to store the message and lets the database enforce
uniqueness. The `messages` table carries two independent uniqueness rules — one on an ID
supplied by the message provider, one on a fingerprint computed from the message's own
content. When a repeat arrives, the database refuses it, and the endpoint catches that
refusal and responds calmly with "already received." Because the database enforces this
at the moment of writing, two simultaneous attempts end with one stored and the other
turned away. The guarantee is built into the storage itself, so no bug in the application
code can let a duplicate through.

> Two fingerprints, both on purpose: the provider's ID catches the common case, where the
> provider redelivers the same message. The content fingerprint catches the sneakier one,
> where the same message arrives wearing a different ID — a resend or a forward. A repeat
> is blocked if it matches on either.

![The database refusing a duplicate](images_guestdesk/duplicateresponse.png)

### 3. Queue — the database is the queue

The job waits in the `jobs` table with a status that the database restricts to a fixed
set of allowed values (`pending`, `processing`, `done`, `failed`, `dead`) — an illegal
status physically can't be written. There's no Redis or RabbitMQ here; PostgreSQL handles
this comfortably at this scale, which means one fewer service to run, pay for, and deploy.
A dedicated queue becomes worth it at high throughput or when you need features Postgres
lacks — at this scale it would be the wrong complexity.

### 4. Process — a separate worker, and safe concurrency

The worker is a **separate program** from the API, which is the whole reason the API can
answer in milliseconds while the real work takes seconds. Its life is a loop: claim a
pending job, mark it `processing`, do the work, mark it `done`.

The claim is where the interesting problem is. Run two workers at once to go faster, and
both poll the same table, both can see the same pending job, and both try to grab it — so
a guest gets processed twice. It's the same shape as the duplicate-message problem, one
level up.

The fix follows the same philosophy: let the database enforce it. The worker claims a job
using PostgreSQL's `SELECT ... FOR UPDATE SKIP LOCKED` — it finds a pending job and locks
that row so no other worker can take it, and any other worker looking at the same instant
simply skips the locked row and grabs a different job. The lock is held only for the
brief moment of claiming, not while the slow work runs, so one worker's job never holds
up another's.

I proved this by running two workers at once against the same queue. They split the jobs
between them cleanly — every job claimed by exactly one worker, and no job ever appearing
in both — which is the screenshot at the top of this README.

> **On the current build:** the "work" itself is a placeholder (a short pause) standing in
> for the LLM classification and drafting that Stage 2 adds. The concurrency, queueing,
> and deduplication are real and complete; the intelligence on top is designed and not
> yet built (see below).

---

## Live deployment

The service runs live, not only on my laptop:

- **App on Render** (free tier), with **managed Postgres on Neon** (permanent free tier),
  chosen over Render's own database because Neon's free database doesn't expire.
- **Migrations run on deploy** — the database structure is created in the cloud
  automatically by the start command, so the deployed schema matches local exactly.
- **Secrets stay out of the code** — the database address lives in the platform's
  settings, never in the repository. Deploying took zero code changes, because the app
  reads its configuration from the environment; the code running in the cloud is
  identical to the code running locally.
- **Auto-redeploys on every push** to `main`, a small slice of continuous deployment.

The `/health` endpoint returns a 503 error (rather than a 200 success) when the database
is unreachable, so the hosting platform can tell the difference between "the app is
running" and "the app can actually do its job." A health check that always returned
success would report everything as fine straight through an outage.

---

## Design decisions

- **Duplicate-safety enforced by the database.** Two uniqueness rules in the database
  instead of a check in the application code, because the database enforces it at the
  moment of writing and can't be tricked by two requests arriving at once.
- **`SKIP LOCKED` for the worker claim.** Two workers can't grab the same job, because the
  database hands the locked row to exactly one of them. The correctness guarantee lives in
  the layer that can't be raced.
- **Postgres as the queue.** One fewer moving part than a dedicated queue service, and the
  right call at this scale, with a clear line for when I'd change it.
- **Worker as a separate program.** Keeps fast acceptance and slow work apart, and it's
  ready to deploy as its own service with no code change.
- **Fail fast on a dead dependency.** An explicit connection timeout on the database, so
  an outage surfaces in seconds instead of hanging a worker indefinitely and dragging the
  whole system down with it.
- **Migrations instead of hand-edited structure.** Every change to the database is a
  versioned, reversible migration checked into Git, so any copy — local, CI, or cloud —
  is rebuilt identically.

---

## Designed but not built (deliberately)

This repository is the reliability foundation. The full guest-operations system sits on
top of it, and these stages are designed and intentionally unbuilt — the load-bearing
part came first:

- **Intelligence:** LLM classification of each message (intent, urgency) with structured
  output, and a drafted reply grounded in real property documents using **RAG** —
  retrieval based on meaning rather than keyword matching.
- **Reliability hardening:** automatic retries with backoff and a dead-letter path for
  jobs that exhaust them, plus recovery of jobs left stranded by a killed worker.
- **Verification:** an automated test suite run against a throwaway database, and a small
  evaluation set that measures classification quality, both run in CI.

I stopped at a complete, coherent spine rather than half-build the whole system.

---

## Key techniques

- Building a producer/consumer message-processing service, where the API accepts requests
  quickly and a separate worker handles the slow work in the background.
- **Relational database design (SQL / PostgreSQL):** modelling the data as tables with
  enforced rules — uniqueness constraints that make duplicate messages impossible, and a
  constraint that limits each job to a fixed set of valid states — so that whole
  categories of bad data can't be stored in the first place.
- **Safe concurrency:** using PostgreSQL's row-locking (`SELECT ... FOR UPDATE SKIP
  LOCKED`) so multiple workers can drain one queue at the same time without ever handling
  the same job twice — demonstrated with two workers running in parallel.
- **A real cloud deployment:** a containerized local setup, managed cloud PostgreSQL,
  database migrations that run automatically on deploy, configuration and secrets kept
  out of the code, and health checks that report the true state of the service's
  dependencies.
