"""Shared fixtures: a temporary library served in-process with a fake embedding model."""

import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from pocket_recall.config import MemoryConfig
from pocket_recall.embeddings import model_lifecycle_manager, model_specification
from pocket_recall.errors import EmbeddingError
from pocket_recall.retrieval.search_text_processing import words
from pocket_recall.transport.pocket_recall_service import PocketRecallService
from pocket_recall.transport.service_protocol import success_message


class FakeModel:
    """Deterministic bag-of-words vectors: texts sharing more words are more similar."""

    def __init__(self) -> None:
        self.calls = 0
        self.failing = False

    def embed(self, text: str) -> bytes:
        self.calls += 1
        if self.failing:
            raise EmbeddingError("Fake model unavailable")
        vector = np.zeros(model_specification.DIMENSIONS, dtype="<f4")
        for word in words(text.removeprefix(model_specification.QUERY_INSTRUCTION)):
            vector[zlib.crc32(word.encode()) % model_specification.DIMENSIONS] += 1
        if not vector.any():
            vector[0] = 1
        return (vector / np.linalg.norm(vector)).astype("<f4").tobytes()


@dataclass
class Library:
    """Send operations through the same dispatcher and audit path as the daemon."""

    service: PocketRecallService
    model: FakeModel

    @property
    def config(self) -> MemoryConfig:
        return self.service.config

    def call(self, operation: str, **arguments: object) -> object:
        result, _ = self.service.dispatcher.dispatch(operation, arguments)
        response = success_message("test", result)
        self.service.audit_retrieval(operation, arguments, result, response["result"], 0.0)
        return result

    def save(self, title: str, body: str, *aliases: str, memory_id: str | None = None, **extra: object) -> object:
        arguments = {"title": title, "body": body, "aliases": list(aliases), **extra}
        if memory_id is None:
            return self.call("memory.create", **arguments)
        return self.call("memory.update", memory_id=memory_id, **arguments)

    def search_ids(self, query: str) -> list[str]:
        return [candidate.id for candidate in self.call("search", query=query).candidates]

    def retry_index(self) -> None:
        """Run what the daemon's retry timer runs."""
        self.service.store.index_synchronizer.synchronize()


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> FakeModel:
    fake = FakeModel()

    class FakeEmbeddingProvider:
        @staticmethod
        def specification() -> str:
            return "fake-bag-of-words-v1"

        def __init__(self, config: MemoryConfig, *, allow_download: bool = False) -> None:
            pass

        def embed(self, text: str) -> bytes:
            return fake.embed(text)

    monkeypatch.setattr(model_lifecycle_manager, "EmbeddingProvider", FakeEmbeddingProvider)
    return fake


@pytest.fixture
def library(tmp_path: Path, model: FakeModel) -> Library:
    config = MemoryConfig(data_directory=tmp_path, index_retry_delays_seconds=(3600, 3600, 3600, 3600))
    service = PocketRecallService(config)
    service.dispatcher.dispatch("maintenance.init", {})
    yield Library(service=service, model=model)
    service.store.model_lifecycle_manager.close()
