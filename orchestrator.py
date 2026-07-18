"""Orchestrator-workers agent: connects to both MCP servers, lets Claude plan and execute
tool calls to answer a natural-language query, and synthesizes a structured report
following skills/financial-report-formatting/SKILL.md conventions."""

import asyncio
import json
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from audit_log.logger import log_tool_call
from dashboard.render import render_report

load_dotenv()

ROOT = Path(__file__).parent
PYTHON = str(ROOT / ".venv" / "Scripts" / "python.exe")

MCP_SERVERS = {
    "structured": ROOT / "structured_server" / "server.py",
    "unstructured": ROOT / "unstructured_server" / "server.py",
}

MODEL = "claude-sonnet-5"
MAX_TOOL_ITERATIONS = 8

# A "virtual" tool with no server behind it -- its only purpose is to force Claude's
# final answer into the structured shape skills/financial-report-formatting/SKILL.md describes, instead of free text.
SUBMIT_REPORT_TOOL = {
    "name": "submit_report",
    "description": (
        "Submit the final synthesized report. Call this exactly once, as your final "
        "action, after you have gathered all data needed to answer the user's query."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "company": {"type": "string"},
                    "ticker": {"type": "string"},
                    "exchange": {"type": "string"},
                    "as_of": {"type": "string", "description": "Date/time the data was pulled"},
                },
                "required": ["company", "ticker", "as_of"],
            },
            "executive_summary": {
                "type": "string",
                "description": "2-4 sentences, plain language, leading with the most decision-relevant fact",
            },
            "price_snapshot": {
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
            },
            "fundamentals": {
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
            "earnings_surprise": {
                "type": "array",
                "description": "Recent quarters: EPS consensus estimate vs. actual reported, with surprise %",
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
            },
            "recent_filings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "form": {"type": "string"},
                        "filed_date": {"type": "string"},
                        "url": {"type": "string"},
                    },
                },
            },
            "filing_excerpts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "quote": {"type": "string"},
                        "source_url": {"type": "string"},
                    },
                    "required": ["quote", "source_url"],
                },
            },
            "sources": {
                "type": "array",
                "description": "Every tool call made while researching this report",
                "items": {
                    "type": "object",
                    "properties": {
                        "tool": {"type": "string"},
                        "args": {"type": "object"},
                    },
                },
            },
        },
        "required": ["header", "executive_summary", "sources"],
    },
}


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
        self.sessions: dict[str, ClientSession] = {}
        self.tool_routing: dict[str, str] = {}
        self.anthropic_tools: list[dict] = []
        self._stack = AsyncExitStack()
        self.client = anthropic.Anthropic()

    async def connect(self):
        for server_name, script_path in MCP_SERVERS.items():
            params = StdioServerParameters(command=PYTHON, args=[str(script_path)])
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self.sessions[server_name] = session

            tools = await session.list_tools()
            for tool in tools.tools:
                self.tool_routing[tool.name] = server_name
                self.anthropic_tools.append(_mcp_tool_to_anthropic(tool))

    async def close(self):
        await self._stack.aclose()

    async def _execute_tool(self, name: str, args: dict) -> str:
        server_name = self.tool_routing[name]
        session = self.sessions[server_name]
        result = await session.call_tool(name, args)
        text = "\n".join(c.text for c in result.content if hasattr(c, "text"))

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = text
        log_tool_call(server=server_name, tool=name, args=args, result=parsed)

        return text

    async def run(self, user_query: str) -> dict:
        system = (
            "You are a financial research orchestrator. Given a user's natural-language "
            "query, decide which tools to call (in parallel where possible) to gather the "
            "data needed to answer it, then synthesize a final report by calling "
            "submit_report exactly once, as your final action. Follow these formatting "
            "conventions when building the report:\n\n" + _load_skill()
        )

        messages = [{"role": "user", "content": user_query}]
        tools = self.anthropic_tools + [SUBMIT_REPORT_TOOL]

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                system=system,
                tools=tools,
                messages=messages,
            )
            messages.append({"role": "assistant", "content": response.content})

            tool_use_blocks = [b for b in response.content if b.type == "tool_use"]
            if not tool_use_blocks:
                return {
                    "error": "Model finished without calling submit_report",
                    "raw_text": "\n".join(b.text for b in response.content if b.type == "text"),
                }

            submit_block = next((b for b in tool_use_blocks if b.name == "submit_report"), None)
            if submit_block is not None:
                return submit_block.input

            worker_blocks = [b for b in tool_use_blocks if b.name != "submit_report"]
            results = await asyncio.gather(
                *(self._execute_tool(b.name, b.input) for b in worker_blocks)
            )

            tool_result_content = [
                {"type": "tool_result", "tool_use_id": block.id, "content": result}
                for block, result in zip(worker_blocks, results)
            ]
            messages.append({"role": "user", "content": tool_result_content})

        return {"error": f"Exceeded {MAX_TOOL_ITERATIONS} tool-call iterations without a final report"}


async def main():
    if len(sys.argv) < 2:
        print('Usage: python orchestrator.py "<natural language query>"')
        sys.exit(1)
    query = sys.argv[1]

    orch = Orchestrator()
    await orch.connect()
    try:
        report = await orch.run(query)
    finally:
        await orch.close()

    if "error" in report:
        print(json.dumps(report, indent=2))
        sys.exit(1)

    ticker = (report.get("header") or {}).get("ticker", "report").lower()
    output_path = ROOT / "output" / f"report_{ticker}.html"
    render_report(report, output_path)
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
