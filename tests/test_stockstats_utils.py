import unittest
from datetime import date, timedelta

from marketmind_ai.agents.utils.research_types import PriceBar
from marketmind_ai.dataflows.stockstats_utils import bars_to_dataframe, render_indicator_report


def _sample_bars(count: int = 260) -> list[PriceBar]:
    start = date(2025, 1, 1)
    bars: list[PriceBar] = []
    for index in range(count):
        close = 100.0 + (index * 0.55) + ((index % 7) * 0.08)
        bars.append(
            PriceBar(
                date=(start + timedelta(days=index)).isoformat(),
                open=round(close - 0.45, 2),
                high=round(close + 1.25, 2),
                low=round(close - 1.15, 2),
                close=round(close, 2),
                volume=1_000_000 + (index * 2_500),
            )
        )
    return bars


class StockstatsUtilsTests(unittest.TestCase):
    def test_bars_to_dataframe_uses_stockstats_friendly_columns(self):
        frame = bars_to_dataframe(_sample_bars(5))

        self.assertEqual(list(frame.columns), ["date", "open", "high", "low", "close", "volume"])
        self.assertEqual(len(frame), 5)

    def test_render_indicator_report_returns_numeric_values_for_core_indicators(self):
        report = render_indicator_report(
            _sample_bars(),
            ["close_50_sma", "close_200_sma", "rsi", "atr", "vwma", "volatility_20"],
        )

        parsed = {}
        for line in report.splitlines():
            name, raw_value = line.split(": ", 1)
            self.assertNotEqual(raw_value, "None", msg=f"{name} should produce a numeric value")
            parsed[name] = float(raw_value)

        self.assertGreater(parsed["close_50_sma"], 0.0)
        self.assertGreater(parsed["close_200_sma"], 0.0)
        self.assertGreater(parsed["rsi"], 0.0)
        self.assertGreater(parsed["atr"], 0.0)
        self.assertGreater(parsed["vwma"], 0.0)
        self.assertGreater(parsed["volatility_20"], 0.0)


if __name__ == "__main__":
    unittest.main()
