import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from marketmind_ai.agents.analysts.news import create_news_analyst
from marketmind_ai.dataflows.alpha_vantage_news import _extract_feed_items
from marketmind_ai.dataflows.news_rag import (
    NewsEventSnippet,
    build_news_event_timeline,
    rank_news_event_snippets,
)
from marketmind_ai.dataflows.yfinance_news import (
    get_global_news_documents_yfinance,
    get_news_documents_yfinance,
)


def _event(
    *,
    title: str,
    summary: str,
    published_at: str,
    scope: str = "company",
    provider: str = "yfinance",
) -> NewsEventSnippet:
    return NewsEventSnippet(
        source=f"{provider}:{title}",
        title=title,
        summary=summary,
        published_at=published_at,
        provider=provider,
        scope=scope,
        link="https://example.com/story",
    )


class TestNewsRagRanking(unittest.TestCase):
    def test_rank_prefers_recent_relevant_events(self):
        events = [
            _event(
                title="Older macro note",
                summary="Broad market commentary without company catalysts.",
                published_at="2026-04-20",
                scope="macro",
            ),
            _event(
                title="Nvidia raises AI demand outlook",
                summary="Management highlighted demand growth, customer expansion, and margin upside.",
                published_at="2026-04-30",
            ),
            _event(
                title="Competitor launches new chip",
                summary="Competitive positioning and pricing pressure are being discussed.",
                published_at="2026-04-28",
            ),
        ]

        ranked = rank_news_event_snippets(
            events,
            query="AI demand growth margins customers",
            curr_date="2026-05-01",
            limit=2,
        )

        self.assertEqual(2, len(ranked))
        self.assertEqual("Nvidia raises AI demand outlook", ranked[0].title)
        self.assertEqual("Competitor launches new chip", ranked[1].title)

    def test_build_timeline_returns_fallback_when_no_events(self):
        with patch("marketmind_ai.dataflows.news_rag.collect_from_vendors", side_effect=[[], []]):
            result = build_news_event_timeline("NVDA", "2026-05-01")

        self.assertIn("No company-specific or macro news events were available", result)

    def test_build_timeline_formats_company_and_macro_sections(self):
        company = [
            _event(
                title="Nvidia raises AI demand outlook",
                summary="Management highlighted demand growth, customer expansion, and margin upside.",
                published_at="2026-04-30",
            )
        ]
        macro = [
            _event(
                title="Fed signals slower rate cuts",
                summary="Macro conditions remain restrictive for growth multiples.",
                published_at="2026-04-29",
                scope="macro",
                provider="alpha_vantage",
            )
        ]
        with patch("marketmind_ai.dataflows.news_rag.collect_from_vendors", side_effect=[company, macro]):
            result = build_news_event_timeline("NVDA", "2026-05-01", query="AI demand rates")

        self.assertIn("# News and event timeline for NVDA", result)
        self.assertIn("## Company-specific catalysts", result)
        self.assertIn("## Macro / market context", result)
        self.assertIn("Fed signals slower rate cuts", result)


class TestNewsProviderHelpers(unittest.TestCase):
    def test_extract_feed_items_from_alpha_vantage_payload(self):
        payload = {
            "feed": [
                {
                    "title": "Nvidia announces new data center win",
                    "summary": "A large customer commitment supports revenue visibility.",
                    "source": "Reuters",
                    "url": "https://example.com/reuters",
                    "time_published": "20260430T130000",
                    "overall_sentiment_label": "Bullish",
                    "overall_sentiment_score": "0.42",
                }
            ]
        }

        items = _extract_feed_items(payload, scope="company", end_date="2026-05-01")

        self.assertEqual("Nvidia announces new data center win", items[0]["title"])
        self.assertEqual("2026-04-30", items[0]["published_at"])
        self.assertAlmostEqual(0.42, items[0]["sentiment_score"])

    def test_yfinance_document_helpers_return_structured_documents(self):
        article = {
            "content": {
                "title": "Nvidia wins hyperscaler contract",
                "summary": "The deal expands supply commitments and revenue visibility.",
                "provider": {"displayName": "Yahoo Finance"},
                "canonicalUrl": {"url": "https://example.com/nvda"},
                "pubDate": "2026-04-30T12:00:00Z",
            }
        }

        with patch("yfinance.Ticker") as mock_ticker:
            mock_ticker.return_value.get_news.return_value = [article]
            company_docs = get_news_documents_yfinance("NVDA", "2026-04-25", "2026-05-01")

        with patch("yfinance.Search") as mock_search:
            mock_search.return_value.news = [article]
            macro_docs = get_global_news_documents_yfinance("2026-05-01", look_back_days=7, limit=5)

        self.assertEqual("company", company_docs[0]["scope"])
        self.assertEqual("2026-04-30", company_docs[0]["published_at"])
        self.assertEqual("macro", macro_docs[0]["scope"])


class TestNewsAnalystIntegration(unittest.TestCase):
    def test_news_analyst_includes_timeline_tool_and_guidance(self):
        captured = {}

        class DummyLLM:
            def bind_tools(self, tools):
                captured["tool_names"] = [tool.name for tool in tools]

                def _invoke(prompt_value):
                    system_prompt = prompt_value.messages[0].content
                    captured["system_prompt"] = system_prompt
                    return SimpleNamespace(tool_calls=[], content=system_prompt)

                return RunnableLambda(_invoke)

        tools = [SimpleNamespace(name="get_news_event_timeline")]
        offline_runtime = SimpleNamespace(models=SimpleNamespace(offline=False))
        node = create_news_analyst(DummyLLM(), tools, offline_runtime)
        result = node(
            {
                "trade_date": "2026-05-01",
                "company_of_interest": "NVDA",
                "messages": [],
                "output_language": "English",
            }
        )

        self.assertIn("get_news_event_timeline", captured["tool_names"])
        self.assertIn("Start with `get_news_event_timeline`", captured["system_prompt"])
        self.assertIn("event chronology", result["news_report"])


if __name__ == "__main__":
    unittest.main()
