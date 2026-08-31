"""Prepare search text, check for small typos, and choose short body previews."""

import re


WORD_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
MIN_TYPO_WORD_LENGTH = 5
MAX_TYPO_ALTERNATIVES = 8
MAX_QUERY_CHARACTERS = 1_000
MAX_QUERY_TERMS = 32


def normalize_exact(text: str) -> str:
    return " ".join(text.casefold().split())


def words(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(WORD_PATTERN.findall(text.casefold())))


def query_terms(query: str) -> tuple[str, ...]:
    if not isinstance(query, str) or not query.strip() or "\x00" in query:
        raise ValueError("Search query must be nonblank text without null characters")
    if len(query) > MAX_QUERY_CHARACTERS:
        raise ValueError(f"Search query exceeds {MAX_QUERY_CHARACTERS} characters")
    terms = words(query)
    if len(terms) > MAX_QUERY_TERMS:
        raise ValueError(f"Search query exceeds {MAX_QUERY_TERMS} distinct terms")
    return terms


def keyword_expression(term_options: tuple[tuple[str, ...], ...]) -> str:
    # Every word is quoted so user text cannot become FTS operators or prefixes.
    return " AND ".join(
        "(" + " OR ".join('"' + term.replace('"', '""') + '"' for term in options) + ")"
        for options in term_options
    )


def is_one_typo_away(word: str, candidate: str) -> bool:
    if word == candidate or abs(len(word) - len(candidate)) > 1:
        return False
    for position, (left, right) in enumerate(zip(word, candidate)):
        if left == right:
            continue
        if len(word) < len(candidate):
            return word[position:] == candidate[position + 1:]
        if len(word) > len(candidate):
            return word[position + 1:] == candidate[position:]
        return (
            word[position + 1:] == candidate[position + 1:]
            or (
                word[position:position + 2] == candidate[position:position + 2][::-1]
                and word[position + 2:] == candidate[position + 2:]
            )
        )
    return abs(len(word) - len(candidate)) == 1


def excerpt_marker(body: str) -> str:
    marker = "\ue000"
    while marker in body:
        marker += "\ue000"
    return marker


def body_excerpt(body: str, highlighted_body: str | None, limit: int) -> str:
    if len(body) <= limit:
        return body
    match_position = highlighted_body.find(excerpt_marker(body)) if highlighted_body else -1
    start = max(0, match_position - limit // 2) if match_position >= 0 else 0
    start = min(start, len(body) - (limit - 1))
    prefix = "…" if start else ""
    available = limit - len(prefix)
    has_suffix = start + available < len(body)
    end = start + available - int(has_suffix)
    return prefix + body[start:end] + ("…" if has_suffix else "")
