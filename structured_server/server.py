"""MCP server exposing structured market data (quotes, fundamentals, price history) via yfinance."""

from mcp.server.fastmcp import FastMCP
import pandas as pd
import yfinance as yf

mcp = FastMCP("structured-market-data")


@mcp.tool()
def get_quote(ticker: str) -> dict:
    """Get the current/latest price snapshot for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "MSFT".
    """
    t = yf.Ticker(ticker)
    info = t.info

    if not info or info.get("regularMarketPrice") is None:
        return {"error": f"No quote data found for ticker '{ticker}'"}

    return {
        "ticker": ticker.upper(),
        "shortName": info.get("shortName"),
        "currency": info.get("currency"),
        "regularMarketPrice": info.get("regularMarketPrice"),
        "previousClose": info.get("previousClose"),
        "open": info.get("open"),
        "dayLow": info.get("dayLow"),
        "dayHigh": info.get("dayHigh"),
        "volume": info.get("volume"),
        "marketCap": info.get("marketCap"),
        "exchange": info.get("exchange"),
    }


@mcp.tool()
def get_fundamentals(ticker: str) -> dict:
    """Get key fundamental metrics for a stock: valuation, profitability, and per-share figures.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "MSFT".
    """
    t = yf.Ticker(ticker)
    info = t.info

    if not info or info.get("shortName") is None:
        return {"error": f"No fundamentals data found for ticker '{ticker}'"}

    return {
        "ticker": ticker.upper(),
        "shortName": info.get("shortName"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "marketCap": info.get("marketCap"),
        "trailingPE": info.get("trailingPE"),
        "forwardPE": info.get("forwardPE"),
        "priceToBook": info.get("priceToBook"),
        "trailingEps": info.get("trailingEps"),
        "forwardEps": info.get("forwardEps"),
        "totalRevenue": info.get("totalRevenue"),
        "revenueGrowth": info.get("revenueGrowth"),
        "grossMargins": info.get("grossMargins"),
        "operatingMargins": info.get("operatingMargins"),
        "profitMargins": info.get("profitMargins"),
        "returnOnEquity": info.get("returnOnEquity"),
        "debtToEquity": info.get("debtToEquity"),
        "dividendYield": info.get("dividendYield"),
        "beta": info.get("beta"),
        "fiftyTwoWeekLow": info.get("fiftyTwoWeekLow"),
        "fiftyTwoWeekHigh": info.get("fiftyTwoWeekHigh"),
    }


@mcp.tool()
def get_price_history(ticker: str, period: str = "3mo", interval: str = "1d") -> dict:
    """Get historical OHLCV price data for a stock ticker.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "MSFT".
        period: Lookback window, e.g. "1mo", "3mo", "6mo", "1y", "5y", "max".
        interval: Bar size, e.g. "1d", "1wk", "1mo".
    """
    t = yf.Ticker(ticker)
    hist = t.history(period=period, interval=interval)

    if hist.empty:
        return {"error": f"No price history found for ticker '{ticker}'"}

    hist = hist.reset_index()
    date_col = "Date" if "Date" in hist.columns else "Datetime"

    bars = [
        {
            "date": row[date_col].strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
            "volume": int(row["Volume"]),
        }
        for _, row in hist.iterrows()
    ]

    return {
        "ticker": ticker.upper(),
        "period": period,
        "interval": interval,
        "bars": bars,
    }


@mcp.tool()
def get_earnings_surprise(ticker: str, limit: int = 4) -> dict:
    """Get recent quarterly EPS: analyst consensus estimate vs. actual reported, with surprise %.

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "MSFT".
        limit: Max number of most recently reported quarters to return.
    """
    t = yf.Ticker(ticker)
    # yfinance's own `limit` counts future/unreported dates too, so over-fetch and filter.
    df = t.get_earnings_dates(limit=limit + 8)

    if df is None or df.empty:
        return {"error": f"No earnings history found for ticker '{ticker}'"}

    reported = df.dropna(subset=["Reported EPS"]).sort_index(ascending=False).head(limit)

    quarters = [
        {
            "earningsDate": idx.strftime("%Y-%m-%d"),
            "epsEstimate": round(row["EPS Estimate"], 2) if pd.notna(row["EPS Estimate"]) else None,
            "epsActual": round(row["Reported EPS"], 2),
            "surprisePct": round(row["Surprise(%)"], 2) if pd.notna(row["Surprise(%)"]) else None,
        }
        for idx, row in reported.iterrows()
    ]

    return {"ticker": ticker.upper(), "quarters": quarters}


if __name__ == "__main__":
    mcp.run()
