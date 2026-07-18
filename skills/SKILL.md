---
name: financial-report-formatting
description: Report structure and formatting conventions for equity research summaries synthesized from structured market data and unstructured SEC filings.
---

# Financial Report Formatting

Conventions for turning tool results (quotes, fundamentals, price history, filings) into a single coherent report. Apply these rules when synthesizing the final output, regardless of which specific company or query triggered it.

## Report structure

Produce sections in this order. If no data was returned for a section, display the section header and a single line stating "No data available" rather than omitting the section entirely. This ensures that the report is complete and that the reader can see which sections were intentionally left blank.

1. **Header** — Company name, ticker, exchange, as-of date/time of the data pulled.
2. **Executive summary** — 2-4 sentences, plain language, no jargon. Lead with the single most decision-relevant fact (e.g. "beat/missed consensus," "trading near 52-week high").
3. **Price snapshot** — table: current price, change vs. previous close, day range, volume, market cap.
4. **Price history chart** — line chart of closing price over the requested period. See Chart conventions below.
5. **Fundamentals** — table: valuation (P/E, forward P/E, P/B), profitability (margins, ROE), growth (revenue growth), and per-share figures (EPS). Group related metrics together rather than listing alphabetically.
6. **Earnings vs. consensus** — table of recent quarters: EPS analyst estimate, actual reported EPS, and surprise %. This is the "beat/missed consensus" data point referenced in the executive summary — never state a beat/miss without it appearing here.
7. **Recent filings** — table of recent SEC filings (form type, filed date, link).
8. **Notable filing excerpts** — short quoted passages (1-3 sentences each) pulled from filing text that are directly relevant to the query, each with a citation link back to the source filing.
9. **Sources** — footer listing every tool call made (tool name, key arguments, timestamp),so every figure in the report is traceable to where it came from.

## Table conventions

- **Currency**: `$` prefix, thousands separators, 2 decimal places for prices (`$334.02`), no decimals for large aggregates (`$4,905,797,419,008` → prefer abbreviated form `$4.91T` for market cap / revenue scale figures).
- **Percentages**: 1 decimal place (`27.2%`), always signed for changes (`+2.1%` / `-0.8%`).
- **Dates**: `YYYY-MM-DD`, never locale-ambiguous formats like `03/04/26`.
- **Missing data**: render as `N/A`, never `0`, `null`, or a blank cell — several yfinance fields are legitimately absent depending on company/exchange, and `0` would misrepresent that as an actual zero value.

## Chart conventions

- Price history: line chart, x-axis = date, y-axis = closing price. Do not use 3D effects, unnecessary dual axes, or more than one series unless explicitly comparing tickers.
- Use a consistent color for positive/up movement and a consistent different color for negative/down movement across the whole report — do not vary this per chart.
- Label axes and include units. Never rely on color alone to convey meaning (accessibility).
- Prefer fewer, clearer gridlines over a dense grid.

## Sourcing rule

Every number or claim in the report must be attributable to a specific tool call result. If synthesizing a comparison (e.g. "vs. consensus"), state explicitly what data backs the comparison and flag when a figure is an estimate or unavailable rather than inferring it.
