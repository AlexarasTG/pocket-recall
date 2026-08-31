"""Load one embedding model on demand and release it after an idle period."""

from threading import RLock, Timer
from time import monotonic

from pocket_recall.config import MemoryConfig
from pocket_recall.embeddings import model_specification
from pocket_recall.embeddings.embedding_provider import EmbeddingProvider
from pocket_recall.models import MemoryRecord


class ModelLifecycleManager:
    """Share a model between indexing and search, with one embedding request at a time."""

    def __init__(self, config: MemoryConfig) -> None:
        self.config = config
        self.specification = EmbeddingProvider.specification()
        self.dimensions = model_specification.DIMENSIONS
        self._provider: EmbeddingProvider | None = None
        self._lock = RLock()
        self._idle_timer: Timer | None = None
        self._last_used = 0.0

    def prepare(self) -> None:
        """Allow the explicit initialization command to download the pinned model."""
        with self._lock:
            self._load(allow_download=True)
            self._schedule_unload()

    def embed_record(self, record: MemoryRecord) -> bytes:
        text = "\n".join((record.title, ", ".join(record.aliases), record.body))
        return self._embed(text)

    def embed_query(self, query: str) -> bytes:
        return self._embed(model_specification.QUERY_INSTRUCTION + query)

    def _embed(self, text: str) -> bytes:
        with self._lock:
            provider = self._load()
            try:
                return provider.embed(text)
            finally:
                self._schedule_unload()

    def _load(self, *, allow_download: bool = False) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = EmbeddingProvider(self.config, allow_download=allow_download)
        return self._provider

    def _schedule_unload(self) -> None:
        self._last_used = monotonic()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        self._idle_timer = Timer(self.config.model_idle_timeout_minutes * 60, self._unload_if_idle)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def _unload_if_idle(self) -> None:
        with self._lock:
            if monotonic() - self._last_used >= self.config.model_idle_timeout_minutes * 60:
                self.close()

    def close(self) -> None:
        """Release the model and cancel its idle timer."""
        with self._lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._provider = None
