"""SEC filing retrieval for fundamentals-focused document RAG."""

from __future__ import annotations

import gzip
import json
import re
import urllib.request
import zlib
from html import unescape
from html.parser import HTMLParser
from typing import Any

from .config import get_config


SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{document}"
SUPPORTED_FORMS = ("10-K", "10-Q")


def get_fundamental_documents(
    ticker: str,
    curr_date: str,
) -> list:
    """Retrieve recent 10-K / 10-Q filing snippets for a ticker."""
    from .fundamentals_rag import chunk_document_text

    try:
        cik = _lookup_cik(ticker)
        if cik is None:
            return []
        submissions = _sec_get_json(SEC_SUBMISSIONS_URL.format(cik=cik))
        recent = (submissions.get("filings") or {}).get("recent") or {}
        filings = _recent_filings(recent, curr_date)
    except Exception:
        return []

    snippets = []
    for filing in filings:
        try:
            url = SEC_ARCHIVE_URL.format(
                cik_int=int(cik),
                accession=filing["accession_nodashes"],
                document=filing["primary_document"],
            )
            html = _sec_get_text(url)
            text = _extract_filing_text(html)
            if not text:
                continue
            title = f"{filing['form']} filed {filing['filing_date']}"
            snippets.extend(
                chunk_document_text(
                    text,
                    title=title,
                    doc_type=filing["form"],
                    filing_date=filing["filing_date"],
                    provider="sec",
                    source=url,
                )
            )
        except Exception:
            continue
    return snippets


def _lookup_cik(ticker: str) -> str | None:
    payload = _sec_get_json(SEC_TICKER_URL)
    target = ticker.upper()
    for item in payload.values():
        if str(item.get("ticker", "")).upper() == target:
            cik_number = int(item["cik_str"])
            return f"{cik_number:010d}"
    return None


def _recent_filings(recent: dict[str, list[Any]], curr_date: str) -> list[dict[str, str]]:
    forms = recent.get("form") or []
    filing_dates = recent.get("filingDate") or []
    accession_numbers = recent.get("accessionNumber") or []
    primary_documents = recent.get("primaryDocument") or []

    selected: list[dict[str, str]] = []
    seen_forms = set()
    for form, filing_date, accession_number, primary_document in zip(
        forms,
        filing_dates,
        accession_numbers,
        primary_documents,
    ):
        if form not in SUPPORTED_FORMS or filing_date > curr_date:
            continue
        key = (form, filing_date)
        if key in seen_forms:
            continue
        seen_forms.add(key)
        selected.append(
            {
                "form": form,
                "filing_date": filing_date,
                "accession_nodashes": accession_number.replace("-", ""),
                "primary_document": primary_document,
            }
        )
        if len(selected) >= 4:
            break
    return selected


def _extract_filing_text(html: str) -> str:
    parser = _SECTextExtractor()
    parser.feed(html)
    text = parser.get_text()
    text = unescape(text).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _sec_get_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_sec_headers())
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(_read_response_bytes(response).decode("utf-8"))


def _sec_get_text(url: str) -> str:
    request = urllib.request.Request(url, headers=_sec_headers())
    with urllib.request.urlopen(request, timeout=20) as response:
        return _read_response_bytes(response).decode("utf-8", errors="ignore")


def _read_response_bytes(response) -> bytes:
    body = response.read()
    encoding = str(response.headers.get("Content-Encoding", "")).lower()
    if encoding == "gzip":
        return gzip.decompress(body)
    if encoding == "deflate":
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def _sec_headers() -> dict[str, str]:
    config = get_config()
    return {
        "User-Agent": str(config.get("sec_user_agent")),
        "Accept-Encoding": "gzip, deflate",
    }


class _SECTextExtractor(HTMLParser):
    _BLOCK_TAGS = {"p", "div", "br", "li", "tr", "td", "section", "article", "h1", "h2", "h3", "h4"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style"} and self._ignored_depth > 0:
            self._ignored_depth -= 1
            return
        if self._ignored_depth == 0 and lowered in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and data.strip():
            self._parts.append(data.strip())

    def get_text(self) -> str:
        return " ".join(self._parts)
