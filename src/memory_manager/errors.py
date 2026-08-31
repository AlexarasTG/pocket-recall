"""Custom exceptions for the memory manager."""


class MemoryLookupError(LookupError):
    """The requested memory or archived version is missing or unavailable."""
