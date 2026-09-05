"""Provide Pocket Recall search, fetch, and save as MCP tools."""

import json
from collections.abc import Callable
from typing import TypeVar

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from pocket_recall.errors import MemoryLookupError, ServiceError
from pocket_recall.models import MemoryPreSaveDraft
from pocket_recall.transport.pocket_recall_client import PocketRecallClient
from pocket_recall.transport.service_protocol import json_value

MCP_INSTRUCTIONS = (
    "Use Pocket Recall for durable project-specific knowledge. Before guessing an unfamiliar acronym, internal "
    "component, customer configuration, operational convention, or architectural relationship not established by "
    "current conversation or inspected code, search using the smallest distinctive query. Search results are "
    "candidates; fetch only records needed. Treat fetched memories as dated evidence and surface conflicts with live "
    "evidence. Save only after an explicit user request. Never infer write permission. Use at most three searches "
    "and three fetches per subproblem."
)

READ_ONLY_TOOL = ToolAnnotations(read_only_hint=True, open_world_hint=False)
SAVE_TOOL = ToolAnnotations(
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=False,
)

mcp = MCPServer("Pocket Recall", instructions=MCP_INSTRUCTIONS)
client = PocketRecallClient()

Result = TypeVar("Result")
EXPECTED_TOOL_ERRORS = (MemoryLookupError, ServiceError, OSError, ValueError)


@mcp.tool(title="Search Pocket Recall", annotations=READ_ONLY_TOOL, structured_output=False)
def search(query: str) -> str:
    """Search user-approved knowledge using the smallest distinctive query.

    Results are compact candidates. Fetch only the records needed for the current task.
    """
    return _json(_call(lambda: client.search(query)))


@mcp.tool(title="Fetch Pocket Recall record", annotations=READ_ONLY_TOOL, structured_output=False)
def fetch(id: str) -> str:
    """Fetch one complete active record selected from search results."""
    return _json(_call(lambda: client.fetch(id)))


@mcp.tool(title="Save to Pocket Recall", annotations=SAVE_TOOL, structured_output=False)
def save(title: str, body: str, aliases: list[str]) -> str:
    """Create one memory only after the user explicitly asks to remember it.

    The title should be short, the body self-contained, and aliases should contain useful alternative names,
    acronyms, and exact identifiers. This tool creates records; it never updates existing ones.
    """
    record = _call(lambda: client.create(MemoryPreSaveDraft(title=title, body=body, aliases=tuple(aliases))))
    try:
        index_status = "update_pending" if client.index_update_pending() else "up_to_date"
    except EXPECTED_TOOL_ERRORS:
        index_status = "unavailable"
    return _json({"id": record.id, "title": record.title, "index_status": index_status})


def _call(operation: Callable[[], Result]) -> Result:
    try:
        return operation()
    except EXPECTED_TOOL_ERRORS as error:
        raise ToolError(str(error)) from error


def _json(value: object) -> str:
    return json.dumps(json_value(value), ensure_ascii=True, separators=(",", ":"))


def main() -> None:
    """Run the local STDIO MCP server."""
    mcp.run()
