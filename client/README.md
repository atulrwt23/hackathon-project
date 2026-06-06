# nl2sql-client

Thin Python client for the `nl2sql` sidecar.

```python
from nl2sql_client import NL2SQLClient

client = NL2SQLClient("http://localhost:8080")
ingest = client.ingest(
    target_dsn="postgresql://readonly:pw@host:5432/app",
    business_context={"glossary": [{"term": "MRR", "definition": "..."}]},
)

result = client.query(
    ingest_id=ingest["ingest_id"],
    question="how many active users signed up last month?",
    principal={"user_id": "u_42", "roles": ["analyst"], "tenant_id": "t_1"},
)
print(result["sql"])
print(result["rows"])
```

An async variant `AsyncNL2SQLClient` is also exposed for asyncio callers.
