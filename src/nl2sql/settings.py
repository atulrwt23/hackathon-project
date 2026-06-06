from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="NL2SQL_", env_file=".env", extra="ignore")

    metadata_dsn: str = Field(
        description="DSN for the pgvector-enabled metadata store (schema/glossary embeddings)"
    )
    anthropic_api_key: str
    voyage_api_key: str

    llm_model: str = "claude-sonnet-4-6"
    embed_model: str = "voyage-3"
    embed_dim: int = 1024

    max_rows: int = 1000
    statement_timeout_ms: int = 5000

    top_k_schema: int = 8
    top_k_glossary: int = 6
    top_k_examples: int = 4


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
