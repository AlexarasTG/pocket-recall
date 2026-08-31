"""Custom exceptions for the memory manager."""


class MemoryLookupError(LookupError):
    """The requested memory or archived version is missing or unavailable."""


class EmbeddingError(RuntimeError):
    """The local model could not load or turn text into a usable vector."""
