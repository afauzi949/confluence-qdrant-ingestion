import pytest

from ingest.config import Settings

ENV = {
    "CONFLUENCE_EMAIL": "u@example.com",
    "CONFLUENCE_API_TOKEN": "tok",
    "EMBEDDING_API_KEY": "ek",
    "QDRANT_API_KEY": "qk",
    "HTTP_RETRY_WAIT_SECONDS": "0",
}


@pytest.fixture
def settings(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("ingest.config.load_dotenv", lambda *_a, **_k: None)
    return Settings.from_env()
