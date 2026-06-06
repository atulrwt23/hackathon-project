from __future__ import annotations

from . import store
from .embeddings import embed_one
from .models import RetrievedContext
from .settings import get_settings


async def retrieve(ingest_id: str, question: str) -> RetrievedContext:
    s = get_settings()
    qvec = await embed_one(question, input_type="query")

    schema = await store.search_chunks(ingest_id, qvec, "schema", s.top_k_schema)
    glossary = await store.search_chunks(ingest_id, qvec, "glossary", s.top_k_glossary)
    table_notes = await store.search_chunks(ingest_id, qvec, "table_note", s.top_k_glossary)
    examples = await store.search_chunks(ingest_id, qvec, "example", s.top_k_examples)

    return RetrievedContext(
        schema=schema,
        glossary=glossary,
        table_notes=table_notes,
        examples=examples,
    )
