from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException

from . import ingest as ingest_mod
from . import store
from .execute import execute_sql
from .generate import generate_sql
from .models import IngestRequest, IngestResponse, QueryRequest, QueryResponse
from .retrieve import retrieve
from .settings import get_settings
from .validate import SQLValidationError, validate_and_cap

log = logging.getLogger("nl2sql")
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="nl2sql", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest_route(req: IngestRequest) -> IngestResponse:
    try:
        return await ingest_mod.ingest(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/query", response_model=QueryResponse)
async def query_route(req: QueryRequest) -> QueryResponse:
    s = get_settings()
    started = time.perf_counter()

    target_dsn = await store.get_target_dsn(req.ingest_id)
    if target_dsn is None:
        raise HTTPException(status_code=404, detail=f"unknown ingest_id: {req.ingest_id}")

    ctx = await retrieve(req.ingest_id, req.question)
    raw_sql = await generate_sql(req.question, ctx, req.principal)

    cap = req.max_rows or s.max_rows
    try:
        sql = validate_and_cap(raw_sql, max_rows=cap)
    except SQLValidationError as e:
        log.warning("sql_rejected", extra={"reason": str(e), "sql": raw_sql})
        raise HTTPException(status_code=422, detail=f"generated SQL rejected: {e}") from e

    rows = await execute_sql(target_dsn, sql, req.principal, dry_run=req.dry_run)
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    log.info(
        "query_served",
        extra={
            "ingest_id": req.ingest_id,
            "user_id": req.principal.user_id,
            "tenant_id": req.principal.tenant_id,
            "row_count": len(rows),
            "latency_ms": elapsed_ms,
        },
    )

    return QueryResponse(
        sql=sql,
        rows=rows,
        row_count=len(rows),
        truncated=len(rows) >= cap,
        latency_ms=elapsed_ms,
    )


def main() -> None:
    import uvicorn

    uvicorn.run("nl2sql.app:app", host="0.0.0.0", port=8080, reload=False)


if __name__ == "__main__":
    main()
