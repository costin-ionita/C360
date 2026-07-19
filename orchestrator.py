"""Orchestrator: connects to both MCP servers, lets Claude plan and execute tool
calls, and builds up a report as an ordered list of sections (report_state.Section)
via a family of add_*_section tools -- the same tool loop and tool family serve both
"generate a fresh report" (starting from an empty section list) and "edit an existing
report" (starting from a populated one, see web/app.py's chat endpoint)."""

import asyncio
import json
import sys
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from audit_log.logger import get_session_entries, log_tool_call
from dashboard.render import render_static_page
from report_state import ReportState, Section, SECTION_TITLES

load_dotenv()

ROOT = Path(__file__).parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

MCP_SERVERS = {
    "structured": ROOT / "structured_server" / "server.py",
    "unstructured": ROOT / "unstructured_server" / "server.py",
}

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 8

# ---------------------------------------------------------------------------
# Section tools -- synthetic tools with no MCP server behind them. Each one
# mutates report_state.ReportState directly (see Orchestrator._apply_section_tool).
# Calling one of these a second time for the same standard type *replaces* that
# section in place (same list position), which is what makes "regenerate fundamentals"
# and "add fundamentals back after removing it" the same mechanism.
# ---------------------------------------------------------------------------

ADD_HEADER = {
    "name": "add_header",
    "description": (
        "Add or replace the report header (company name, ticker, exchange, as-of "
        "date). Call this once per report, typically first."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "company": {"type": "string"},
            "ticker": {"type": "string"},
            "exchange": {"type": "string"},
            "as_of": {"type": "string", "description": "Date/time the data was pulled"},
        },
        "required": ["company", "ticker", "as_of"],
    },
}

ADD_EXECUTIVE_SUMMARY = {
    "name": "add_executive_summary",
    "description": (
        "Add or replace the executive summary (2-4 sentences, plain language, lead "
        "with the most decision-relevant fact). Call this after gathering the data "
        "it references, typically last."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}

ADD_PRICE_SNAPSHOT_SECTION = {
    "name": "add_price_snapshot_section",
    "description": "Add or replace the price snapshot section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "price": {"type": "number"},
            "previous_close": {"type": "number"},
            "day_low": {"type": "number"},
            "day_high": {"type": "number"},
            "volume": {"type": "number"},
            "market_cap": {"type": "number"},
        },
    },
}

ADD_PRICE_HISTORY_CHART_SECTION = {
    "name": "add_price_history_chart_section",
    "description": "Add or replace the price history chart section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "price_history": {
                "type": "array",
                "description": "Closing price series for charting",
                "items": {
                    "type": "object",
                    "properties": {
                        "date": {"type": "string"},
                        "close": {"type": "number"},
                    },
                    "required": ["date", "close"],
                },
            }
        },
        "required": ["price_history"],
    },
}

ADD_FUNDAMENTALS_SECTION = {
    "name": "add_fundamentals_section",
    "description": "Add or replace the fundamentals section (valuation, profitability, growth).",
    "input_schema": {
        "type": "object",
        "properties": {
            "trailing_pe": {"type": ["number", "null"]},
            "forward_pe": {"type": ["number", "null"]},
            "price_to_book": {"type": ["number", "null"]},
            "trailing_eps": {"type": ["number", "null"]},
            "revenue_growth": {"type": ["number", "null"]},
            "profit_margins": {"type": ["number", "null"]},
            "return_on_equity": {"type": ["number", "null"]},
        },
    },
}

ADD_EARNINGS_SURPRISE_SECTION = {
    "name": "add_earnings_surprise_section",
    "description": (
        "Add or replace the earnings-vs-consensus section: recent quarters' EPS "
        "analyst estimate vs. actual reported, with surprise %."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "quarters": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "earnings_date": {"type": "string"},
                        "eps_estimate": {"type": ["number", "null"]},
                        "eps_actual": {"type": "number"},
                        "surprise_pct": {"type": ["number", "null"]},
                    },
                    "required": ["earnings_date", "eps_actual"],
                },
            }
        },
        "required": ["quarters"],
    },
}

