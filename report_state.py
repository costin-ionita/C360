"""Shared data model for a report's mutable section list.

Lives in its own module (not inside orchestrator.py or dashboard/render.py) because
both of those need it: orchestrator.py mutates it via tool calls, dashboard/render.py
renders it. Putting it in either of those two would create a circular import.
"""

from dataclasses import dataclass, field


@dataclass
class Section:
    id: str
    type: str
    title: str | None
    data: dict


@dataclass
class ReportState:
    sections: list[Section] = field(default_factory=list)
    messages: list[dict] = field(default_factory=list)


# Display titles for standard section types. `None` means "no heading" (the header
# section renders its own company/ticker markup instead of a generic label).
SECTION_TITLES: dict[str, str | None] = {
    "header": None,
    "executive_summary": "Executive Summary",
    "price_snapshot": "Price Snapshot",
    "price_history_chart": "Price History",
    "fundamentals": "Fundamentals",
    "earnings_surprise": "Earnings vs. Consensus",
    "recent_filings": "Recent Filings",
    "filing_excerpts": "Notable Filing Excerpts",
    "sources": "Sources",
}
