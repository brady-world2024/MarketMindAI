import os
import unittest
from unittest.mock import patch

from marketmind_ai.dataflows.alpha_vantage import get_indicator, get_stock
from marketmind_ai.dataflows.alpha_vantage_common import (
    AlphaVantageRateLimitError,
    _raise_for_alpha_vantage_errors,
    format_datetime_for_api,
    get_api_key,
)
from marketmind_ai.dataflows.alpha_vantage_news import get_insider_transactions


class AlphaVantageDataflowTests(unittest.TestCase):
    def test_get_api_key_prefers_reference_env_name(self):
        with patch.dict(
            os.environ,
            {
                "ALPHA_VANTAGE_API_KEY": "reference-key",
                "ALPHAVANTAGE_API_KEY": "legacy-key",
            },
            clear=False,
        ):
            self.assertEqual(get_api_key(), "reference-key")

    def test_get_api_key_supports_legacy_env_name(self):
        with patch.dict(os.environ, {"ALPHAVANTAGE_API_KEY": "legacy-key"}, clear=True):
            self.assertEqual(get_api_key(), "legacy-key")

    def test_format_datetime_for_api_matches_reference_shape(self):
        self.assertEqual(format_datetime_for_api("2026-06-12"), "20260612T0000")
        self.assertEqual(format_datetime_for_api("2026-06-12 09:45"), "20260612T0945")

    def test_rate_limit_error_is_promoted(self):
        with self.assertRaises(AlphaVantageRateLimitError):
            _raise_for_alpha_vantage_errors({"Information": "Thank you for using Alpha Vantage! Our standard API call frequency is 25 requests per day."})

    @patch("marketmind_ai.dataflows.alpha_vantage_news._make_api_request")
    def test_insider_transactions_are_rendered_as_human_readable_lines(self, mock_request):
        mock_request.return_value = {
            "data": [
                {
                    "transaction_date": "2026-01-12",
                    "insider_name": "Jane Doe",
                    "transaction_type": "Buy",
                    "shares": "1500",
                    "share_price": "201.25",
                }
            ]
        }

        rendered = get_insider_transactions("NVDA", "2026-06-12")

        self.assertIn("2026-01-12", rendered)
        self.assertIn("Jane Doe", rendered)
        self.assertIn("Buy", rendered)
        self.assertIn("shares=1500", rendered)
        self.assertIn("price=201.25", rendered)

    @patch("marketmind_ai.dataflows.alpha_vantage.get_price_history", return_value=["bar"])
    def test_aggregate_module_exposes_reference_style_get_stock(self, mock_get_price_history):
        result = get_stock("NVDA", "2026-06-12", lookback_days=30)

        self.assertEqual(result, ["bar"])
        mock_get_price_history.assert_called_once_with("NVDA", "2026-06-12", lookback_days=30)

    @patch("marketmind_ai.dataflows.alpha_vantage.get_indicators", return_value="rsi: 61.2")
    def test_aggregate_module_exposes_reference_style_get_indicator(self, mock_get_indicators):
        result = get_indicator("NVDA", "2026-06-12", indicators=["rsi"])

        self.assertEqual(result, "rsi: 61.2")
        mock_get_indicators.assert_called_once_with("NVDA", "2026-06-12", indicators=["rsi"])


if __name__ == "__main__":
    unittest.main()