ADD_RECENT_FILINGS_SECTION = {
    "name": "add_recent_filings_section",
    "description": "Add or replace the recent SEC filings section.",
    "input_schema": {
        "type": "object",
        "properties": {
            "filings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "form": {"type": "string"},
                        "filed_date": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            }
        },
        "required": ["filings"],
    },
}

ADD_FILING_EXCERPTS_SECTION = {
    "name": "add_filing_excerpts_section",
    "description": (
        "Add or replace the notable filing excerpts section: short quoted passages "
        "relevant to the query, each with a citation link back to its source filing."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "excerpts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["quote", "source_url"],
                },
            }
        },
        "required": ["excerpts"],
    },
}

STANDARD_SECTION_TOOLS = [
    ADD_HEADER,
    ADD_EXECUTIVE_SUMMARY,
    ADD_PRICE_SNAPSHOT_SECTION,
    ADD_PRICE_HISTORY_CHART_SECTION,
    ADD_FUNDAMENTALS_SECTION,
    ADD_EARNINGS_SURPRISE_SECTION,
    ADD_RECENT_FILINGS_SECTION,
    ADD_FILING_EXCERPTS_SECTION,
]

# tool name -> section type/id it writes to (id == type for all standard sections)
SECTION_TOOL_TYPES = {tool["name"]: tool["name"].removeprefix("add_").removesuffix("_section") for tool in STANDARD_SECTION_TOOLS}
SECTION_TOOL_TYPES["add_header"] = "header"
SECTION_TOOL_TYPES["add_executive_summary"] = "executive_summary"


def _load_skill() -> str:
    return (ROOT / "skills" / "financial-report-formatting" / "SKILL.md").read_text(encoding="utf-8")


def _mcp_tool_to_anthropic(tool) -> dict:
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


