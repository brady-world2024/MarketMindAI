"""Fundamentals-focused document retrieval and lightweight RAG helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
from typing import Iterable

from .config import get_config
from .interface import collect_from_vendors


@dataclass
class FundamentalDocumentSnippet:
    source: str
    doc_type: str
    filing_date: str
    title: str
    text: str
    provider: str


_DEFAULT_QUERY = (
    "revenue growth margins profitability cash flow liquidity debt guidance "
    "demand outlook risks capital allocation segments competitive position"
)
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SECTION_PATTERNS = (
    (re.compile(r"\bitem\s+1a\b", re.IGNORECASE), "Risk Factors"),
    (re.compile(r"\bitem\s+1\b", re.IGNORECASE), "Business Overview"),
    (re.compile(r"\bitem\s+2\b", re.IGNORECASE), "Management Discussion"),
    (re.compile(r"\bitem\s+7a\b", re.IGNORECASE), "Market Risk"),
    (re.compile(r"\bitem\s+7\b", re.IGNORECASE), "MD&A"),
    (re.compile(r"\bitem\s+8\b", re.IGNORECASE), "Financial Statements"),
)
_DOC_TYPE_WEIGHT = {
    "earnings_call_transcript": 1.15,
    "10-Q": 1.05,
    "10-K": 0.95,
}


def build_fundamental_document_context(
    ticker: str,
    curr_date: str,
    query: str | None = None,
    *,
    provider=None,
) -> str:
    """Collect, rank, and render fundamental document snippets."""
    config = get_config()
    if not config.get("fundamentals_rag_enabled", True):
        return "Fundamental document RAG is disabled in the current configuration."

    snippets = collect_from_vendors(
        "get_fundamental_documents",
        ticker,
        curr_date,
    )
    unique = _dedupe_snippets(_coerce_snippets(snippets))
    if not unique:
        return (
            f"No filing or transcript documents were available for `{ticker}` on or before {curr_date}. "
            "Proceed with statement-based fundamental analysis only."
        )

    selected = rank_fundamental_document_snippets(
        unique,
        query=query or _DEFAULT_QUERY,
        curr_date=curr_date,
        limit=int(config.get("fundamentals_rag_max_chunks", 6)),
    )
    if not selected:
        return (
            f"Documents were found for `{ticker}`, but none produced useful chunks for the current fundamentals query."
        )

    lines = [
        f"# Fundamental document evidence for {ticker}",
        f"# Retrieved {len(unique)} document chunks; showing top {len(selected)} ranked snippets.",
        "",
    ]
    for index, snippet in enumerate(selected, start=1):
        lines.extend(
            [
                f"## {index}. {snippet.title}",
                f"- Source: {snippet.source}",
                f"- Type: {snippet.doc_type}",
                f"- Date: {snippet.filing_date}",
                f"- Provider: {snippet.provider}",
                snippet.text.strip(),
                "",
            ]
        )
    return "\n".join(lines).strip()


def rank_fundamental_document_snippets(
    snippets: Iterable[FundamentalDocumentSnippet],
    query: str,
    curr_date: str,
    limit: int = 6,
) -> list[FundamentalDocumentSnippet]:
    """Rank snippets using keyword overlap, recency, and document type priors."""
    query_tokens = set(_TOKEN_RE.findall(query.lower())) or set(_TOKEN_RE.findall(_DEFAULT_QUERY))
    ranked = []
    for snippet in snippets:
        text_tokens = set(_TOKEN_RE.findall(snippet.text.lower()))
        overlap = len(query_tokens & text_tokens)
        if overlap == 0 and len(text_tokens) < 10:
            continue
        score = float(overlap)
        score += _DOC_TYPE_WEIGHT.get(snippet.doc_type, 0.8)
        score += _recency_weight(snippet.filing_date, curr_date)
        score += _keyword_bonus(snippet.text)
        ranked.append((score, snippet))

    ranked.sort(
        key=lambda item: (
            item[0],
            item[1].filing_date,
            len(item[1].text),
        ),
        reverse=True,
    )
    return [snippet for _, snippet in ranked[:limit]]


def chunk_document_text(
    text: str,
    title: str,
    doc_type: str,
    filing_date: str,
    provider: str,
    source: str,
    max_chars: int | None = None,
) -> list[FundamentalDocumentSnippet]:
    """Chunk filing/transcript text into retrievable snippets."""
    config = get_config()
    max_chars = max_chars or int(config.get("fundamentals_rag_chunk_chars", 1400))
    normalized = _normalize_text(text)
    if not normalized:
        return []

    section_chunks = _extract_section_chunks(
        normalized,
        title=title,
        doc_type=doc_type,
        filing_date=filing_date,
        provider=provider,
        source=source,
        max_chars=max_chars,
    )
    if section_chunks:
        return section_chunks

    return _chunk_by_paragraphs(
        normalized,
        title=title,
        doc_type=doc_type,
        filing_date=filing_date,
        provider=provider,
        source=source,
        max_chars=max_chars,
    )


def _extract_section_chunks(
    text: str,
    *,
    title: str,
    doc_type: str,
    filing_date: str,
    provider: str,
    source: str,
    max_chars: int,
) -> list[FundamentalDocumentSnippet]:
    matches = []
    for pattern, label in _SECTION_PATTERNS:
        match = pattern.search(text)
        if match:
            matches.append((match.start(), label))

    if not matches:
        return []

    matches.sort(key=lambda item: item[0])
    chunks = []
    for index, (start, label) in enumerate(matches):
        end = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        snippet_text = text[start:end].strip()
        if len(snippet_text) > max_chars:
            snippet_text = snippet_text[:max_chars].rsplit(" ", 1)[0].strip()
        if len(snippet_text) < 120:
            continue
        chunks.append(
            FundamentalDocumentSnippet(
                source=source,
                doc_type=doc_type,
                filing_date=filing_date,
                title=f"{title} — {label}",
                text=snippet_text,
                provider=provider,
            )
        )
    return chunks


def _chunk_by_paragraphs(
    text: str,
    *,
    title: str,
    doc_type: str,
    filing_date: str,
    provider: str,
    source: str,
    max_chars: int,
) -> list[FundamentalDocumentSnippet]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks = []
    buffer = []
    buffer_len = 0
    part = 1
    for paragraph in paragraphs:
        if buffer and buffer_len + len(paragraph) > max_chars:
            combined = "\n\n".join(buffer)
            chunks.append(
                FundamentalDocumentSnippet(
                    source=source,
                    doc_type=doc_type,
                    filing_date=filing_date,
                    title=f"{title} — Part {part}",
                    text=combined,
                    provider=provider,
                )
            )
            part += 1
            buffer = [paragraph]
            buffer_len = len(paragraph)
            continue

        buffer.append(paragraph)
        buffer_len += len(paragraph)

    if buffer:
        combined = "\n\n".join(buffer)
        chunks.append(
            FundamentalDocumentSnippet(
                source=source,
                doc_type=doc_type,
                filing_date=filing_date,
                title=f"{title} — Part {part}",
                text=combined,
                provider=provider,
            )
        )
    return chunks


def _coerce_snippets(items: Iterable[FundamentalDocumentSnippet | dict]) -> list[FundamentalDocumentSnippet]:
    snippets: list[FundamentalDocumentSnippet] = []
    for item in items:
        if isinstance(item, FundamentalDocumentSnippet):
            snippets.append(item)
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        snippets.append(
            FundamentalDocumentSnippet(
                source=str(item.get("source", "unknown")),
                doc_type=str(item.get("doc_type", "unknown")),
                filing_date=str(item.get("filing_date", "")),
                title=str(item.get("title", "Untitled document")),
                text=text,
                provider=str(item.get("provider", "unknown")),
            )
        )
    return snippets


def _normalize_text(text: str) -> str:
    text = text.replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _keyword_bonus(text: str) -> float:
    lowered = text.lower()
    bonus_terms = (
        "revenue",
        "margin",
        "cash flow",
        "guidance",
        "outlook",
        "demand",
        "liquidity",
        "debt",
        "capex",
    )
    return sum(0.25 for term in bonus_terms if term in lowered)


def _recency_weight(filing_date: str, curr_date: str) -> float:
    try:
        filing_dt = datetime.strptime(filing_date, "%Y-%m-%d")
        current_dt = datetime.strptime(curr_date, "%Y-%m-%d")
    except ValueError:
        return 0.0

    delta_days = max((current_dt - filing_dt).days, 0)
    return 1.0 / (1.0 + math.log1p(delta_days))


def _dedupe_snippets(snippets: Iterable[FundamentalDocumentSnippet]) -> list[FundamentalDocumentSnippet]:
    seen = set()
    unique = []
    for snippet in snippets:
        key = (
            snippet.source,
            snippet.doc_type,
            snippet.filing_date,
            snippet.title,
            snippet.text[:240],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(snippet)
    return unique
