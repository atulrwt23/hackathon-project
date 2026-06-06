# nl2sql — The Complete Guide

A long-form, story-style walkthrough of what this project is, why it exists, how it was designed, and exactly how to use it.

---

## Part 1 — The Idea

Most companies sit on top of a database that holds all the answers they need: how many users signed up last month, which products are losing money, who the top customers are. But getting those answers usually means writing SQL. SQL is a wonderful language for people who know it, and a wall for everyone else.

The product team has a question. They send it to engineering. Engineering writes a query. They send the numbers back. By the time the team gets the answer, the meeting is over and the question has changed.

**What if anyone could just *ask* the database a question in plain English, and get the answer?**

That's the idea behind `nl2sql`. It is a small service you bolt onto any application. The application sends it a natural-language question — *"how many active users signed up last month?"* — and the service:

1. Figures out what tables and columns are relevant.
2. Writes a SQL query that answers the question.
3. Runs the query safely against the database.
4. Returns the rows.

The host application doesn't need to know SQL. It doesn't need to know the schema. It just needs to know how to ask a question. The hard parts — understanding the schema, understanding the business, writing the SQL, keeping the database safe — all live inside this one plugin.

---

## Part 2 — What We Thought About Before Writing Any Code

Before we wrote a single line, we sat with a few big questions. Each one had several reasonable answers, and the choice we made shaped everything afterwards. This section explains how we thought about them.

### Question 1: Train a model, or guide a smart one?

The obvious first instinct is: *let's train an AI model on our database, so it learns our schema.* That is called **fine-tuning**. It is also a trap. Fine-tuning means:

- Collecting thousands of question/SQL example pairs.
- Spending money to train a custom model.
- Re-training every time the schema changes.
- Hoping the model generalizes to questions you didn't anticipate.

The modern alternative is called **Retrieval-Augmented Generation**, or **RAG** for short. The idea is dead simple: don't bake knowledge *into* the model — *show* the model the knowledge at the moment you need it.

So instead of training, we do this every time a question comes in:

1. Look up the bits of schema and business context that are relevant to the question.
2. Paste them into a prompt: *"Here is the schema. Here is what 'active user' means. Here are some examples. Now answer this question with SQL."*
3. Send that prompt to a smart general-purpose model (Claude).
4. Get the SQL back.

This is dramatically cheaper, schema changes are absorbed by just re-indexing (no retraining), and modern models like Claude are already excellent at SQL when given good context. **We picked RAG.**

### Question 2: How should the host application use this thing?

A few options:

- A **library** that the host imports directly (only works if the host is in Python).
- A **sidecar service** that runs alongside the host and exposes an HTTP API (works for any host, in any language).
- An **MCP server**, which is a way to make tools available to AI agents.

The user said the plugin should be "added to any service." If a Java service or a Node service or a Go service wants to use this, a Python-only library won't help them. So we picked the **sidecar HTTP service**. As a bonus, we shipped a tiny Python client library on top so Python users get a nicer experience.

### Question 3: Who is allowed to see what?

This is the authorization question, and it has two halves:

- **Authentication** — *who is this user?* (login, JWT, OAuth)
- **Authorization** — *what is this user allowed to see?* (row-level security, tenant isolation, role checks)

The host application already knows how to authenticate users — it has login pages, sessions, OAuth providers. We shouldn't reinvent that.

But the plugin is the one touching the data. So the plugin must be the one deciding *what data is allowed out*.

The split we landed on:

| Concern | Owner |
|---|---|
| Who is this user? | Host application |
| What roles do they have? | Host application |
| What rows/columns can they see? | Plugin |
| What read-only DB role to use? | Plugin |

The host tells the plugin *"this question is being asked by user u_42, who is an analyst on tenant t_1"* by passing a **principal** object on every query. The plugin uses that principal to enforce data-level rules. Today, the plumbing is in place — the principal is passed through to the database session as PostgreSQL config variables, which means PostgreSQL's built-in row-level-security policies can already read it. Tomorrow, we will add more enforcement layers on top.

### Question 4: How do we keep this safe?

Letting an AI write SQL and run it against your production database sounds scary. It is, if you do it naively. We layered the safety:

