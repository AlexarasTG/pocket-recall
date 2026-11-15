"""Malformed requests are rejected before they reach storage."""

import pytest

from pocket_recall.transport.service_protocol import request_message, validate_request


def test_unsupported_protocol_version_is_rejected():
    message = {**request_message("id", "search", {"query": "ST"}), "protocol_version": 999}

    with pytest.raises(ValueError):
        validate_request(message)


@pytest.mark.parametrize(
    ("operation", "arguments"),
    [
        ("memory.explode", {}),
        ("memory.create", {"title": 3, "body": "Body", "aliases": []}),
        ("memory.create", {"title": "Title", "body": "Body", "aliases": "ST"}),
        ("maintenance.review", {"unexpected": True}),
    ],
    ids=["unknown-operation", "non-text-title", "aliases-not-a-list", "unexpected-argument"],
)
def test_malformed_requests_are_rejected_without_writing(library, operation, arguments):
    with pytest.raises(ValueError):
        library.service.dispatcher.dispatch(operation, arguments)

    assert library.call("memory.list") == ()
