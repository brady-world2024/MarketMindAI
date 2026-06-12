import unittest
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.runnables import RunnableLambda

from marketmind_ai.agents.analysts.fundamentals import create_fundamentals_analyst
from marketmind_ai.dataflows.alpha_vantage_transcripts import _extract_transcript_text
from marketmind_ai.dataflows.fundamentals_rag import (
    FundamentalDocumentSnippet,
    build_fundamental_document_context,
    rank_fundamental_document_snippets,
)
from marketmind_ai.dataflows.sec_filings import _recent_filings


def _snippet(
    *,
    title: str,
    text: str,
    filing_date: str,
    doc_type: str = "10-Q",
    provider: str = "sec",
) -> FundamentalDocumentSnippet:
    return FundamentalDocumentSnippet(
        source=f"{provider}:{title}",
        doc_type=doc_type,
        filing_date=filing_date,
        title=title,
        text=text,
        provider=provider,
    )


class TestFundamentalsRagRanking(unittest.TestCase):
    def test_rank_prefers_relevant_recent_snippets(self):
        snippets = [
            _snippet(
                title="Old risk factor",
                filing_date="2024-02-01",
                text="General competitive risks and boilerplate disclosures.",
                doc_type="10-K",
            ),
            _snippet(
                title="Recent revenue discussion",
                filing_date="2026-04-20",
                text="Revenue growth accelerated, gross margin expanded, and guidance improved.",
                doc_type="10-Q",
            ),
            _snippet(
                title="Transcript outlook",
                filing_date="2026-04-25",
                text="Management discussed demand, guidance, capex, and customer expansion in detail.",
                doc_type="earnings_call_transcript",
                provider="alpha_vantage",
            ),
        ]

        ranked = rank_fundamental_document_snippets(
            snippets,
            query="guidance demand revenue margin",
            curr_date="2026-05-01",
            limit=2,
        )

        self.assertEqual(2, len(ranked))
        self.assertEqual("Recent revenue discussion", ranked[0].title)
        self.assertEqual("Transcript outlook", ranked[1].title)

    def test_build_context_returns_fallback_when_no_docs(self):
        with patch("marketmind_ai.dataflows.fundamentals_rag.collect_from_vendors", return_value=[]):
            result = build_fundamental_document_context("NVDA", "2026-05-01")

        self.assertIn("No filing or transcript documents were available", result)

    def test_build_context_formats_ranked_snippets(self):
        snippets = [
            _snippet(
                title="Recent revenue discussion",
                filing_date="2026-04-20",
                text="Revenue growth accelerated, gross margin expanded, and guidance improved.",
            ),
            _snippet(
                title="Transcript outlook",
                filing_date="2026-04-25",
                text="Management discussed demand, guidance, capex, and customer expansion in detail.",
                doc_type="earnings_call_transcript",
                provider="alpha_vantage",
            ),
        ]
        with patch("marketmind_ai.dataflows.fundamentals_rag.collect_from_vendors", return_value=snippets):
            result = build_fundamental_document_context("NVDA", "2026-05-01", "guidance demand")

        self.assertIn("# Fundamental document evidence for NVDA", result)
        self.assertIn("Transcript outlook", result)
        self.assertIn("Recent revenue discussion", result)


class TestTranscriptAndSecHelpers(unittest.TestCase):
    def test_extract_transcript_text_from_list_payload(self):
        payload = {
            "transcript": [
                {"speaker": "CEO", "content": "Demand remains strong."},
                {"speaker": "CFO", "content": "Margins improved sequentially."},
            ]
        }
        text = _extract_transcript_text(payload)
        self.assertIn("CEO: Demand remains strong.", text)
        self.assertIn("CFO: Margins improved sequentially.", text)

    def test_recent_filings_filters_supported_forms_and_dates(self):
        recent = {
            "form": ["8-K", "10-Q", "10-K", "10-Q"],
            "filingDate": ["2026-05-02", "2026-04-20", "2026-02-10", "2026-05-03"],
            "accessionNumber": ["a", "b", "c", "d"],
            "primaryDocument": ["8k.htm", "10q.htm", "10k.htm", "future10q.htm"],
        }
        filings = _recent_filings(recent, "2026-05-01")
        self.assertEqual(["10-Q", "10-K"], [item["form"] for item in filings])
        self.assertEqual("10q.htm", filings[0]["primary_document"])


class TestFundamentalsAnalystIntegration(unittest.TestCase):
    def test_fundamentals_analyst_includes_document_tool_and_guidance(self):
        captured = {}

        class DummyLLM:
            def bind_tools(self, tools):
                captured["tool_names"] = [tool.name for tool in tools]

                def _invoke(prompt_value):
                    system_prompt = prompt_value.messages[0].content
                    captured["system_prompt"] = system_prompt
                    return SimpleNamespace(tool_calls=[], content=system_prompt)

                return RunnableLambda(_invoke)

        tools = [SimpleNamespace(name="get_fundamental_document_context")]
        offline_runtime = SimpleNamespace(models=SimpleNamespace(offline=False))
        node = create_fundamentals_analyst(DummyLLM(), tools, offline_runtime)
        result = node(
            {
                "trade_date": "2026-05-01",
                "company_of_interest": "NVDA",
                "messages": [],
                "output_language": "English",
            }
        )

        self.assertIn("get_fundamental_document_context", captured["tool_names"])
        self.assertIn("Start with `get_fundamental_document_context`", captured["system_prompt"])
        self.assertIn("earnings call transcript", result["fundamentals_report"])


if __name__ == "__main__":
    unittest.main()
