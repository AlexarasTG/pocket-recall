"""Approved writes are durable, recoverable, and never silently overwritten."""

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from pocket_recall.errors import ConcurrentUpdateError, MemoryLookupError


def test_edit_keeps_previous_version_restorable(library):
    original = library.save("Start times", "ST means start times.", "ST")
    library.save("Start times", "ST marks where a programme begins.", "ST", memory_id=original.id)

    assert library.call("memory.get", memory_id=original.id).body == "ST marks where a programme begins."
    assert library.search_ids("programme") == [original.id]

    [revision] = library.call("archive.list", memory_id=original.id)
    assert revision.record.body == "ST means start times."
    library.call("memory.restore", memory_id=original.id, revision_id=revision.id)

    assert library.call("memory.get", memory_id=original.id).body == "ST means start times."
    assert library.search_ids("means") == [original.id]
    assert library.search_ids("programme") == []


def test_edit_based_on_outdated_preview_is_rejected(library):
    original = library.save("Start times", "ST means start times.", "ST")
    library.save("Start times", "First edit.", "ST", memory_id=original.id)

    with pytest.raises(ConcurrentUpdateError):
        library.save(
            "Start times",
            "Second edit from a stale preview.",
            "ST",
            memory_id=original.id,
            expected_updated_at=original.updated_at.isoformat(),
        )

    assert library.call("memory.get", memory_id=original.id).body == "First edit."


def test_deleted_memory_is_hidden_restorable_then_expires(library):
    record = library.save("Start times", "ST means start times.", "ST")

    library.call("memory.delete", memory_id=record.id)
    with pytest.raises(MemoryLookupError):
        library.call("memory.get", memory_id=record.id)
    assert library.search_ids("ST") == []

    library.call("memory.restore", memory_id=record.id)
    assert library.search_ids("ST") == [record.id]

    library.call("memory.delete", memory_id=record.id)
    expired = datetime.now(timezone.utc) - timedelta(days=library.config.recovery_retention_days + 1)
    with sqlite3.connect(library.config.memory_database) as connection:
        connection.execute("UPDATE memories SET deleted_at = ? WHERE id = ?", (expired.isoformat(), record.id))

    with pytest.raises(MemoryLookupError):
        library.call("memory.restore", memory_id=record.id)


@pytest.mark.parametrize(
    "body",
    [
        "Use api_key = abcdef1234567890 for staging.",
        '{"stream": "abc", "purposes": ["TM"]}',
        "x" * 1_001,
    ],
    ids=["credential", "raw-json", "too-long"],
)
def test_invalid_content_writes_nothing(library, body):
    with pytest.raises(ValueError):
        library.save("Rejected", body)

    assert library.call("memory.list") == ()
    assert library.call("maintenance.status")["index_update_pending"] is False
