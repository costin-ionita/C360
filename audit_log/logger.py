"""Append-only JSONL audit trail of every MCP tool call and section edit, as a
governance signal. Also the source of truth for the report's `sources` section
(see report_state.SECTION_TITLES) -- that section is never LLM-authored, it's
derived by filtering this log to one session's data-tool calls."""

import json
from datetime import datetime, timezone
from pathlib import Path

LOG_FILE = Path(__file__).parent / "audit.jsonl"


def log_tool_call(server: str, tool: str, args: dict, result, session_id: str | None = None) -> None:
    """Record one tool call to the audit log.

    Args:
        server: Which MCP server handled the call (e.g. "structured", "unstructured"),
            or "report" for a local section-mutation tool call (no MCP server behind it).
        tool: Tool name, e.g. "get_quote", "add_fundamentals_section".
        args: Arguments the tool was called with.
        result: The tool's return value (must be JSON-serializable, or stringifiable).
        session_id: The report/chat session this call belongs to.
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "server": server,
        "tool": tool,
        "args": args,
        "result": result,
    }
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def get_session_entries(session_id: str) -> list[dict]:
    """Return every logged call for one session, in the order they were made."""
    if not LOG_FILE.exists():
        return []
    entries = []
    with open(LOG_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            if entry.get("session_id") == session_id:
                entries.append(entry)
    return entries
