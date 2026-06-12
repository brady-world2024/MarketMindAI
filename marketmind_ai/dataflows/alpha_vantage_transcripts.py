"""Alpha Vantage earnings call transcript retrieval for fundamentals RAG."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any

def get_fundamental_documents(
    ticker: str,
    curr_date: str,
) -> list:
    """Retrieve the latest available earnings call transcript snippets."""
    from .fundamentals_rag import chunk_document_text

    if not os.getenv("ALPHAVANTAGE_API_KEY", "").strip():
        return []

    quarter = _latest_available_quarter(ticker, curr_date)
    if quarter is None:
        return []

    try:
        payload = _parse_payload(
            _make_api_request(
                "EARNINGS_CALL_TRANSCRIPT",
                {"symbol": ticker, "quarter": quarter},
            )
        )
    except Exception:
        return []

    transcript_text = _extract_transcript_text(payload)
    if not transcript_text:
        return []

    filing_date = _extract_transcript_date(payload) or _quarter_to_date(quarter)
    title = f"Earnings call transcript {quarter}"
    return chunk_document_text(
        transcript_text,
        title=title,
        doc_type="earnings_call_transcript",
        filing_date=filing_date,
        provider="alpha_vantage",
        source=f"alpha_vantage:EARNINGS_CALL_TRANSCRIPT:{ticker}:{quarter}",
    )


def _latest_available_quarter(ticker: str, curr_date: str) -> str | None:
    try:
        payload = _parse_payload(_make_api_request("EARNINGS", {"symbol": ticker}))
    except Exception:
        return None

    quarterly = payload.get("quarterlyEarnings") or []
    candidates = []
    for item in quarterly:
        fiscal_date = item.get("fiscalDateEnding")
        if not fiscal_date or fiscal_date > curr_date:
            continue
        quarter = _date_to_quarter(fiscal_date)
        if quarter:
            candidates.append((fiscal_date, quarter))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def _make_api_request(function: str, params: dict[str, str]) -> dict:
    api_key = os.getenv("ALPHAVANTAGE_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ALPHAVANTAGE_API_KEY is not configured")
    query = {"function": function, "apikey": api_key, **params}
    url = "https://www.alphavantage.co/query?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 MarketMindAIRebuild/1.0",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _parse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        return json.loads(payload)
    raise ValueError(f"Unsupported payload type: {type(payload)}")


def _extract_transcript_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("transcript"), str):
        return payload["transcript"]

    transcript = payload.get("transcript")
    if isinstance(transcript, list):
        parts = []
        for item in transcript:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                speaker = item.get("speaker") or item.get("name") or item.get("role")
                text = item.get("content") or item.get("text") or item.get("statement")
                if speaker and text:
                    parts.append(f"{speaker}: {text}")
                elif text:
                    parts.append(str(text))
        if parts:
            return "\n".join(parts)

    for key in ("content", "text", "body"):
        value = payload.get(key)
        if isinstance(value, str):
            return value

    return ""


def _extract_transcript_date(payload: dict[str, Any]) -> str | None:
    for key in ("quarter", "fiscalDateEnding", "date", "reportedDate"):
        value = payload.get(key)
        if isinstance(value, str):
            if len(value) == 10:
                return value
            if value.endswith(("Q1", "Q2", "Q3", "Q4")):
                return _quarter_to_date(value)
    return None


def _date_to_quarter(date_str: str) -> str | None:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None
    quarter = (dt.month - 1) // 3 + 1
    return f"{dt.year}Q{quarter}"


def _quarter_to_date(quarter: str) -> str:
    year = int(quarter[:4])
    quarter_num = int(quarter[-1])
    month = quarter_num * 3
    return f"{year:04d}-{month:02d}-01"
