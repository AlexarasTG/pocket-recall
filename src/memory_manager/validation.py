"""Check memory content without changing or shortening it."""

import json
import re

from memory_manager.config import MemoryConfig
from memory_manager.models import MemoryPreSaveDraft


SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"),
    re.compile(
        r"\b(?:password|passwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|"
        r"client[_ -]?secret|secret[_ -]?key)\b[\"']?\s*[:=]\s*[\"']?\S+",
        re.IGNORECASE,
    ),
    re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@", re.IGNORECASE),
)

AUTHORIZATION_PATTERN = re.compile(r"\b(?:Bearer|Basic)\s+([A-Za-z0-9+/_.=-]{8,})", re.IGNORECASE)


def validate_draft(draft: MemoryPreSaveDraft) -> None:
    fields = (draft.title, draft.body, *draft.aliases)
    if any(not isinstance(value, str) or not value.strip() for value in fields):
        raise ValueError("Title, body, and each alias must contain text")
    if any("\x00" in value for value in fields):
        raise ValueError("Memory text must not contain null characters")
    limit = MemoryConfig.RECORD_BODY_CHARACTER_LIMIT
    if len(draft.body) > limit:
        raise ValueError(f"Body has {len(draft.body)} characters; the limit is {limit}")

    text = "\n".join(fields)
    # Ignore ordinary words after Bearer/Basic, including a sentence-ending period.
    authorization_token_found = any(
        not match.group(1).rstrip(".").isalpha()
        for match in AUTHORIZATION_PATTERN.finditer(text)
    )
    if authorization_token_found or any(pattern.search(text) for pattern in SECRET_PATTERNS):
        raise ValueError("Possible credential or private key detected; remove it before saving")

    try:
        payload = json.loads(draft.body)
    except (ValueError, RecursionError):
        return
    if isinstance(payload, (dict, list)):
        raise ValueError("Store a short explanation, not a raw JSON payload")
