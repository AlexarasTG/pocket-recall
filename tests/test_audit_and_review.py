"""Retrieval auditing stays private, and review turns it into useful candidates."""


def test_audit_never_stores_memory_content(library):
    record = library.save("Zephyrine routing", "Quillback marmalade lives in the obsidian namespace.", "ZPR-ALIAS")

    library.call("search", query="quillback")
    library.call("memory.get", memory_id=record.id)

    audit = library.config.audit_database.read_bytes()
    for content in (b"Zephyrine", b"ZPR-ALIAS", b"marmalade", b"obsidian"):
        assert content not in audit


def test_review_reports_gaps_unused_records_and_near_duplicates(library):
    surfaced = library.save("ST detection type", "ST means start times.", "ST")
    never_searched = library.save("Recording pods", "Recording pods live in the well namespace.")
    duplicate = library.save("Binge markers types", "Binge markers are intro sequences, recaps, and end credits.")
    near_duplicate = library.save("Binge markers kinds", "Binge markers are intro sequences, recaps, and end credits.")

    library.call("search", query="ST")
    library.call("search", query="multica")
    library.call("search", query="multica")
    library.call("memory.get", memory_id=never_searched.id)
    created_after_window = library.save("Upload service", "The upload service stores customer files.")

    review = library.call("maintenance.review")

    assert {"keyword": "multica", "total_searches": 2, "empty_searches": 2} in review["gaps"]
    unused_ids = {record["id"] for record in review["unused"]}
    assert never_searched.id in unused_ids
    assert surfaced.id not in unused_ids
    assert created_after_window.id not in unused_ids
    pairs = [{memory["id"] for memory in pair["memories"]} for pair in review["similar_pairs"]]
    assert {duplicate.id, near_duplicate.id} in pairs
    assert {surfaced.id, never_searched.id} not in pairs
