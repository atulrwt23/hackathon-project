# nl2sql

A natural-language-to-SQL sidecar plugin for PostgreSQL. Drop it next to any service; the host calls `/ingest` once with the target DB and business glossary, then calls `/query` with NL questions. The plugin retrieves relevant schema + glossary chunks, asks Claude to generate SQL, validates it (read-only, parseable, row-capped), executes it against a read-only role, and returns rows.

## Quick start

```bash
cp .env.example .env  # fill in keys
docker compose up --build
```

The service listens on `http://localhost:8080`.

### Ingest

```bash
curl -X POST http://localhost:8080/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "target_dsn": "postgresql://readonly:pw@host:5432/app",
    "business_context": {
      "glossary": [
        {"term": "MRR", "definition": "Monthly recurring revenue, summed from subscriptions.amount where status = active"}
      ],
      "table_notes": [
        {"table": "users", "note": "flag column \"flg\"=A means active, I means inactive"}
      ],
      "examples": [
        {"question": "active users this month", "sql": "SELECT count(*) FROM users WHERE flg = '\''A'\''"}
      ]
    }
  }'
# => { "ingest_id": "..." }
```

### Query

```bash
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{
    "ingest_id": "...",
    "question": "how many active users signed up last month?",
    "principal": { "user_id": "u_42", "roles": ["analyst"], "tenant_id": "t_1" }
  }'
```

## Architecture

```
  host service ──HTTP──> nl2sql sidecar ──asyncpg──> target Postgres (read-only role)
                              │
                              ├── pgvector (schema + glossary embeddings)
                              ├── Anthropic API (Claude Sonnet — SQL generation)
                              └── Voyage API (embeddings)
```

See `src/nl2sql/` for module-by-module breakdown. Authorization is hybrid: the host owns authentication; the plugin owns data-level authorization via the `principal` field on every query.
# hackathon-project
# hackathon-project