1. **The database connection itself is read-only.** Even if the AI tried to write a `DELETE` statement, the database would refuse it. This is the strongest line of defense — defense in depth, even if everything else fails.
2. **The SQL is parsed and validated before we run it.** We use a SQL parser (`sqlglot`) to check that the statement is a `SELECT`. `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `GRANT` — all rejected outright.
3. **Every query is capped with `LIMIT`.** Even if the AI writes a query that would return ten million rows, we wrap it in an outer `LIMIT 1000` (or whatever you configure). The AI cannot override this — it's wrapped *around* whatever the AI wrote.
4. **Every query has a timeout.** PostgreSQL is told to abort any query that runs longer than 5 seconds. No runaway queries.
5. **Prompt injection is contained.** User questions are wrapped in `<user_question>` tags, and the system prompt explicitly tells the model to treat anything inside those tags as data, never as instructions.
6. **Every query is logged.** Question, generated SQL, row count, latency — all logged for audit.

---

## Part 3 — What We Built

Here is the picture of the running system:

```
   ┌──────────────────┐         ┌────────────────────────────────────┐
   │  Host service    │  HTTP   │   nl2sql sidecar (FastAPI)         │
   │  (any language)  │ ──────► │                                    │
   └──────────────────┘         │   /ingest   /query   /healthz      │
                                │                                    │
                                │   ┌─────────┐   ┌──────────────┐   │
                                │   │ ingest  │   │  retrieve    │   │
                                │   │ module  │   │  module      │   │
                                │   └─────────┘   └──────────────┘   │
                                │   ┌─────────┐   ┌──────────────┐   │
                                │   │ generate│   │  validate    │   │
                                │   │ (Claude)│   │  (sqlglot)   │   │
                                │   └─────────┘   └──────────────┘   │
                                │   ┌─────────────────────────────┐  │
                                │   │  execute (asyncpg)          │  │
                                │   └─────────────────────────────┘  │
                                └──────┬─────────────────────┬───────┘
                                       │                     │
                                       ▼                     ▼
                              ┌────────────────┐   ┌────────────────────┐
                              │  pgvector      │   │  Target Postgres   │
                              │  (metadata)    │   │  (read-only role)  │
                              └────────────────┘   └────────────────────┘
