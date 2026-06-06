from __future__ import annotations

import httpx

from .settings import get_settings


async def embed_texts(texts: list[str], *, input_type: str = "document") -> list[list[float]]:
    """Embed a batch of texts via Voyage. input_type is 'document' or 'query'."""
    if not texts:
        return []
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.voyageai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {s.voyage_api_key}"},
            json={"input": texts, "model": s.embed_model, "input_type": input_type},
        )
        resp.raise_for_status()
        data = resp.json()["data"]
    return [item["embedding"] for item in data]


async def embed_one(text: str, *, input_type: str = "query") -> list[float]:
    [v] = await embed_texts([text], input_type=input_type)
    return v
