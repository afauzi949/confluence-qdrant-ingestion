from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    confluence_base_url: str
    confluence_email: str
    confluence_api_token: str
    confluence_space_key: str
    confluence_space_id: str
    modified_window_days: int
    search_page_limit: int
    trashed_page_limit: int

    page_type: str

    convert_api_url: str

    chunk_mode: str
    chunk_api_url: str
    chunk_size: int
    chunk_overlap: int

    embedding_api_url: str
    embedding_api_key: str
    embedding_model: str

    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection: str
    qdrant_sparse_model: str

    schedule_hour: int
    schedule_minute: int
    schedule_timezone: str
    run_on_start: bool

    http_timeout: float
    http_max_tries: int
    http_retry_wait: float

    log_level: str

    @classmethod
    def from_env(cls, env_file: str | None = None) -> "Settings":
        load_dotenv(env_file)
        e = os.environ

        required = [
            "CONFLUENCE_EMAIL",
            "CONFLUENCE_API_TOKEN",
            "EMBEDDING_API_KEY",
            "QDRANT_API_KEY",
        ]
        missing = [k for k in required if not e.get(k, "").strip()]
        if missing:
            raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

        chunk_mode = e.get("CHUNK_MODE", "api").strip().lower()
        if chunk_mode not in {"api", "local"}:
            raise ConfigError("CHUNK_MODE must be 'api' or 'local'")

        return cls(
            confluence_base_url=e.get("CONFLUENCE_BASE_URL", "https://altoid.atlassian.net/wiki").rstrip("/"),
            confluence_email=e["CONFLUENCE_EMAIL"].strip(),
            confluence_api_token=e["CONFLUENCE_API_TOKEN"].strip(),
            confluence_space_key=e.get("CONFLUENCE_SPACE_KEY", "II"),
            confluence_space_id=e.get("CONFLUENCE_SPACE_ID", "131465483"),
            modified_window_days=int(e.get("MODIFIED_WINDOW_DAYS", "3")),
            search_page_limit=int(e.get("SEARCH_PAGE_LIMIT", "50")),
            trashed_page_limit=int(e.get("TRASHED_PAGE_LIMIT", "100")),
            page_type=e.get("PAGE_TYPE", "page"),
            convert_api_url=e.get("CONVERT_API_URL", "http://213.35.102.95:8000/convert"),
            chunk_mode=chunk_mode,
            chunk_api_url=e.get("CHUNK_API_URL", "http://213.35.102.95:8001/chunk"),
            chunk_size=int(e.get("CHUNK_SIZE", "6000")),
            chunk_overlap=int(e.get("CHUNK_OVERLAP", "200")),
            embedding_api_url=e.get("EMBEDDING_API_URL", "https://ai.sumopod.com/v1/embeddings"),
            embedding_api_key=e["EMBEDDING_API_KEY"].strip(),
            embedding_model=e.get("EMBEDDING_MODEL", "text-embedding-3-small"),
            qdrant_url=e.get("QDRANT_URL", "http://213.35.102.95:6333").rstrip("/"),
            qdrant_api_key=e["QDRANT_API_KEY"].strip(),
            qdrant_collection=e.get("QDRANT_COLLECTION", "space_alto"),
            qdrant_sparse_model=e.get("QDRANT_SPARSE_MODEL", "qdrant/bm25"),
            schedule_hour=int(e.get("SCHEDULE_HOUR", "1")),
            schedule_minute=int(e.get("SCHEDULE_MINUTE", "0")),
            schedule_timezone=e.get("SCHEDULE_TIMEZONE", "Asia/Jakarta"),
            run_on_start=_bool(e.get("RUN_ON_START", "false")),
            http_timeout=float(e.get("HTTP_TIMEOUT_SECONDS", "120")),
            http_max_tries=int(e.get("HTTP_MAX_TRIES", "3")),
            http_retry_wait=float(e.get("HTTP_RETRY_WAIT_SECONDS", "5")),
            log_level=e.get("LOG_LEVEL", "INFO").upper(),
        )
