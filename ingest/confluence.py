from __future__ import annotations

import logging
from typing import Iterator
from urllib.parse import urlsplit

import httpx

from .config import Settings
from .http import send

log = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, client: httpx.Client, settings: Settings):
        self._c = client
        self._s = settings
        self._space_ids: dict[str, str] | None = None  # key -> id, resolved lazily

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        return send(
            self._c, "GET", url, params=params,
            tries=self._s.http_max_tries, wait=self._s.http_retry_wait,
        )

    def _next_url(self, links: dict) -> str | None:
        """Resolve `_links.next`.

        v1 returns `/rest/api/...` (needs the `.../wiki` base prepended) while
        v2 returns `/wiki/api/v2/...` (already contains the context path).
        """
        nxt = links.get("next")
        if not nxt:
            return None
        if nxt.startswith("http"):
            return nxt
        base = (links.get("base") or self._s.confluence_base_url).rstrip("/")
        if nxt.startswith("/wiki/"):
            parts = urlsplit(base)
            return f"{parts.scheme}://{parts.netloc}{nxt}"
        return base + nxt

    def _paginate(self, url: str, params: dict) -> Iterator[dict]:
        seen: set[str] = set()
        next_params: dict | None = params
        while url and url not in seen:
            seen.add(url)
            resp = self._get(url, next_params)
            resp.raise_for_status()
            data = resp.json()
            yield data
            url = self._next_url(data.get("_links", {}))
            next_params = None  # the next URL already carries the query

    def resolve_space_ids(self) -> dict[str, str]:
        """Space key -> id for every configured key (v2 `GET /spaces?keys=`).

        Fails loudly when a key is not found, so a typo does not silently skip
        a space (and with it the trashed-page purge for that space).
        """
        if self._space_ids is None:
            s = self._s
            found: dict[str, str] = {}
            for data in self._paginate(
                f"{s.confluence_base_url}/api/v2/spaces",
                {"keys": ",".join(s.confluence_space_keys), "limit": 250},
            ):
                found.update({str(r["key"]): str(r["id"]) for r in data.get("results", [])})
            missing = [k for k in s.confluence_space_keys if k not in found]
            if missing:
                raise RuntimeError(f"Confluence space(s) not found or not accessible: {', '.join(missing)}")
            self._space_ids = {k: found[k] for k in s.confluence_space_keys}
            log.info("resolved spaces: %s", self._space_ids)
        return self._space_ids

    def search_modified_ids(self) -> list[str]:
        """Pages in the configured spaces modified within the window (CQL, v1 search)."""
        s = self._s
        keys = ",".join(f'"{k}"' for k in s.confluence_space_keys)
        cql = (
            f"type=page AND space in ({keys}) "
            f'AND lastmodified >= now("-{s.modified_window_days}d") '
            "ORDER BY lastmodified DESC"
        )
        ids: list[str] = []
        for data in self._paginate(
            f"{s.confluence_base_url}/rest/api/search",
            {"cql": cql, "limit": s.search_page_limit},
        ):
            ids.extend(str(r["content"]["id"]) for r in data.get("results", []))
        return list(dict.fromkeys(ids))

    def list_trashed_ids(self) -> list[str]:
        """All trashed pages of every configured space (v2, one call chain per
        space). No date filter: trashing does not bump the page version, so the
        full list is read on every run."""
        s = self._s
        ids: list[str] = []
        for space_id in self.resolve_space_ids().values():
            for data in self._paginate(
                f"{s.confluence_base_url}/api/v2/spaces/{space_id}/pages",
                {"status": "trashed", "sort": "-modified-date", "limit": s.trashed_page_limit},
            ):
                ids.extend(str(r["id"]) for r in data.get("results", []))
        return list(dict.fromkeys(ids))

    def get_page(self, page_id: str) -> dict | None:
        """Metadata + export_view body in one call. None if the page is gone."""
        resp = self._get(
            f"{self._s.confluence_base_url}/api/v2/pages/{page_id}",
            {"body-format": "export_view"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()
