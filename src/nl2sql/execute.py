from __future__ import annotations

import datetime as dt
import decimal
import uuid
from typing import Any

import asyncpg

from .models import Principal
from .settings import get_settings


async def execute_sql(
    target_dsn: str,
    sql: str,
    principal: Principal,
    *,
    dry_run: bool = False,
) -> list[dict[str, Any]]:
    """Execute the (already validated) SQL against the target DB.

    Sets `statement_timeout` defensively. `principal` is accepted now so future
    enforcement (per-role connections, RLS via SET LOCAL) can be added without
    changing the call site.
    """
    s = get_settings()
    conn = await asyncpg.connect(target_dsn)
    try:
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(f"SET statement_timeout = {int(s.statement_timeout_ms)}")
        # Hook for future RLS / per-tenant variables:
        if principal.tenant_id:
            await conn.execute(
                "SELECT set_config('nl2sql.tenant_id', $1, true)", principal.tenant_id
            )
        await conn.execute(
            "SELECT set_config('nl2sql.user_id', $1, true)", principal.user_id
        )

        if dry_run:
            await conn.execute(f"EXPLAIN {sql}")
            return []

        rows = await conn.fetch(sql)
        return [_jsonable(dict(r)) for r in rows]
    finally:
        await conn.close()


def _jsonable(d: dict[str, Any]) -> dict[str, Any]:
    return {k: _coerce(v) for k, v in d.items()}


def _coerce(v: Any) -> Any:
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return str(v)
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, dict):
        return _jsonable(v)
    if isinstance(v, list):
        return [_coerce(x) for x in v]
    return v
