from __future__ import annotations

import uuid

import httpx

from .config import Settings
from .http import send

PURGE_BATCH = 500


def build_point(chunk: dict, dense: list[float], s: Settings) -> dict:
    """One Qdrant point.

    `chunk` is one row: chunk fields + avg_len + page metadata.
    The sparse BM25 vector is an inference object computed by Qdrant.
    """
    return {
        "id": str(uuid.uuid4()),
        "vector": {
            "dense": dense,
            "sparse": {
                "text": chunk["text"],
                "model": s.qdrant_sparse_model,
                "options": {"avg_len": chunk["avg_len"]},
            },
        },
        "payload": {
            "text": chunk["text"],
            "chunk_index": chunk["chunk_index"],
            "token_count": chunk["token_count"],
            "word_count": chunk["word_count"],
            "pageId": chunk["pageId"],
            "title": chunk["title"],
            "spaceKey": chunk["spaceKey"],
            "url": chunk["url"],
            "createdAt": chunk["createdAt"],
            "lastModified": chunk["lastModified"],
        },
    }


class QdrantStore:
    def __init__(self, client: httpx.Client, s: Settings):
        self._c, self._s = client, s
        self._base = f"{s.qdrant_url}/collections/{s.qdrant_collection}/points"
        self._headers = {"Authorization": f"Bearer {s.qdrant_api_key}"}

    def _call(self, method: str, url: str, body: dict) -> None:
        resp = send(
            self._c, method, url, json=body, headers=self._headers,
            tries=self._s.http_max_tries, wait=self._s.http_retry_wait,
        )
        resp.raise_for_status()

    def purge(self, page_ids: list[str]) -> None:
        for i in range(0, len(page_ids), PURGE_BATCH):
            batch = page_ids[i:i + PURGE_BATCH]
            self._call("POST", f"{self._base}/delete", {
                "filter": {"must": [{"key": "pageId", "match": {"any": batch}}]},
            })

    def upsert(self, points: list[dict]) -> None:
        if points:
            self._call("PUT", self._base, {"points": points})