class Orchestrator:
    def __init__(self):
        self.mcp_sessions: dict[str, ClientSession] = {}
        self.tool_routing: dict[str, str] = {}
        self.anthropic_tools: list[dict] = []
        self.report_sessions: dict[str, ReportState] = {}
        self._stack = AsyncExitStack()
        self.client = anthropic.Anthropic()

    async def connect(self):
        for server_name, script_path in MCP_SERVERS.items():
            params = StdioServerParameters(command=PYTHON, args=[str(script_path)])
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.mcp_sessions[server_name] = session

            tools = await session.list_tools()
            for tool in tools.tools:
                self.tool_routing[tool.name] = server_name
                self.anthropic_tools.append(_mcp_tool_to_anthropic(tool))

    async def close(self):
        await self._stack.aclose()

    def get_or_create_session(self, session_id: str) -> ReportState:
        return self.report_sessions.setdefault(session_id, ReportState())

    async def _execute_tool(self, session_id: str, name: str, args: dict) -> str:
        server_name = self.tool_routing[name]
        mcp_session = self.mcp_sessions[server_name]
        result = await mcp_session.call_tool(name, args)
        text = "\n".join(c.text for c in result.content if hasattr(c, "text"))

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        log_tool_call(server=server_name, tool=name, args=args, result=parsed, session_id=session_id)

        return text

    def _apply_section_tool(self, session_id: str, state: ReportState, name: str, args: dict) -> str:
        section_type = SECTION_TOOL_TYPES.get(name)
        if section_type is None:
            result = f"Error: unknown section tool '{name}'"
            log_tool_call(server="report", tool=name, args=args, result=result, session_id=session_id)
            return result

        section = Section(id=section_type, type=section_type, title=SECTION_TITLES.get(section_type), data=args)
        idx = next((i for i, s in enumerate(state.sections) if s.id == section.id), None)
        if idx is not None:
            state.sections[idx] = section
        else:
            state.sections.append(section)

        result = f"Added/updated section '{section.id}'."
        log_tool_call(server="report", tool=name, args=args, result=result, session_id=session_id)
        return result

    def _refresh_sources(self, session_id: str, state: ReportState) -> None:
        """Rebuild the 'sources' section from the audit log -- never LLM-authored, so
        every number in the report stays traceable to the call that produced it."""
        entries = get_session_entries(session_id)
        data_entries = [e for e in entries if e.get("server") != "report"]
        sources_section = Section(
            id="sources",
            type="sources",
            title=SECTION_TITLES["sources"],
            data={"entries": [{"tool": e["tool"], "args": e["args"]} for e in data_entries]},
        )
        idx = next((i for i, s in enumerate(state.sections) if s.id == "sources"), None)
        if idx is not None:
            state.sections[idx] = sources_section
        else:
            state.sections.append(sources_section)

    def _build_system_prompt(self, state: ReportState) -> str:
        if state.sections:
            section_list = "\n".join(f"- {s.id} ({s.type}): {s.title or s.id}" for s in state.sections)
        else:
            section_list = "(none yet -- this is a fresh report)"
        return (
            "You are a financial research orchestrator. Given a user's natural-language "
            "query, decide which data tools to call (in parallel where possible) to "
            "gather the data needed to answer it. Build the report by calling one "
            "add_*_section tool per section -- these mutate the report directly, there "
            "is no separate 'submit' step. When the report reflects everything relevant "
            "to the query, reply with plain text and no further tool calls; that ends "
            "the turn.\n\n"
            f"Current report sections:\n{section_list}\n\n"
            "Follow these formatting conventions when building the report:\n\n" + _load_skill()
        )

    async def run_turn(self, session_id: str, user_message: str) -> tuple[str, ReportState]:
        state = self.get_or_create_session(session_id)
        state.messages.append({"role": "user", "content": user_message})

        tools = self.anthropic_tools + STANDARD_SECTION_TOOLS

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=self._build_system_prompt(state),
                tools=tools,
                messages=state.messages,
            )
            state.messages.append({"role": "assistant", "content": response.content})

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks:
                reply_text = "\n".join(b.text for b in response.content if b.type == "text")
                self._refresh_sources(session_id, state)
                return reply_text, state

            # Data tools (MCP) run concurrently -- their order never mattered. Section
            # tools mutate local state and run sequentially, preserving the order Claude
            # emitted them in, so the section list doesn't depend on asyncio scheduling.
            data_blocks = [b for b in tool_use_blocks if b.name in self.tool_routing]
            section_blocks = [b for b in tool_use_blocks if b.name not in self.tool_routing]

            data_results = await asyncio.gather(
                *(self._execute_tool(session_id, b.name, b.input) for b in data_blocks)
            )
            section_results = [
                self._apply_section_tool(session_id, state, b.name, b.input) for b in section_blocks
            ]

            results_by_id = dict(zip((b.id for b in data_blocks), data_results))
            results_by_id.update(zip((b.id for b in section_blocks), section_results))

            state.messages.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": b.id, "content": results_by_id[b.id]}
                        for b in tool_use_blocks
                    ],
                }
            )

        self._refresh_sources(session_id, state)
        return f"Exceeded {MAX_TOOL_ITERATIONS} tool-call iterations without finishing.", state


async def main():
    if len(sys.argv) < 2:
        print('Usage: python orchestrator.py "<natural language query>"')
        sys.exit(1)
    query = sys.argv[1]

    orch = Orchestrator()
    await orch.connect()
    try:
        session_id = str(uuid.uuid4())
        reply_text, state = await orch.run_turn(session_id, query)
    finally:
        await orch.close()

    if not state.sections:
        print(f"No report generated. Model's final reply: {reply_text}")
        sys.exit(1)

    header = next((s for s in state.sections if s.type == "header"), None)
    ticker = (header.data.get("ticker") if header else None) or "report"
    output_path = ROOT / "output" / f"report_{ticker.lower()}.html"
    render_static_page(state.sections, output_path)
    print(f"Report written to {output_path}")
    print(f"Model summary: {reply_text}")


if __name__ == "__main__":
    asyncio.run(main())
