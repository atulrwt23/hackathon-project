from __future__ import annotations

import json
from typing import Any

import asyncpg

from .settings import get_settings

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        s = get_settings()
        _pool = await asyncpg.create_pool(s.metadata_dsn, min_size=1, max_size=10)
        async with _pool.acquire() as conn:
            await _init_schema(conn, s.embed_dim)
    return _pool


async def _init_schema(conn: asyncpg.Connection, embed_dim: int) -> None:
    await conn.execute("CREATE EXTENSION IF NOT EXISTS vector;")
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ingests (
            ingest_id     TEXT PRIMARY KEY,
            target_dsn    TEXT NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        """
    )
    await conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS chunks (
            id            BIGSERIAL PRIMARY KEY,
            ingest_id     TEXT NOT NULL REFERENCES ingests(ingest_id) ON DELETE CASCADE,
            kind          TEXT NOT NULL,  -- 'schema' | 'glossary' | 'example' | 'table_note'
            ref           TEXT,           -- table name, term, etc.
            content       TEXT NOT NULL,
            metadata      JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding     vector({embed_dim}) NOT NULL
        );
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS chunks_ingest_kind_idx ON chunks (ingest_id, kind);"
    )
    # IVFFlat index is built lazily; for small corpora a seq scan is fine.


async def write_ingest(
    ingest_id: str,
    target_dsn: str,
    chunks: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            INSERT INTO ingests (ingest_id, target_dsn) VALUES ($1, $2)
            ON CONFLICT (ingest_id) DO UPDATE SET target_dsn = EXCLUDED.target_dsn
            """,
            ingest_id,
            target_dsn,
        )
        await conn.execute("DELETE FROM chunks WHERE ingest_id = $1", ingest_id)
        rows = [
            (
                ingest_id,
                c["kind"],
                c.get("ref"),
                c["content"],
                json.dumps(c.get("metadata", {})),
                _vec_literal(emb),
            )
            for c, emb in zip(chunks, embeddings, strict=True)
        ]
        await conn.executemany(
            """
            INSERT INTO chunks (ingest_id, kind, ref, content, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
            """,
            rows,
        )


async def get_target_dsn(ingest_id: str) -> str | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT target_dsn FROM ingests WHERE ingest_id = $1", ingest_id
        )
    return row["target_dsn"] if row else None


async def search_chunks(
    ingest_id: str, embedding: list[float], kind: str, k: int
) -> list[dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kind, ref, content, metadata, embedding <=> $1::vector AS distance
            FROM chunks
            WHERE ingest_id = $2 AND kind = $3
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            _vec_literal(embedding),
            ingest_id,
            kind,
            k,
        )
    return [dict(r) for r in rows]


def _vec_literal(v: list[float]) -> str:
    # pgvector accepts a textual literal of the form '[1,2,3]'
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"