```

### The two phases — ingest and query

The service has two operations. You call them in this order.

**Ingest** is a one-time setup step. You give the service:

- A read-only connection string for your database.
- A "business context" bundle — a glossary of business terms, notes on confusing columns, and a handful of example questions with the SQL that answers them.

The service introspects your database (reads `information_schema` — table names, column names, types, foreign keys), combines that with your business context, embeds everything into numbers using Voyage AI's embedding model, and stores those numbers in a `pgvector`-enabled PostgreSQL database. The service hands you back an `ingest_id` — a short token like `ing_aBc123XyZ`.

You only need to re-ingest when your schema or business context changes.

**Query** is what you call every time a user asks a question. You pass:

- The `ingest_id` from before.
- The user's question, in plain English.
- A **principal** object describing who is asking.

The service:

1. Embeds the question into numbers.
2. Searches the `pgvector` store for the schema chunks, glossary entries, and example queries most similar to the question.
3. Builds a prompt for Claude that includes the system instructions, the retrieved context, the principal, and the user's question (wrapped in safety tags).
4. Claude generates SQL.
5. The validator parses the SQL, rejects anything that isn't a `SELECT`, wraps it in an outer `LIMIT`.
6. The executor runs the SQL against the target database in a read-only transaction with a statement timeout. The principal is set as session variables so row-level-security policies can use them.
7. The rows come back. The service returns them, along with the final SQL it ran and a latency number, so the host application can show them to the user.

### Files in the repo

| Path | What it does |
|---|---|
| `src/nl2sql/app.py` | The FastAPI app — defines `/ingest`, `/query`, `/healthz`, ties everything together |
| `src/nl2sql/models.py` | Pydantic types for requests, responses, principal, retrieved context |
| `src/nl2sql/settings.py` | Reads environment variables (API keys, model names, limits) |
| `src/nl2sql/ingest.py` | Reads your database's structure, accepts business context, embeds everything |
| `src/nl2sql/embeddings.py` | Tiny client for Voyage AI's embedding API |
| `src/nl2sql/store.py` | Reads/writes the pgvector metadata store |
| `src/nl2sql/retrieve.py` | Vector search — finds the most relevant schema/glossary/examples for a question |
| `src/nl2sql/generate.py` | Builds the prompt, calls Claude, extracts the SQL from the response |
| `src/nl2sql/validate.py` | Parses the generated SQL, rejects mutations, enforces the row cap |
| `src/nl2sql/execute.py` | Runs the safe SQL against your database with timeouts and read-only transactions |
| `client/nl2sql_client/__init__.py` | Sync + async Python client for the sidecar |
| `tests/test_validate.py` | Tests proving the validator rejects every form of mutation |
| `tests/test_generate_prompt.py` | Tests for prompt assembly (no LLM call needed) |
| `Dockerfile`, `docker-compose.yml` | Run the whole thing locally with one command |

---

## Part 4 — Features at a Glance

- **Natural-language to SQL** — Ask in English, get rows back.
- **Schema-aware** — Reads your real database structure on ingest.
- **Business-context-aware** — Teaches the AI your domain vocabulary, your weird columns, and your favorite query patterns.
- **Read-only by default** — Cannot mutate data, period.
- **SQL validated before execution** — Generated SQL is parsed and checked.
- **Row-capped** — Every query is wrapped in `LIMIT`, configurable per request.
- **Timeout-protected** — Slow queries are killed automatically.
- **Principal-aware** — Caller identity flows from host to plugin to database session.
- **Prompt-injection resistant** — User questions are isolated inside delimiters.
- **Audit-logged** — Every query is recorded with question, SQL, row count, latency.
- **Polyglot-friendly** — Any language can call the HTTP API.
- **Ergonomic Python client** — Sync and async clients available out of the box.
- **Self-contained** — Runs as a single container; the only external services are Anthropic and Voyage.

---

## Part 5 — How to Use It (with examples)

This part walks you through using the plugin end-to-end. Imagine you run an e-commerce company. Your database has tables like `users`, `orders`, and `products`. You want non-technical teammates to ask questions like *"how many orders did we ship last week?"* without bothering engineering.

### Step 1 — Prepare your environment

You need:

- Docker installed.
- An **Anthropic API key** (https://console.anthropic.com).
- A **Voyage AI API key** (https://www.voyageai.com).
- A read-only PostgreSQL user on the database you want to query.

Make sure your read-only user really is read-only:

```sql
CREATE ROLE nl2sql_reader LOGIN PASSWORD 'a-strong-password';
GRANT CONNECT ON DATABASE shop TO nl2sql_reader;
GRANT USAGE ON SCHEMA public TO nl2sql_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO nl2sql_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO nl2sql_reader;
```

### Step 2 — Start the service

In the project directory:

```bash
cp .env.example .env
# edit .env, fill in your two API keys
docker compose up --build
```

After a few seconds the service is listening on `http://localhost:8080`. You can verify:

```bash
curl http://localhost:8080/healthz
# {"status":"ok"}
```

### Step 3 — Ingest your schema and business context

This is the "teach the plugin about your business" step. You only do it once (and again when things change).

```bash
curl -X POST http://localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "target_dsn": "postgresql://nl2sql_reader:a-strong-password@db.example.com:5432/shop",
    "business_context": {
      "glossary": [
        {"term": "active user", "definition": "A user whose users.flg column is the string A"},
        {"term": "MRR", "definition": "Monthly recurring revenue: sum of subscriptions.amount where status = active"},
        {"term": "last month", "definition": "The previous calendar month, not the trailing 30 days"}
      ],
      "table_notes": [
        {"table": "users", "note": "The flg column is single-character: A=active, I=inactive, S=suspended"},
        {"table": "orders", "note": "The status column has values: pending, paid, shipped, refunded, cancelled. Only paid and shipped count as real revenue."}
      ],
      "examples": [
        {
          "question": "how many active users do we have?",
          "sql": "SELECT count(*) FROM users WHERE flg = '\''A'\''"
        },
        {
          "question": "revenue last month",
          "sql": "SELECT sum(amount) FROM orders WHERE status IN ('\''paid'\'','\''shipped'\'') AND created_at >= date_trunc('\''month'\'', current_date - interval '\''1 month'\'') AND created_at < date_trunc('\''month'\'', current_date)"
        }
      ]
    }
  }'
```

