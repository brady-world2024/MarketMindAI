import unittest

from marketmind_ai.symbols.models import (
    FundamentalValidationResult,
    PriceValidationResult,
    ResolveStatus,
    SymbolCandidate,
)
from marketmind_ai.symbols.resolver import SymbolResolver


class FakeResolver(SymbolResolver):
    def __init__(self, candidates, price_results, fundamental_results):
        super().__init__(provider=None)
        self._candidates = candidates
        self._price_results = price_results
        self._fundamental_results = fundamental_results

    def search_symbols(self, query: str, limit: int = 10):
        return self._candidates[:limit]

    def validate_price_data(self, symbol: str, trade_date: str, provider=None):
        return self._price_results[symbol]

    def validate_fundamental_data(self, symbol: str, trade_date: str, provider=None):
        return self._fundamental_results[symbol]


def _valid_price():
    return PriceValidationResult(
        valid=True,
        latest_quote_exists=True,
        latest_price=100.0,
        recent_history_exists=True,
        history_points=20,
        stale=False,
        latest_trade_date="2026-05-01",
    )


def _valid_fundamentals(name: str, exchange: str = "NASDAQ"):
    return FundamentalValidationResult(
        valid=True,
        company_profile_exists=True,
        company_name_exists=True,
        exchange_exists=True,
        financial_statements_exist=True,
        income_statement_exists=True,
        balance_sheet_exists=True,
        cashflow_exists=True,
        company_name=name,
        exchange=exchange,
        region="United States",
        currency="USD",
    )


class SymbolResolverPackageTests(unittest.TestCase):
    def test_input_aapl_resolves_to_apple_inc(self):
        resolver = FakeResolver(
            candidates=[
                SymbolCandidate(symbol="AAPL", name="Apple Inc", exchange="NASDAQ", type="EQUITY"),
                SymbolCandidate(symbol="APLE", name="Apple Hospitality REIT", exchange="NYSE", type="EQUITY"),
            ],
            price_results={"AAPL": _valid_price(), "APLE": _valid_price()},
            fundamental_results={
                "AAPL": _valid_fundamentals("Apple Inc"),
                "APLE": _valid_fundamentals("Apple Hospitality REIT", exchange="NYSE"),
            },
        )

        resolved = resolver.resolve("AAPL", "2026-05-01")
        self.assertEqual(resolved.status, ResolveStatus.RESOLVED)
        self.assertEqual(resolved.resolved_symbol, "AAPL")
        self.assertEqual(resolved.company_name, "Apple Inc")

    def test_input_company_name_resolves_to_primary_equity(self):
        resolver = FakeResolver(
            candidates=[
                SymbolCandidate(symbol="AAPL", name="Apple Inc", exchange="NASDAQ", type="EQUITY"),
                SymbolCandidate(symbol="APLE", name="Apple Hospitality REIT", exchange="NYSE", type="EQUITY"),
            ],
            price_results={"AAPL": _valid_price(), "APLE": _valid_price()},
            fundamental_results={
                "AAPL": _valid_fundamentals("Apple Inc"),
                "APLE": _valid_fundamentals("Apple Hospitality REIT", exchange="NYSE"),
            },
        )

        resolved = resolver.resolve("Apple", "2026-05-01")
        self.assertEqual(resolved.status, ResolveStatus.RESOLVED)
        self.assertEqual(resolved.resolved_symbol, "AAPL")

    def test_invalid_input_returns_not_found(self):
        resolver = FakeResolver(candidates=[], price_results={}, fundamental_results={})
        resolved = resolver.resolve("does-not-exist", "2026-05-01")
        self.assertEqual(resolved.status, ResolveStatus.NOT_FOUND)

    def test_multiple_similar_candidates_return_ambiguous(self):
        resolver = FakeResolver(
            candidates=[
                SymbolCandidate(symbol="ALFA", name="Alpha Beta Plc", exchange="LSE", type="EQUITY"),
                SymbolCandidate(symbol="ALFB", name="Alpha Beta Ltd", exchange="TSX", type="EQUITY"),
            ],
            price_results={"ALFA": _valid_price(), "ALFB": _valid_price()},
            fundamental_results={
                "ALFA": _valid_fundamentals("Alpha Beta Plc", exchange="LSE"),
                "ALFB": _valid_fundamentals("Alpha Beta Ltd", exchange="TSX"),
            },
        )

        resolved = resolver.resolve("Alpha Beta", "2026-05-01")
        self.assertEqual(resolved.status, ResolveStatus.AMBIGUOUS)
        self.assertGreaterEqual(len(resolved.candidates), 2)

    def test_symbol_with_no_price_data_returns_insufficient_data(self):
        resolver = FakeResolver(
            candidates=[SymbolCandidate(symbol="AAPL", name="Apple Inc", exchange="NASDAQ", type="EQUITY")],
            price_results={
                "AAPL": PriceValidationResult(
                    valid=False,
                    latest_quote_exists=False,
                    recent_history_exists=False,
                    reason="No price data.",
                )
            },
            fundamental_results={"AAPL": _valid_fundamentals("Apple Inc")},
        )

        resolved = resolver.resolve("Apple", "2026-05-01")
        self.assertEqual(resolved.status, ResolveStatus.INSUFFICIENT_DATA)
        self.assertFalse(resolved.validation.price_data)


if __name__ == "__main__":
    unittest.main()
