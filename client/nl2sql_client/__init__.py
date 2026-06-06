from __future__ import annotations

from typing import Any

import httpx

__all__ = ["NL2SQLClient", "AsyncNL2SQLClient"]


class NL2SQLClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def ingest(
        self, *, target_dsn: str, business_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        r = self._client.post(
            "/ingest",
            json={"target_dsn": target_dsn, "business_context": business_context or {}},
        )
        r.raise_for_status()
        return r.json()

    def query(
        self,
        *,
        ingest_id: str,
        question: str,
        principal: dict[str, Any],
        max_rows: int | None = None,
        dry_run: bool = False,
        explain: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ingest_id": ingest_id,
            "question": question,
            "principal": principal,
            "dry_run": dry_run,
            "explain": explain,
        }
        if max_rows is not None:
            payload["max_rows"] = max_rows
        r = self._client.post("/query", json=payload)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "NL2SQLClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class AsyncNL2SQLClient:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def ingest(
        self, *, target_dsn: str, business_context: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        r = await self._client.post(
            "/ingest",
            json={"target_dsn": target_dsn, "business_context": business_context or {}},
        )
        r.raise_for_status()
        return r.json()

    async def query(
        self,
        *,
        ingest_id: str,
        question: str,
        principal: dict[str, Any],
        max_rows: int | None = None,
        dry_run: bool = False,
        explain: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ingest_id": ingest_id,
            "question": question,
            "principal": principal,
            "dry_run": dry_run,
            "explain": explain,
        }
        if max_rows is not None:
            payload["max_rows"] = max_rows
        r = await self._client.post("/query", json=payload)
        r.raise_for_status()
        return r.json()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncNL2SQLClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
