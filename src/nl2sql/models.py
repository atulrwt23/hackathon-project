from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field


class GlossaryEntry(BaseModel):
    term: str
    definition: str


class TableNote(BaseModel):
    table: str
    note: str


class Example(BaseModel):
    question: str
    sql: str


class BusinessContext(BaseModel):
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    table_notes: list[TableNote] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)


class IngestRequest(BaseModel):
    target_dsn: str = Field(description="Read-only PostgreSQL DSN for the host's database")
    business_context: BusinessContext = Field(default_factory=BusinessContext)


class IngestResponse(BaseModel):
    ingest_id: str
    tables_indexed: int
    glossary_terms_indexed: int
    examples_indexed: int


class Principal(BaseModel):
    """Identity + authorization context supplied by the host on every query.

    The plugin treats this as authoritative; the host must authenticate the
    user before populating it. Used (in future enforcement work) to choose a
    DB role, inject row-level filters, and restrict retrievable schema.
    """

    user_id: str
    roles: list[str] = Field(default_factory=list)
    tenant_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class QueryRequest(BaseModel):
    ingest_id: str
    question: str
    principal: Principal
    max_rows: int | None = Field(default=None, ge=1, le=10_000)
    dry_run: bool = False
    explain: bool = Field(
        default=False, description="If true, ask the LLM for a NL summary of the result"
    )


class QueryResponse(BaseModel):
    sql: str
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool
    explanation: str | None = None
    latency_ms: int


@dataclass
class RetrievedContext:
    """Top-k results from the vector store, grouped by chunk kind."""

    schema: list[dict[str, Any]] = field(default_factory=list)
    glossary: list[dict[str, Any]] = field(default_factory=list)
    table_notes: list[dict[str, Any]] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
