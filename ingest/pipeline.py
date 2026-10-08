from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx

from .config import Settings
from .confluence import ConfluenceClient
from .qdrant import QdrantStore, build_point
from .services import Chunker, Converter, Embedder, build_metadata

log = logging.getLogger(__name__)


@dataclass
class RunResult:
    trashed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    ingested: dict[str, int] = field(default_factory=dict)  # pageId -> points
    purged_only: list[str] = field(default_factory=list)    # gone / not current
    failed: dict[str, str] = field(default_factory=dict)    # pageId -> error

    @property
    def ok(self) -> bool:
        return not self.failed


class Pipeline:
    def __init__(self, s: Settings, transport: httpx.BaseTransport | None = None):
        self._s = s

        def mk(**kw) -> httpx.Client:
            return httpx.Client(timeout=s.http_timeout, transport=transport, **kw)

        self.confluence = ConfluenceClient(
            mk(auth=(s.confluence_email, s.confluence_api_token)), s)
        plain = mk()
        self.converter = Converter(plain, s)
        self.chunker = Chunker(plain, s)
        self.embedder = Embedder(mk(), s)
        self.qdrant = QdrantStore(mk(), s)

    def run(self, dry_run: bool = False) -> RunResult:
        res = RunResult()
        res.trashed = self.confluence.list_trashed_ids()
        modified = self.confluence.search_modified_ids()
        trashed = set(res.trashed)
        # never re-ingest a page that is trashed
        res.modified = [p for p in modified if p not in trashed]
        log.info("trashed=%d modified=%d (after excluding trashed)", len(res.trashed), len(res.modified))

        if dry_run:
            log.info("dry-run: trashed=%s modified=%s", res.trashed, res.modified)
            return res

        if res.trashed:
            self.qdrant.purge(res.trashed)
            log.info("purged %d trashed pages", len(res.trashed))

        for page_id in res.modified:
            try:
                self._sync_page(page_id, res)
            except Exception as exc:  # one bad page must not stop the run
                log.exception("page %s failed", page_id)
                res.failed[page_id] = f"{exc.__class__.__name__}: {exc}"

        log.info("done: ingested=%d purged_only=%d failed=%d",
                 len(res.ingested), len(res.purged_only), len(res.failed))
        return res

    def _sync_page(self, page_id: str, res: RunResult) -> None:
        page = self.confluence.get_page(page_id)
        if page is None or page.get("status") != "current":
            # deleted or no longer current: drop its vectors, do not ingest
            self.qdrant.purge([page_id])
            res.purged_only.append(page_id)
            return

        meta = build_metadata(page, self._s)
        markdown = self.converter.to_markdown(page)
        chunked = self.chunker.chunk(markdown)

        points = []
        for ch in chunked["chunks"]:
            row = {**ch, "avg_len": chunked["avg_len"], **meta}
            points.append(build_point(row, self.embedder.embed(ch["text"]), self._s))

        # everything is prepared: swap old vectors for new ones
        self.qdrant.purge([page_id])
        self.qdrant.upsert(points)
        res.ingested[page_id] = len(points)
        log.info("page %s: %d chunks upserted", page_id, len(points))
