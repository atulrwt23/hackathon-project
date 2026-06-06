from __future__ import annotations

import secrets
from typing import Any

import asyncpg

from . import store
from .embeddings import embed_texts
from .models import BusinessContext, IngestRequest, IngestResponse


async def ingest(req: IngestRequest) -> IngestResponse:
    """Introspect the target DB schema, combine with business context, embed, and persist."""
    schema_chunks = await _introspect_schema(req.target_dsn)
    glossary_chunks = _glossary_chunks(req.business_context)
    note_chunks = _table_note_chunks(req.business_context)
    example_chunks = _example_chunks(req.business_context)

    all_chunks = schema_chunks + glossary_chunks + note_chunks + example_chunks
    if not all_chunks:
        raise ValueError("Nothing to ingest: target schema is empty and no business context provided")

    embeddings = await embed_texts(
        [c["content"] for c in all_chunks], input_type="document"
    )

    ingest_id = "ing_" + secrets.token_urlsafe(12)
    await store.write_ingest(ingest_id, req.target_dsn, all_chunks, embeddings)

    return IngestResponse(
        ingest_id=ingest_id,
        tables_indexed=len(schema_chunks),
        glossary_terms_indexed=len(glossary_chunks),
        examples_indexed=len(example_chunks),
    )


async def _introspect_schema(dsn: str) -> list[dict[str, Any]]:
    """Return one chunk per table with a CREATE-TABLE-ish synopsis."""
    conn = await asyncpg.connect(dsn)
    try:
        tables = await conn.fetch(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'information_schema')
            ORDER BY table_schema, table_name
            """
        )
        chunks: list[dict[str, Any]] = []
        for t in tables:
            schema, name = t["table_schema"], t["table_name"]
            cols = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                schema,
                name,
            )
            fks = await conn.fetch(
                """
                SELECT kcu.column_name, ccu.table_schema AS f_schema,
                       ccu.table_name AS f_table, ccu.column_name AS f_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                JOIN information_schema.constraint_column_usage ccu
                  ON ccu.constraint_name = tc.constraint_name
                 AND ccu.table_schema = tc.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = $1 AND tc.table_name = $2
                """,
                schema,
                name,
            )
            content = _format_table(schema, name, cols, fks)
            chunks.append(
                {
                    "kind": "schema",
                    "ref": f"{schema}.{name}",
                    "content": content,
                    "metadata": {"schema": schema, "table": name},
                }
            )
        return chunks
    finally:
        await conn.close()


def _format_table(
    schema: str, name: str, cols: list[asyncpg.Record], fks: list[asyncpg.Record]
) -> str:
    lines = [f"TABLE {schema}.{name}"]
    for c in cols:
        nullable = "NULL" if c["is_nullable"] == "YES" else "NOT NULL"
        default = f" DEFAULT {c['column_default']}" if c["column_default"] else ""
        lines.append(f"  {c['column_name']} {c['data_type']} {nullable}{default}")
    for fk in fks:
        lines.append(
            f"  FK {fk['column_name']} -> {fk['f_schema']}.{fk['f_table']}({fk['f_column']})"
        )
    return "\n".join(lines)


def _glossary_chunks(ctx: BusinessContext) -> list[dict[str, Any]]:
    return [
        {
            "kind": "glossary",
            "ref": g.term,
            "content": f"{g.term}: {g.definition}",
        }
        for g in ctx.glossary
    ]


def _table_note_chunks(ctx: BusinessContext) -> list[dict[str, Any]]:
    return [
        {
            "kind": "table_note",
            "ref": n.table,
            "content": f"Note on {n.table}: {n.note}",
        }
        for n in ctx.table_notes
    ]


def _example_chunks(ctx: BusinessContext) -> list[dict[str, Any]]:
    return [
        {
            "kind": "example",
            "ref": None,
            "content": f"Q: {e.question}\nSQL: {e.sql}",
        }
        for e in ctx.examples
    ]
