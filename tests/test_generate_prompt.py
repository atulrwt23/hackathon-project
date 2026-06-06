"""Smoke tests for prompt assembly. No LLM call is made."""
from __future__ import annotations

from nl2sql.generate import _extract_sql, _format_context, _format_principal
from nl2sql.models import Principal, RetrievedContext


def test_format_context_orders_sections():
    ctx = RetrievedContext(
        schema=[{"content": "TABLE public.users\n  id int"}],
        glossary=[{"content": "MRR: monthly recurring revenue"}],
        table_notes=[{"content": "Note on users: flg=A is active"}],
        examples=[{"content": "Q: foo\nSQL: SELECT 1"}],
    )
    out = _format_context(ctx)
    assert out.index("SCHEMA:") < out.index("TABLE NOTES:")
    assert out.index("TABLE NOTES:") < out.index("GLOSSARY:")
    assert out.index("GLOSSARY:") < out.index("EXAMPLES:")


def test_format_context_skips_empty_sections():
    ctx = RetrievedContext(schema=[{"content": "TABLE x"}])
    out = _format_context(ctx)
    assert "SCHEMA:" in out
    assert "GLOSSARY:" not in out
    assert "EXAMPLES:" not in out


def test_format_principal_includes_required_fields():
    p = Principal(user_id="u_1", roles=["analyst", "admin"], tenant_id="t_9")
    out = _format_principal(p)
    assert "user_id=u_1" in out
    assert "analyst,admin" in out
    assert "tenant_id=t_9" in out


def test_format_principal_handles_missing_optional_fields():
    p = Principal(user_id="u_1")
    out = _format_principal(p)
    assert "roles=-" in out
    assert "tenant_id=-" in out


def test_extract_sql_from_fenced_block():
    text = "Here is the query:\n```sql\nSELECT 1\n```\nDone."
    assert _extract_sql(text) == "SELECT 1"


def test_extract_sql_from_bare_fence():
    text = "```\nSELECT 2\n```"
    assert _extract_sql(text) == "SELECT 2"


def test_extract_sql_no_fence_returns_stripped():
    assert _extract_sql("  SELECT 3  ") == "SELECT 3"
