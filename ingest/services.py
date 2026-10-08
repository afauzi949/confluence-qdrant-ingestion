from __future__ import annotations

import httpx

from .config import Settings
from .http import send


def build_metadata(page: dict, s: Settings) -> dict:
    """Same fields as the `Convert Markdown` node's metadata."""
    links = page["_links"]
    return {
        "pageId": page["id"],
        "title": page["title"],
        "spaceKey": links["webui"].split("/")[2],
        "url": links["base"] + links["webui"],
        "type": s.page_type,
        "createdAt": page.get("createdAt"),
        "lastModified": page["version"]["createdAt"],
    }


class Converter:
    """HTML -> Markdown via the external Docling service."""

    def __init__(self, client: httpx.Client, s: Settings):
        self._c, self._s = client, s

    def to_markdown(self, page: dict) -> str:
        body = page.get("body", {}).get("export_view", {}).get("value", "")
        payload = {
            "html_content": "title : # " + page["title"] + " #" + "\n " + body,
            "metadata": build_metadata(page, self._s),
        }
        resp = send(
            self._c, "POST", self._s.convert_api_url, json=payload,
            tries=self._s.http_max_tries, wait=self._s.http_retry_wait,
        )
        resp.raise_for_status()
        return resp.json()["markdown"]


def chunk_local(text: str, chunk_size: int, overlap: int) -> dict:
    """Same algorithm as convert-file-api/chunking.py (tiktoken, gpt-4o-mini)."""
    import tiktoken

    enc = tiktoken.encoding_for_model("gpt-4o-mini")
    tokens = enc.encode(text)
    chunks: list[dict] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        piece = enc.decode(tokens[start:end])
        chunks.append({
            "chunk_index": len(chunks),
            "text": piece,
            "token_count": end - start,
            "word_count": len(piece.split()),
        })
        if end == len(tokens):
            break
        start += chunk_size - overlap
    total_words = sum(c["word_count"] for c in chunks)
    return {
        "total_chunks": len(chunks),
        "avg_len": round(total_words / len(chunks), 3) if chunks else 0.0,
        "chunks": chunks,
    }


class Chunker:
    def __init__(self, client: httpx.Client, s: Settings):
        self._c, self._s = client, s

    def chunk(self, markdown: str) -> dict:
        s = self._s
        if s.chunk_mode == "local":
            return chunk_local(markdown, s.chunk_size, s.chunk_overlap)
        resp = send(
            self._c, "POST", s.chunk_api_url,
            json={"text": markdown, "chunk_size": s.chunk_size, "overlap": s.chunk_overlap},
            tries=s.http_max_tries, wait=s.http_retry_wait,
        )
        resp.raise_for_status()
        return resp.json()


class Embedder:
    """Dense embedding via the external OpenAI-compatible API."""

    def __init__(self, client: httpx.Client, s: Settings):
        self._c, self._s = client, s

    def embed(self, text: str) -> list[float]:
        s = self._s
        resp = send(
            self._c, "POST", s.embedding_api_url,
            json={"input": text, "model": s.embedding_model},
            headers={"Authorization": f"Bearer {s.embedding_api_key}"},
            tries=s.http_max_tries, wait=s.http_retry_wait,
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["embedding"]
