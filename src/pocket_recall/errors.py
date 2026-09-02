"""Custom exceptions for Pocket Recall."""


class MemoryLookupError(LookupError):
    """The requested memory or archived version is missing or unavailable."""


class EmbeddingError(RuntimeError):
    """The local model could not load or turn text into a usable vector."""


class ConcurrentUpdateError(RuntimeError):
    """The memory changed after it was shown for approval."""


class ServiceError(RuntimeError):
    """The local service rejected a request or could not complete it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