Response:

```json
{
  "ingest_id": "ing_aBc123XyZ456",
  "tables_indexed": 17,
  "glossary_terms_indexed": 3,
  "examples_indexed": 2
}
```

**Save the `ingest_id`** — your application will need it on every query.

**Tip on writing good business context:**

- The glossary is for *domain words*. If your company says "MRR" or "GMV" or "shipped", define it.
- Table notes are for *weird columns*. If a column called `flg` actually means user status, say so.
- Examples are gold. A handful of good question-to-SQL examples teaches the model your query style faster than any other input. Three to ten examples is plenty.

### Step 4 — Ask a question

```bash
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{
    "ingest_id": "ing_aBc123XyZ456",
    "question": "how many active users signed up last month?",
    "principal": {
      "user_id": "u_42",
      "roles": ["analyst"],
      "tenant_id": "t_1"
    }
  }'
```

Response:

```json
{
  "sql": "SELECT * FROM (SELECT count(*) FROM users WHERE flg = 'A' AND created_at >= date_trunc('month', current_date - interval '1 month') AND created_at < date_trunc('month', current_date)) AS nl2sql_capped LIMIT 1000",
  "rows": [{"count": 1247}],
  "row_count": 1,
  "truncated": false,
  "latency_ms": 812
}
```

Things worth noticing:

- The plugin understood "active users" by combining the glossary (`flg = 'A'`) with the `users` table structure.
- It understood "last month" via the glossary entry.
- The SQL is wrapped in an outer `LIMIT 1000` — even though this query only returns one row, the cap is always applied.
- The `latency_ms` includes the embedding call, the Claude call, the validation, and the database round-trip.

### Step 5 — Using the Python client

If your application is in Python, you can skip the raw HTTP calls.

```python
from nl2sql_client import NL2SQLClient

with NL2SQLClient("http://localhost:8080") as client:
    ingest = client.ingest(
        target_dsn="postgresql://nl2sql_reader:pw@db.example.com:5432/shop",
        business_context={
            "glossary": [
                {"term": "active user", "definition": "users.flg = 'A'"},
            ],
            "examples": [
                {"question": "active users", "sql": "SELECT count(*) FROM users WHERE flg = 'A'"},
            ],
        },
    )

    result = client.query(
        ingest_id=ingest["ingest_id"],
        question="orders shipped yesterday by region",
        principal={"user_id": "u_42", "roles": ["analyst"], "tenant_id": "t_1"},
    )

    print("SQL:", result["sql"])
    for row in result["rows"]:
        print(row)
```

There is also `AsyncNL2SQLClient` for asyncio applications.

### Step 6 — Passing the principal correctly

The principal is how the host tells the plugin *who is asking*. It travels with every query and reaches the database session.

A typical Flask/FastAPI integration looks like:

```python
@app.post("/ask")
def ask(req: AskRequest, current_user: User = Depends(authenticate)):
    return nl2sql.query(
        ingest_id=INGEST_ID,
        question=req.question,
        principal={
            "user_id": current_user.id,
            "roles": current_user.roles,
            "tenant_id": current_user.tenant_id,
            "attributes": {"department": current_user.department},
        },
    )
```

Inside the executor, the plugin sets PostgreSQL session variables:

```
SELECT set_config('nl2sql.user_id', 'u_42', true);
SELECT set_config('nl2sql.tenant_id', 't_1', true);
```

If you have row-level security policies in PostgreSQL, they can read these:

```sql
CREATE POLICY tenant_isolation ON orders
  USING (tenant_id = current_setting('nl2sql.tenant_id'));
```

Now even if Claude writes a query that forgets to filter by tenant, the database itself only returns rows for the right tenant. **This is the foundation for safe multi-tenant use.**

### Step 7 — Dry-run mode

If you want to *see* the SQL without running it (useful for an "explain what this would do" feature):

