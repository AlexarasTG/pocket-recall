"""Retrieval prefers strong matches, stays within context limits, and avoids loading the model."""


def save_detection_types(library):
    start = library.save("ST detection type", "ST means start times and is a detection type.", "ST")
    end = library.save("ET detection type", "ET means end times and is a detection type.", "ET")
    kubernetes = library.save("Kubernetes environments", "Kubernetes environments are dev, stg, and prod.")
    return start, end, kubernetes


def test_search_tries_exact_then_lexical_then_typo_then_semantic(library):
    start, end, kubernetes = save_detection_types(library)

    exact = library.call("search", query="ST").candidates
    assert [(candidate.id, candidate.match_kind) for candidate in exact] == [(start.id, "exact")]

    lexical = library.call("search", query="detection type").candidates
    assert {candidate.id for candidate in lexical} == {start.id, end.id}
    assert {candidate.match_kind for candidate in lexical} == {"lexical"}

    typo = library.call("search", query="kuberntes").candidates
    assert [(candidate.id, candidate.match_kind) for candidate in typo] == [(kubernetes.id, "typo")]

    semantic = library.call("search", query="start times detection type means unrelatedword").candidates
    assert [(candidate.id, candidate.match_kind) for candidate in semantic] == [(start.id, "semantic")]


def test_unrelated_query_returns_nothing_rather_than_noise(library):
    save_detection_types(library)

    assert library.search_ids("banana smoothie recipe") == []


def test_results_respect_context_limits(library):
    for number in range(7):
        library.save(f"Pipeline step {number}", f"Pipeline step {number} processes video.")
    long_record = library.save("Long pipeline notes", "Pipeline notes. " + "detail " * 120)
    deleted = library.save("Deleted pipeline", "Pipeline that was removed.")
    library.call("memory.delete", memory_id=deleted.id)

    candidates = library.call("search", query="pipeline").candidates

    assert len(candidates) == library.config.max_candidates_per_search
    assert deleted.id not in {candidate.id for candidate in candidates}
    long_excerpt = library.call("search", query="Long pipeline notes").candidates[0]
    assert long_excerpt.id == long_record.id
    assert len(long_excerpt.excerpt) <= library.config.SEARCH_PREVIEW_CHARACTER_LIMIT
    assert long_excerpt.excerpt != library.call("memory.get", memory_id=long_record.id).body


def test_exact_and_lexical_searches_do_not_use_the_model(library):
    save_detection_types(library)
    library.model.calls = 0

    library.call("search", query="ST")
    library.call("search", query="detection type")

    assert library.model.calls == 0
