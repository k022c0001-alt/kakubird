import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.api.services.handlers.stock_research.analysis import (
    analyze_price_history,
)
from backend.api.services.handlers.stock_research.handler import (
    StockResearchHandler,
)
from backend.api.services.handlers.stock_research.providers import (
    EdinetReportProvider,
    UnavailableReportProvider,
    configured_report_provider,
)


class FakePriceProvider:
    def __init__(self, fail_symbols=()):
        self.fail_symbols = set(fail_symbols)

    def fetch_history(self, symbol):
        if symbol in self.fail_symbols:
            raise RuntimeError("source unavailable")
        return {
            "currency": "JPY",
            "observations": [
                {"date": "2026-07-01", "close": 100},
                {"date": "2026-07-02", "close": 110},
                {"date": "2026-07-03", "close": 105},
                {"date": "2026-07-04", "close": 115},
            ],
            "as_of": "2026-07-04",
            "retrieved_at": "2026-07-04T00:00:00+00:00",
            "source": "test price source",
            "source_url": "https://prices.example.test/7203.T",
        }


class FakeReportProvider:
    def fetch_reports(self, symbols):
        return {
            symbol: {
                "status": "unavailable",
                "reason": "No official reports are configured.",
                "source_url": "https://reports.example.test/",
                "reports": [],
            }
            for symbol in symbols
        }


class StockResearchAnalysisTests(unittest.TestCase):
    def test_counts_daily_direction_changes_and_alternations(self):
        analysis = analyze_price_history(
            [
                {"date": "2026-01-01", "close": 100},
                {"date": "2026-01-02", "close": 110},
                {"date": "2026-01-03", "close": 105},
                {"date": "2026-01-04", "close": 115},
                {"date": "2026-01-05", "close": 110},
                {"date": "2026-01-06", "close": None},
            ]
        )
        self.assertEqual(analysis["change_percent"], 10.0)
        self.assertEqual(analysis["up_moves"], 2)
        self.assertEqual(analysis["down_moves"], 2)
        self.assertEqual(analysis["alternating_moves"], 3)
        self.assertTrue(analysis["repeated_alternation"])
        self.assertEqual(analysis["observation_count"], 5)

    def test_requires_two_valid_observations(self):
        self.assertIsNone(
            analyze_price_history([{"date": "2026-01-01", "close": 100}])
        )


class StockResearchRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_routes_stock_research_but_not_unrelated_chat(self):
        handler = StockResearchHandler(
            price_provider=FakePriceProvider(),
            report_provider=FakeReportProvider(),
        )
        self.assertEqual(
            await handler.calculate_score("7203と6758の株価を調査"), 100
        )
        self.assertEqual(await handler.calculate_score("今日の天気は？"), 0)
        self.assertEqual(await handler.calculate_score("株式市場とは何ですか"), 0)

    async def test_requires_explicit_or_configured_universe(self):
        handler = StockResearchHandler(
            price_provider=FakePriceProvider(),
            report_provider=FakeReportProvider(),
        )
        with patch.dict(os.environ, {"STOCK_RESEARCH_UNIVERSE": ""}, clear=False):
            _, content = await handler.handle("日本株のトレンドを調査")
        self.assertEqual(
            content["stock_research"]["status"], "configuration_required"
        )
        self.assertIn("全上場銘柄", content["message"])

    async def test_returns_attributed_price_and_clear_financial_unavailability(self):
        handler = StockResearchHandler(
            price_provider=FakePriceProvider(),
            report_provider=FakeReportProvider(),
        )
        request = SimpleNamespace(message="7203と6758の株価・業績を調査")
        response_type, content = await handler.handle(request)
        result = content["stock_research"]
        self.assertEqual(response_type, "ui_code")
        self.assertEqual(content["blocks"][0]["type"], "StockResearchBlock")
        self.assertIs(content["blocks"][0]["props"]["data"], result)
        self.assertEqual(result["universe"]["symbols"], ["7203", "6758"])
        self.assertEqual(result["universe"]["coverage"], "configured/explicit universe only; not all Japanese listings")
        self.assertEqual(result["stocks"][0]["price"]["status"], "available")
        self.assertEqual(
            result["stocks"][0]["price"]["source_url"],
            "https://prices.example.test/7203.T",
        )
        self.assertEqual(result["stocks"][0]["price"]["as_of"], "2026-07-04")
        self.assertEqual(
            result["stocks"][0]["business_performance"]["status"],
            "unavailable",
        )
        self.assertIn("四半期", content["message"])
        self.assertEqual(result["status"], "partial")

    async def test_price_source_failure_is_not_reported_as_success(self):
        handler = StockResearchHandler(
            price_provider=FakePriceProvider(fail_symbols={"7203.T"}),
            report_provider=FakeReportProvider(),
        )
        _, content = await handler.handle("7203の株価トレンドを調査")
        price = content["stock_research"]["stocks"][0]["price"]
        self.assertEqual(price["status"], "unavailable")
        self.assertNotIn("change_percent", price)
        self.assertIn("source_url", price)

    async def test_rejects_unbounded_symbol_lists(self):
        handler = StockResearchHandler(
            price_provider=FakePriceProvider(),
            report_provider=FakeReportProvider(),
        )
        message = " ".join(f"{code:04d}" for code in range(1000, 1013))
        _, content = await handler.handle(message + " 株価分析")
        self.assertEqual(content["stock_research"]["status"], "invalid_universe")


class StockResearchProviderTests(unittest.TestCase):
    def test_missing_edinet_key_has_explicit_unavailable_state(self):
        with patch.dict(os.environ, {"EDINET_API_KEY": ""}, clear=False):
            provider = configured_report_provider()
        reports = provider.fetch_reports(["7203"])
        self.assertIsInstance(provider, UnavailableReportProvider)
        self.assertEqual(reports["7203"]["status"], "unavailable")
        self.assertIn("XBRL", reports["7203"]["reason"])
        self.assertTrue(reports["7203"]["source_url"].startswith("https://"))

    def test_edinet_only_labels_report_metadata_and_known_types(self):
        provider = EdinetReportProvider("test-key", lookback_days=200)
        self.assertEqual(provider.lookback_days, 90)
        self.assertTrue(provider._is_financial_report("第1四半期報告書"))
        self.assertFalse(provider._is_financial_report("大量保有報告書"))


if __name__ == "__main__":
    unittest.main()
