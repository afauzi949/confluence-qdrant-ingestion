import json

import httpx
import pytest

from ingest.config import ConfigError, Settings
from ingest.pipeline import Pipeline

WIKI = "https://altoid.atlassian.net/wiki"


def page(pid, status="current", title="T"):
    return {
        "id": pid, "status": status, "title": title,
        "createdAt": "2026-01-01T00:00:00.000Z",
        "version": {"createdAt": "2026-10-08T06:00:00.000Z"},
        "body": {"export_view": {"value": "<p>hi</p>"}},
        "_links": {"base": WIKI, "webui": f"/spaces/II/pages/{pid}/T"},
    }


class Fake:
    """Routes mocked HTTP calls and records Qdrant traffic in order."""

    def __init__(self, modified, trashed, pages, chunks=1, search_pages=None):
        self.modified, self.trashed, self.pages, self.chunks = modified, trashed, pages, chunks
        self.search_pages = search_pages
        self.qdrant = []  # (method, path, body)
        self.embedded = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        url, path = str(req.url), req.url.path
        if path == "/wiki/rest/api/search":
            if self.search_pages:
                start = int(req.url.params.get("start", 0))
                ids = self.search_pages[start]
                links = {"base": WIKI}
                if start + 1 < len(self.search_pages):
                    links["next"] = f"/rest/api/search?cql=x&start={start + 1}"
                return httpx.Response(200, json={
                    "results": [{"content": {"id": i}} for i in ids], "_links": links})
            return httpx.Response(200, json={
                "results": [{"content": {"id": i}} for i in self.modified], "_links": {"base": WIKI}})
        if path.endswith("/spaces/131465483/pages"):
            assert req.url.params["status"] == "trashed"
            return httpx.Response(200, json={
                "results": [{"id": i} for i in self.trashed], "_links": {"base": WIKI}})
        if path.startswith("/wiki/api/v2/pages/"):
            p = self.pages.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=p) if p else httpx.Response(404)
        if path == "/convert":
            body = json.loads(req.content)
            assert body["html_content"].startswith("title : # ")
            return httpx.Response(200, json={"markdown": "md", "metadata": body["metadata"]})
        if path == "/chunk":
            body = json.loads(req.content)
            assert (body["chunk_size"], body["overlap"]) == (6000, 200)
            chunks = [{"chunk_index": i, "text": f"c{i}", "token_count": 3, "word_count": 1}
                      for i in range(self.chunks)]
            return httpx.Response(200, json={"total_chunks": self.chunks, "avg_len": 1.0, "chunks": chunks})
        if path == "/v1/embeddings":
            assert req.headers["authorization"] == "Bearer ek"
            self.embedded.append(json.loads(req.content)["input"])
            return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})
        if "/collections/space_alto/points" in path:
            assert req.headers["authorization"] == "Bearer qk"
            self.qdrant.append((req.method, path.rsplit("/", 1)[1], json.loads(req.content)))
            return httpx.Response(200, json={"status": "ok"})
        raise AssertionError(f"unexpected request {req.method} {url}")


def run(settings, fake, **kw):
    return Pipeline(settings, transport=httpx.MockTransport(fake)).run(**kw)


def test_payload_schema_and_order(settings):
    fake = Fake(["1"], [], {"1": page("1", title="Hello")}, chunks=2)
    res = run(settings, fake)
    assert res.ok and res.ingested == {"1": 2}

    ops = [(m, a) for m, a, _ in fake.qdrant]
    assert ops == [("POST", "delete"), ("PUT", "points")]  # purge before upsert

    purge = fake.qdrant[0][2]
    assert purge == {"filter": {"must": [{"key": "pageId", "match": {"any": ["1"]}}]}}

    points = fake.qdrant[1][2]["points"]
    assert len(points) == 2
    p = points[0]
    assert list(p) == ["id", "vector", "payload"]
    assert p["vector"]["dense"] == [0.1, 0.2]
    assert p["vector"]["sparse"] == {"text": "c0", "model": "qdrant/bm25", "options": {"avg_len": 1.0}}
    assert list(p["payload"]) == [
        "text", "chunk_index", "token_count", "word_count", "pageId", "title",
        "spaceKey", "url", "createdAt", "lastModified"]
    assert p["payload"]["pageId"] == "1"
    assert p["payload"]["spaceKey"] == "II"
    assert p["payload"]["url"] == f"{WIKI}/spaces/II/pages/1/T"
    assert p["payload"]["lastModified"] == "2026-10-08T06:00:00.000Z"
    assert len({q["id"] for q in points}) == 2


def test_trashed_is_purged_and_never_ingested(settings):
    # page 2 shows up in both lists: must be purged, not fetched/ingested
    fake = Fake(["1", "2"], ["2", "9"], {"1": page("1"), "2": page("2")})
    res = run(settings, fake)
    assert res.modified == ["1"] and res.ingested == {"1": 1}

    first = fake.qdrant[0][2]["filter"]["must"][0]["match"]["any"]
    assert first == ["2", "9"]
    upserted = [pt["payload"]["pageId"] for m, _, b in fake.qdrant if m == "PUT" for pt in b["points"]]
    assert upserted == ["1"]


def test_non_current_or_missing_page_is_purged_only(settings):
    fake = Fake(["3", "4"], [], {"3": page("3", status="archived")})  # 4 -> 404
    res = run(settings, fake)
    assert res.purged_only == ["3", "4"] and not res.ingested and res.ok
    assert all(m == "POST" for m, _, _ in fake.qdrant)


def test_failure_keeps_old_vectors_and_continues(settings):
    class Boom(Fake):
        def __call__(self, req):
            if req.url.path == "/v1/embeddings" and "c0" in req.content.decode() and self.fail_next:
                self.fail_next = False
                return httpx.Response(400, json={"error": "bad"})
            return super().__call__(req)

    fake = Boom(["1", "2"], [], {"1": page("1"), "2": page("2")})
    fake.fail_next = True
    res = run(settings, fake)
    assert list(res.failed) == ["1"] and not res.ok
    assert res.ingested == {"2": 1}
    # nothing was purged for the failed page 1
    purged = [b["filter"]["must"][0]["match"]["any"] for m, a, b in fake.qdrant if a == "delete"]
    assert purged == [["2"]]


def test_search_pagination_follows_next(settings):
    fake = Fake([], [], {"1": page("1"), "2": page("2")}, search_pages=[["1"], ["2"]])
    res = run(settings, fake)
    assert res.modified == ["1", "2"]


def test_dry_run_writes_nothing(settings):
    fake = Fake(["1"], ["9"], {"1": page("1")})
    res = run(settings, fake, dry_run=True)
    assert fake.qdrant == [] and fake.embedded == []
    assert res.modified == ["1"] and res.trashed == ["9"]


def test_missing_required_env(monkeypatch):
    for k in ("CONFLUENCE_EMAIL", "CONFLUENCE_API_TOKEN", "EMBEDDING_API_KEY", "QDRANT_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("ingest.config.load_dotenv", lambda *_a, **_k: None)
    with pytest.raises(ConfigError):
        Settings.from_env()
