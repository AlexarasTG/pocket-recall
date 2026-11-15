"""The search index may lag behind canonical records, but it never loses or misreports them."""

import sqlite3

import pytest


def test_index_failure_keeps_approved_memory_until_retry(library):
    library.model.failing = True
    record = library.save("Start times", "ST means start times.", "ST")

    assert library.call("memory.get", memory_id=record.id).body == "ST means start times."
    results = library.call("search", query="ST")
    assert results.candidates == ()
    assert results.index_update_pending is True

    library.model.failing = False
    library.retry_index()

    results = library.call("search", query="ST")
    assert [candidate.id for candidate in results.candidates] == [record.id]
    assert results.index_update_pending is False


def test_outdated_index_entry_is_never_returned(library):
    record = library.save("Start times", "ST means start times.", "ST")

    library.model.failing = True
    library.save("Start times", "ST marks where a programme begins.", "ST", memory_id=record.id)

    assert library.search_ids("means") == []
    assert library.call("search", query="means").index_update_pending is True


def test_unreadable_index_is_an_error_not_an_empty_result(library):
    library.save("Start times", "ST means start times.", "ST")
    library.config.search_database.write_bytes(b"not a database")

    with pytest.raises((ValueError, sqlite3.Error)):
        library.call("search", query="ST")
