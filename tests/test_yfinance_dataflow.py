import unittest
from unittest.mock import Mock, patch

from marketmind_ai.dataflows.y_finance import get_fundamentals


class YFinanceDataflowTests(unittest.TestCase):
    @patch("marketmind_ai.dataflows.y_finance._http_json")
    @patch("marketmind_ai.dataflows.y_finance.yf")
    def test_get_fundamentals_prefers_yfinance_client_info(self, mock_yf, mock_http_json):
        ticker = Mock()
        ticker.info = {
            "longName": "NVIDIA Corporation",
            "sector": "Technology",
            "industry": "Semiconductors",
            "longBusinessSummary": "Accelerated computing platforms.",
            "marketCap": 1234567890,
            "trailingPE": 55.1,
            "forwardPE": 40.2,
            "priceToBook": 32.8,
            "revenueGrowth": 0.62,
            "grossMargins": 0.74,
            "operatingMargins": 0.52,
            "debtToEquity": 21.3,
            "currentRatio": 3.8,
            "freeCashflow": 987654321,
        }
        mock_yf.Ticker.return_value = ticker

        snapshot = get_fundamentals("NVDA")

        self.assertEqual(snapshot.company_name, "NVIDIA Corporation")
        self.assertEqual(snapshot.sector, "Technology")
        self.assertEqual(snapshot.industry, "Semiconductors")
        self.assertAlmostEqual(snapshot.market_cap or 0.0, 1234567890.0)
        self.assertAlmostEqual(snapshot.trailing_pe or 0.0, 55.1)
        self.assertAlmostEqual(snapshot.free_cashflow or 0.0, 987654321.0)
        mock_http_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
