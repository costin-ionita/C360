"""MCP server exposing unstructured filings/news data via SEC EDGAR's free full-text search API."""

import re

import requests
from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("unstructured-filings-data")

# SEC requires a descriptive User-Agent identifying the requester on every request,
# or it will rate-limit / block. See https://www.sec.gov/os/webmaster-faq#developers
SEC_HEADERS = {"User-Agent": "C360 Interview Portfolio Project message.costin@gmail.com"}

_TICKER_TO_CIK: dict[str, str] = {}


def _load_ticker_map() -> dict[str, str]:
    """Fetch and cache SEC's ticker->CIK mapping (fetched once per server process)."""
    global _TICKER_TO_CIK
    if not _TICKER_TO_CIK:
        resp = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=SEC_HEADERS,
            timeout=10,
        )
        resp.raise_for_status()
        for entry in resp.json().values():
            _TICKER_TO_CIK[entry["ticker"].upper()] = str(entry["cik_str"]).zfill(10)
    return _TICKER_TO_CIK


def _cik_for_ticker(ticker: str) -> str | None:
    return _load_ticker_map().get(ticker.upper())


@mcp.tool()
def get_recent_filings(ticker: str, form_type: str | None = None, limit: int = 10) -> dict:
    """Get a company's recent SEC filings (form type, filing date, document URL).

    Args:
        ticker: Stock ticker symbol, e.g. "AAPL", "MSFT".
        form_type: Optional filter, e.g. "10-K", "10-Q", "8-K". Omit for all form types.
        limit: Max number of filings to return.
    """
    cik = _cik_for_ticker(ticker)
    if cik is None:
        return {"error": f"No CIK found for ticker '{ticker}'"}

    resp = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=SEC_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    recent = resp.json()["filings"]["recent"]

    filings = []
    for i in range(len(recent["form"])):
        if form_type and recent["form"][i].upper() != form_type.upper():
            continue
        accession_nodash = recent["accessionNumber"][i].replace("-", "")
        doc = recent["primaryDocument"][i]
        filings.append(
            {
                "form": recent["form"][i],
                "filingDate": recent["filingDate"][i],
                "reportDate": recent["reportDate"][i],
                "accessionNumber": recent["accessionNumber"][i],
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{doc}",
            }
        )
        if len(filings) >= limit:
            break

    return {"ticker": ticker.upper(), "cik": cik, "filings": filings}


@mcp.tool()
def search_filings_fulltext(
    query: str, forms: str | None = None, ticker: str | None = None, limit: int = 10
) -> dict:
    """Full-text search across SEC EDGAR filings for a keyword or phrase.

    Args:
        query: Search text, e.g. "supply chain constraints".
        forms: Optional comma-separated form types to restrict to, e.g. "10-K,10-Q".
        ticker: Optional ticker to restrict results to a single company.
        limit: Max number of results to return.
    """
    params: dict = {"q": query}
    if forms:
        params["forms"] = forms
    if ticker:
        cik = _cik_for_ticker(ticker)
        if cik is None:
            return {"error": f"No CIK found for ticker '{ticker}'"}
        params["ciks"] = cik

    resp = requests.get(
        "https://efts.sec.gov/LATEST/search-index",
        params=params,
        headers=SEC_HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    hits = resp.json().get("hits", {}).get("hits", [])

    results = []
    for hit in hits[:limit]:
        src = hit["_source"]
        accession_nodash = hit["_id"].split(":")[0].replace("-", "")
        doc = hit["_id"].split(":")[1] if ":" in hit["_id"] else ""
        cik = src.get("ciks", [None])[0]
        results.append(
            {
                "company": src.get("display_names", [None])[0],
                "form": src.get("forms", [None])[0] if isinstance(src.get("forms"), list) else src.get("form"),
                "filedDate": src.get("file_date"),
                "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{doc}"
                if cik and doc
                else None,
            }
        )

    return {"query": query, "count": len(results), "results": results}


@mcp.tool()
def get_filing_excerpt(url: str, max_chars: int = 5000) -> dict:
    """Fetch an SEC filing document and return readable plain text, stripped of HTML.

    Args:
        url: Filing document URL, typically from get_recent_filings or search_filings_fulltext.
        max_chars: Max characters of text to return (filings can be very long).
    """
    resp = requests.get(url, headers=SEC_HEADERS, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.content, "html.parser")
    # Inline XBRL filings embed a large block of structured tagging metadata in
    # <ix:header>, which a plain CSS-unaware parser would otherwise read as text.
    header = soup.find("ix:header")
    if header:
        header.decompose()
    for tag in soup(["script", "style"]):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()

    return {
        "url": url,
        "totalChars": len(text),
        "truncated": len(text) > max_chars,
        "text": text[:max_chars],
    }


if __name__ == "__main__":
    mcp.run()
