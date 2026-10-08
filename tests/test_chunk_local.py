from ingest.services import chunk_local


def test_matches_reference_algorithm():
    text = "kata " * 20000
    out = chunk_local(text, 6000, 200)
    assert out["total_chunks"] == len(out["chunks"]) > 1
    assert [c["chunk_index"] for c in out["chunks"]] == list(range(out["total_chunks"]))
    assert all(c["token_count"] <= 6000 for c in out["chunks"])
    assert out["avg_len"] == round(sum(c["word_count"] for c in out["chunks"]) / out["total_chunks"], 3)
    assert chunk_local("", 6000, 200)["chunks"] == []
