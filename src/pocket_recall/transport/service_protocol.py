"""Build and check JSON messages exchanged with the background service."""

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

PROTOCOL_VERSION = 1


def request_message(request_id: str, operation: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "operation": operation,
        "arguments": arguments,
    }


def success_message(request_id: str, result: object, *, warnings: tuple[str, ...] = ()) -> dict[str, object]:
    message: dict[str, object] = {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "success": True,
        "result": json_value(result),
    }
    if warnings:
        message["warnings"] = list(warnings)
    return message


def error_message(request_id: str, code: str, message: str) -> dict[str, object]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "success": False,
        "error": {"code": code, "message": message},
    }


def encode_message(message: dict[str, object]) -> bytes:
    return (json.dumps(message, ensure_ascii=True, separators=(",", ":")) + "\n").encode("utf-8")


def decode_message(data: bytes) -> dict[str, Any]:
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Message must be one valid UTF-8 JSON object") from error
    if not isinstance(message, dict):
        raise ValueError("Message must be a JSON object")
    return message


def validate_request(message: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ValueError(f"Unsupported protocol version; expected {PROTOCOL_VERSION}")
    request_id = message.get("request_id")
    operation = message.get("operation")
    arguments = message.get("arguments")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request_id must be a non-empty string")
    if not isinstance(operation, str) or not operation:
        raise ValueError("operation must be a non-empty string")
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    return request_id, operation, arguments


def json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return json_value(asdict(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    return value
