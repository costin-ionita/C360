# C360

A finance-flavored agentic workflow built to demonstrate MCP (Model Context Protocol)
integration patterns: two MCP servers, an orchestrator-workers agent using the Claude
API, a governance audit trail, and a rendered HTML dashboard — all driven by a single
natural-language query like *"Summarize Apple's latest quarter vs consensus."*

## Architecture

```
structured_server/     MCP server: quotes, fundamentals, price history, earnings
                        surprise (via yfinance)
unstructured_server/    MCP server: SEC EDGAR filings search + full text (free,
                        no API key)
skills/financial-report-formatting/SKILL.md
                        Report structure and table/chart formatting conventions,
                        loaded into the orchestrator's system prompt
orchestrator.py         Connects to both MCP servers, lets Claude plan + execute
                        tool calls (in parallel where possible), and forces a
                        structured final report via a submit_report tool
audit_log/              Append-only JSONL log of every tool call (governance)
dashboard/               Renders the structured report into a self-contained
                        Tailwind-styled HTML file with a hand-built, palette-
                        compliant price chart (light + dark mode, hover tooltip)
output/                 Generated HTML reports land here (gitignored)
```

### Tools

**structured_server** (numeric/tabular data):
- `get_quote(ticker)` — current price snapshot
- `get_fundamentals(ticker)` — valuation, profitability, growth metrics
- `get_price_history(ticker, period, interval)` — OHLCV bars
- `get_earnings_surprise(ticker, limit)` — EPS estimate vs. actual, surprise %

**unstructured_server** (filings/news text):
- `get_recent_filings(ticker, form_type, limit)` — filing metadata + document URLs
- `search_filings_fulltext(query, forms, ticker, limit)` — full-text search across
  SEC filings
- `get_filing_excerpt(url, max_chars)` — fetches a filing and returns readable
  plain text (strips inline-XBRL metadata)

### Why two MCP servers instead of one

Structured data (numbers, feeds tables/charts directly) and unstructured data
(prose, needs an LLM to read and summarize) have different consumption patterns
downstream. Splitting them lets the orchestrator reason about "which kind of tool
do I need" as a first split, and keeps each server's responsibility coherent.

### Why a `submit_report` tool instead of free-text output

The dashboard is rendered by a fixed Python/Jinja2 template (using Tailwind), not
LLM-authored HTML — cheaper and more visually consistent than asking an LLM to
hand-write markup on every run. To get reliable structured output from Claude,
`submit_report` is a "virtual" tool (no MCP server behind it) whose input schema
mirrors `skills/financial-report-formatting/SKILL.md`'s report structure; the API validates the shape, so the
final report never needs fragile text parsing.

## Setup

```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Create a `.env` file in the project root with your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```
.venv\Scripts\python.exe orchestrator.py "Summarize Apple's latest quarter vs consensus"
```

This connects to both MCP servers, lets Claude plan and execute the tool calls
needed to answer the query, logs every call to `audit_log/audit.jsonl`, and writes
a rendered report to `output/report_<ticker>.html`.

### Testing an individual MCP server

Each server can be exercised directly with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector):

```
npx @modelcontextprotocol/inspector ./.venv/Scripts/python.exe structured_server/server.py
npx @modelcontextprotocol/inspector ./.venv/Scripts/python.exe unstructured_server/server.py
```

## Governance

Every tool call (server, tool name, arguments, result, timestamp) is appended to
`audit_log/audit.jsonl`, so every number in a generated report is traceable back
to the exact call that produced it.
