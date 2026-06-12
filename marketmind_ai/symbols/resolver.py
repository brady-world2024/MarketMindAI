from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Optional

from ..dataflows.interface import collect_from_vendors, get_fallback_vendors, invoke_vendor_method
from ..dataflows.utils import safe_ticker_component
from .models import (
    FundamentalValidationResult,
    PriceValidationResult,
    ResolveStatus,
    ResolvedTicker,
    SymbolCandidate,
    ValidationFlags,
)


logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "stock",
    "stocks",
    "share",
    "shares",
    "equity",
    "common",
    "ordinary",
    "class",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "holdings",
    "holding",
    "plc",
    "limited",
    "ltd",
}


class TickerResolutionError(ValueError):
    def __init__(self, resolved: ResolvedTicker):
        self.resolved = resolved
        super().__init__(format_resolution_message(resolved))


@dataclass
class _RankedCandidate:
    candidate: SymbolCandidate
    base_score: float
    final_score: float
    name_similarity: float
    price_validation: PriceValidationResult
    fundamental_validation: FundamentalValidationResult


def _normalize_query(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        raise ValueError("query cannot be empty")
    if len(cleaned) > 128:
        raise ValueError("query is too long")
    if any(ch in cleaned for ch in ("\x00", "\n", "\r", "\t")):
        raise ValueError("query contains unsupported control characters")
    return cleaned


def _normalize_for_name_match(value: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(value.lower()) if token not in _STOPWORDS]
    return " ".join(tokens)


def _coerce_score(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    score = float(value)
    if score > 1:
        score /= 100.0
    return max(0.0, min(score, 1.0))


def _equity_bonus(candidate_type: Optional[str]) -> float:
    type_text = (candidate_type or "").lower()
    if "equity" in type_text or "stock" in type_text:
        return 18.0
    if "etf" in type_text:
        return 6.0
    if not type_text:
        return 0.0
    return -8.0


def format_resolution_message(resolved: ResolvedTicker) -> str:
    if resolved.status == ResolveStatus.RESOLVED and resolved.resolved_symbol:
        if resolved.original_input.strip().upper() == resolved.resolved_symbol.upper():
            return f'Validated "{resolved.resolved_symbol}" as {resolved.company_name or resolved.resolved_symbol}.'
        return (
            f'Input "{resolved.original_input}" was resolved to '
            f'"{resolved.resolved_symbol} — {resolved.company_name or resolved.resolved_symbol}".'
        )

    lines = [f'We could not verify "{resolved.original_input}" as a valid listed ticker.']
    if resolved.reason:
        lines.append(resolved.reason)

    if resolved.candidates:
        lines.append("")
        lines.append("Did you mean:")
        for index, candidate in enumerate(resolved.candidates[:5], start=1):
            exchange = candidate.exchange or candidate.region or "Unknown market"
            region = f" — {candidate.region}" if candidate.region else ""
            lines.append(
                f"{index}. {candidate.symbol} — {candidate.name} — {exchange}{region}"
            )

    lines.append("Please confirm the symbol before generating the report.")
    return "\n".join(lines)


class SymbolResolver:
    def __init__(self, provider: object | None = None) -> None:
        self.provider = provider

    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolCandidate]:
        normalized_query = _normalize_query(query)
        if self.provider is not None and hasattr(self.provider, "search_symbols"):
            raw_candidates = getattr(self.provider, "search_symbols")(normalized_query, limit=limit)
        else:
            raw_candidates = collect_from_vendors("search_symbols", normalized_query, limit=limit)

        deduped: dict[tuple[str, str, str], SymbolCandidate] = {}
        for item in raw_candidates:
            candidate = item if isinstance(item, SymbolCandidate) else SymbolCandidate.model_validate(item)
            try:
                safe_ticker_component(candidate.symbol)
            except ValueError:
                continue

            key = (
                candidate.symbol.upper(),
                (candidate.exchange or "").upper(),
                (candidate.region or "").upper(),
            )
            existing = deduped.get(key)
            if existing is None:
                deduped[key] = candidate
                continue

            existing_score = _coerce_score(existing.match_score)
            new_score = _coerce_score(candidate.match_score)
            if new_score > existing_score:
                deduped[key] = candidate

        candidates = list(deduped.values())
        logger.info(
            "symbol_search %s",
            json.dumps(
                {
                    "query": query,
                    "normalized_query": normalized_query,
                    "candidate_count": len(candidates),
                    "candidates": [candidate.model_dump(mode="json") for candidate in candidates[:8]],
                },
                ensure_ascii=False,
            ),
        )
        return candidates[:limit]

    def validate_price_data(
        self,
        symbol: str,
        trade_date: str,
        provider: Optional[str] = None,
    ) -> PriceValidationResult:
        if self.provider is not None and hasattr(self.provider, "validate_price_data"):
            try:
                result = getattr(self.provider, "validate_price_data")(symbol, trade_date)
                return self._coerce_price_validation(result, symbol, trade_date)
            except Exception as exc:
                logger.warning("price_validation_provider_error symbol=%s provider=self error=%s", symbol, exc)

        providers = []
        if provider:
            providers.append(provider)
        providers.extend(get_fallback_vendors("validate_price_data"))

        seen: set[str] = set()
        for vendor in providers:
            if vendor in seen or vendor == "provider":
                continue
            seen.add(vendor)
            try:
                result = invoke_vendor_method("validate_price_data", vendor, symbol, trade_date)
            except Exception as exc:
                logger.warning("price_validation_provider_error symbol=%s vendor=%s error=%s", symbol, vendor, exc)
                continue
            if result is None:
                continue
            return self._coerce_price_validation(result, symbol, trade_date)

        return PriceValidationResult(valid=False, reason="No provider could validate price data.")

    def validate_fundamental_data(
        self,
        symbol: str,
        trade_date: str,
        provider: Optional[str] = None,
    ) -> FundamentalValidationResult:
        if self.provider is not None and hasattr(self.provider, "validate_fundamental_data"):
            try:
                result = getattr(self.provider, "validate_fundamental_data")(symbol, trade_date)
                return self._coerce_fundamental_validation(result, symbol)
            except Exception as exc:
                logger.warning("fundamental_validation_provider_error symbol=%s provider=self error=%s", symbol, exc)

        providers = []
        if provider:
            providers.append(provider)
        providers.extend(get_fallback_vendors("validate_fundamental_data"))

        seen: set[str] = set()
        for vendor in providers:
            if vendor in seen or vendor == "provider":
                continue
            seen.add(vendor)
            try:
                result = invoke_vendor_method("validate_fundamental_data", vendor, symbol, trade_date)
            except Exception as exc:
                logger.warning(
                    "fundamental_validation_provider_error symbol=%s vendor=%s error=%s",
                    symbol,
                    vendor,
                    exc,
                )
                continue
            if result is None:
                continue
            return self._coerce_fundamental_validation(result, symbol)

        return FundamentalValidationResult(valid=False, reason="No provider could validate fundamental data.")

    def resolve(
        self,
        raw_input: str,
        trade_date: str,
        *,
        limit: int = 8,
    ) -> ResolvedTicker:
        normalized_query = _normalize_query(raw_input)
        candidates = self.search_symbols(normalized_query, limit=limit)
        if not candidates:
            resolved = ResolvedTicker(
                status=ResolveStatus.NOT_FOUND,
                original_input=raw_input,
                normalized_query=normalized_query,
                reason="No matching symbols were returned by the configured market data providers.",
            )
            self._log_result(resolved)
            return resolved

        ranked = self._rank_and_validate(normalized_query, trade_date, candidates)
        validated = [item for item in ranked if item.price_validation.valid]

        if not validated:
            best = ranked[0]
            resolved = ResolvedTicker(
                status=ResolveStatus.INSUFFICIENT_DATA,
                original_input=raw_input,
                normalized_query=normalized_query,
                resolved_symbol=best.candidate.symbol,
                company_name=best.candidate.name,
                exchange=best.candidate.exchange,
                region=best.candidate.region,
                currency=best.candidate.currency,
                confidence=max(0.0, round(best.final_score, 2)),
                candidates=[item.candidate for item in ranked[:5]],
                reason=best.price_validation.reason or "Matched symbols were found, but none had valid recent market data.",
                validation=ValidationFlags(price_data=False, fundamental_data=False),
            )
            self._log_result(resolved, ranked)
            return resolved

        top = validated[0]
        second = validated[1] if len(validated) > 1 else None

        if not top.fundamental_validation.valid:
            resolved = ResolvedTicker(
                status=ResolveStatus.INSUFFICIENT_DATA,
                original_input=raw_input,
                normalized_query=normalized_query,
                resolved_symbol=top.candidate.symbol,
                company_name=top.candidate.name,
                exchange=top.candidate.exchange,
                region=top.candidate.region,
                currency=top.candidate.currency,
                confidence=max(0.0, round(top.final_score, 2)),
                candidates=[item.candidate for item in ranked[:5]],
                reason=top.fundamental_validation.reason or "The selected symbol does not have sufficient company or financial data.",
                validation=ValidationFlags(price_data=True, fundamental_data=False),
            )
            self._log_result(resolved, ranked)
            return resolved

        query_name = _normalize_for_name_match(normalized_query)
        exact_symbol = top.candidate.symbol.upper() == normalized_query.upper()
        exact_company = _normalize_for_name_match(top.candidate.name) == query_name
        second_exact_company = (
            second is not None
            and _normalize_for_name_match(second.candidate.name) == query_name
        )
        multiple_exact_company_matches = bool(second is not None and exact_company and second_exact_company)
        close_second = (
            second is not None
            and second.fundamental_validation.valid
            and second.price_validation.valid
            and abs(top.final_score - second.final_score) < 8
            and not exact_symbol
            and (multiple_exact_company_matches or not exact_company)
        )
        if close_second:
            resolved = ResolvedTicker(
                status=ResolveStatus.AMBIGUOUS,
                original_input=raw_input,
                normalized_query=normalized_query,
                candidates=[item.candidate for item in validated[:5]],
                reason="Multiple matching listed symbols passed validation with similar confidence scores.",
                validation=ValidationFlags(price_data=True, fundamental_data=True),
            )
            self._log_result(resolved, ranked)
            return resolved

        margin = top.final_score - (second.final_score if second is not None else 0.0)
        confidence = min(99.0, max(50.0, round(top.final_score + min(margin, 20.0), 2)))
        resolved = ResolvedTicker(
            status=ResolveStatus.RESOLVED,
            original_input=raw_input,
            normalized_query=normalized_query,
            resolved_symbol=top.candidate.symbol,
            company_name=top.fundamental_validation.company_name or top.candidate.name,
            exchange=top.fundamental_validation.exchange or top.candidate.exchange,
            region=top.fundamental_validation.region or top.candidate.region,
            currency=top.fundamental_validation.currency or top.candidate.currency,
            confidence=confidence,
            candidates=[item.candidate for item in ranked[:5]],
            reason=(
                f'Input "{raw_input}" was resolved to "{top.candidate.symbol} — '
                f'{top.fundamental_validation.company_name or top.candidate.name}" based on symbol lookup and market data validation.'
            ),
            validation=ValidationFlags(price_data=True, fundamental_data=True),
        )
        self._log_result(resolved, ranked)
        return resolved

    def _rank_and_validate(
        self,
        query: str,
        trade_date: str,
        candidates: Iterable[SymbolCandidate],
    ) -> list[_RankedCandidate]:
        ranked: list[_RankedCandidate] = []
        for candidate in candidates:
            base_score, similarity = self._score_candidate(query, candidate)
            price_validation = self.validate_price_data(
                candidate.symbol,
                trade_date,
                provider=candidate.provider,
            )
            fundamental_validation = self.validate_fundamental_data(
                candidate.symbol,
                trade_date,
                provider=candidate.provider,
            )
            final_score = base_score
            if price_validation.valid:
                final_score += 35.0
            if fundamental_validation.valid:
                final_score += 25.0

            ranked.append(
                _RankedCandidate(
                    candidate=candidate,
                    base_score=base_score,
                    final_score=final_score,
                    name_similarity=similarity,
                    price_validation=price_validation,
                    fundamental_validation=fundamental_validation,
                )
            )

        ranked.sort(key=lambda item: item.final_score, reverse=True)
        return ranked

    def _score_candidate(self, query: str, candidate: SymbolCandidate) -> tuple[float, float]:
        query_upper = query.strip().upper()
        query_name = _normalize_for_name_match(query)
        candidate_name = _normalize_for_name_match(candidate.name)
        similarity = SequenceMatcher(None, query_name or query.lower(), candidate_name or "").ratio()

        score = 0.0
        if candidate.symbol.upper() == query_upper:
            score += 140.0
        if query_name and candidate_name:
            if query_name == candidate_name:
                score += 120.0
            elif candidate_name.startswith(query_name):
                score += 80.0
            elif query_name in candidate_name:
                score += 60.0

            query_tokens = set(query_name.split())
            candidate_tokens = set(candidate_name.split())
            overlap = len(query_tokens & candidate_tokens) / max(len(query_tokens), 1)
            score += overlap * 30.0
            score += similarity * 40.0

        score += _coerce_score(candidate.match_score) * 25.0
        score += _equity_bonus(candidate.type)
        if candidate.exchange:
            score += 4.0
        if candidate.region:
            score += 2.0

        return score, similarity

    def _log_result(
        self,
        resolved: ResolvedTicker,
        ranked: Optional[list[_RankedCandidate]] = None,
    ) -> None:
        payload: dict[str, object] = resolved.model_dump(mode="json")
        if ranked is not None:
            payload["ranked_candidates"] = [
                {
                    "candidate": item.candidate.model_dump(mode="json"),
                    "base_score": round(item.base_score, 2),
                    "final_score": round(item.final_score, 2),
                    "price_validation": item.price_validation.model_dump(mode="json"),
                    "fundamental_validation": item.fundamental_validation.model_dump(mode="json"),
                }
                for item in ranked[:5]
            ]
        logger.info("symbol_resolution_result %s", json.dumps(payload, ensure_ascii=False))

    @staticmethod
    def _coerce_price_validation(result: object, symbol: str, trade_date: str) -> PriceValidationResult:
        if isinstance(result, PriceValidationResult):
            return result
        if isinstance(result, dict):
            return PriceValidationResult.model_validate(result)
        if isinstance(result, bool):
            return PriceValidationResult(
                valid=result,
                latest_quote_exists=result,
                recent_history_exists=result,
                history_points=20 if result else 0,
                stale=False,
                latest_trade_date=trade_date if result else None,
                reason=None if result else f"No provider could validate recent price data for {symbol}.",
            )
        return PriceValidationResult(valid=False, reason=f"Unsupported price validation result for {symbol}.")

    @staticmethod
    def _coerce_fundamental_validation(result: object, symbol: str) -> FundamentalValidationResult:
        if isinstance(result, FundamentalValidationResult):
            return result
        if isinstance(result, dict):
            return FundamentalValidationResult.model_validate(result)
        if isinstance(result, bool):
            return FundamentalValidationResult(
                valid=result,
                company_profile_exists=result,
                company_name_exists=result,
                exchange_exists=result,
                financial_statements_exist=result,
                income_statement_exists=result,
                balance_sheet_exists=result,
                cashflow_exists=result,
                reason=None if result else f"No provider could validate fundamentals for {symbol}.",
            )
        return FundamentalValidationResult(valid=False, reason=f"Unsupported fundamental validation result for {symbol}.")
