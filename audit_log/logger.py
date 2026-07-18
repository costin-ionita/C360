"""Append-only JSONL audit trail of every MCP tool call, as a governance signal."""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(__file__).parent / "audit.jsonl"


def log_tool_call(server: str, tool: str, args: dict, result) -> None:
    """Record one tool call to the audit log.

    Args:
        server: Which MCP server handled the call, e.g. "structured", "unstructured".
        tool: Tool name, e.g. "get_quote".
        args: Arguments the tool was called with.
        result: The tool's return value (must be JSON-serializable, or stringifiable).
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "server": server,
        "tool": tool,
        "args": args,
        "result": result,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