```json
{
  "ingest_id": "ing_aBc123XyZ456",
  "question": "delete all orders",
  "principal": { "user_id": "u_42", "roles": ["analyst"] },
  "dry_run": true
}
```

This would run a PostgreSQL `EXPLAIN` only — except in this case the validator would reject the SQL outright because "delete" would force the model to emit a `DELETE`, which the validator refuses. You'd see:

```json
{ "detail": "generated SQL rejected: forbidden statement type: Delete" }
```

That's the safety system working.

---

## Part 6 — Tuning Knobs

All configuration is via environment variables (prefix `NL2SQL_`):

| Variable | Default | What it does |
|---|---|---|
| `NL2SQL_METADATA_DSN` | *required* | Postgres+pgvector store for embeddings |
| `NL2SQL_ANTHROPIC_API_KEY` | *required* | Anthropic API key |
| `NL2SQL_VOYAGE_API_KEY` | *required* | Voyage embedding API key |
| `NL2SQL_LLM_MODEL` | `claude-sonnet-4-6` | Which Claude model to use |
| `NL2SQL_EMBED_MODEL` | `voyage-3` | Which embedding model to use |
| `NL2SQL_EMBED_DIM` | `1024` | Embedding dimensionality (matches the model) |
| `NL2SQL_MAX_ROWS` | `1000` | Hard cap on rows returned per query |
| `NL2SQL_STATEMENT_TIMEOUT_MS` | `5000` | PostgreSQL `statement_timeout` per query |
| `NL2SQL_TOP_K_SCHEMA` | `8` | How many schema tables to retrieve per question |
| `NL2SQL_TOP_K_GLOSSARY` | `6` | How many glossary entries to retrieve |
| `NL2SQL_TOP_K_EXAMPLES` | `4` | How many few-shot examples to retrieve |

Bigger `top_k` values mean more context to the model, which costs more tokens but can give better SQL on complex schemas. Smaller values are faster and cheaper. The defaults are sensible for a schema with ~50 tables.

---

## Part 7 — What's Done vs. What's Next

### Done

- HTTP service with `/ingest` and `/query`.
- Schema introspection for PostgreSQL.
- Business context: glossary, table notes, few-shot examples.
- Vector storage with pgvector.
- Retrieval, prompt assembly, Claude generation with prompt caching.
- SQL validation (parser-based, statement-type allowlist, outer-`LIMIT` wrap).
- Safe execution (read-only transaction, statement timeout, principal-aware session vars).
- Python client (sync + async).
- Dockerfile + Docker Compose.
- 23 unit tests covering the validator and prompt assembly.

### Not yet done — natural next steps

- **Full authorization enforcement** — today the principal flows to the database session, so RLS policies can use it. The richer pieces (retrieval-time table allowlists per role, per-role connection pools, mandatory `WHERE` injection at generation time) are next.
- **Result explanation** — a second LLM call that summarizes the rows in natural language. The `explain: true` flag exists in the request schema but isn't wired up yet.
- **Integration tests** — end-to-end tests using a containerized Postgres with a fixture schema.
- **Observability** — Prometheus metrics for latency, cache hit rate, validator rejection rate, token spend.
- **Other databases** — MySQL, SQLite, Snowflake. The architecture supports them; the introspector and dialect setting need adapters.
- **Caching of question→SQL pairs** — if the same question is asked twice, return the cached SQL without calling the LLM again.

---

## Part 8 — A Mental Model You Can Carry

The whole project boils down to a single sentence:

> **Ingest** stores knowledge about your database. **Query** retrieves the right knowledge, asks Claude to write SQL with that knowledge, validates the SQL, and runs it safely.

Everything else — the validator, the principal, the row cap, the statement timeout, the prompt caching — is just *making that sentence true and safe in production*.

If you remember nothing else from this document, remember this:

1. **The model is not the system.** The model is one component. The safety boundary lives in the validator, the read-only role, and the row cap.
2. **Context is the magic.** The model is only as good as the schema and business notes you feed it. Spend your effort there.
3. **The principal is the seam between host and plugin.** Get it right early, because retrofitting authorization later is painful.

That's the project.
