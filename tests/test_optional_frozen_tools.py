from types import SimpleNamespace

from marketmind_ai.agents.utils.news_data_tools import build_news_data_tools
from marketmind_ai.dataflows.config import dataflow_context
from test_frozen_inputs import frozen


def test_optional_news_and_insider_tools_report_absence_without_breaking_ai():
    context = SimpleNamespace(analysis_date='2026-06-12')
    tools = {tool.name: tool for tool in build_news_data_tools(context)}
    with dataflow_context({'data_mode': 'live'}) as audit:
        audit.frozen_inputs = frozen()
        for name, args in [('get_news', {'symbol': 'OTHER'}),
                           ('get_global_news', {}), ('get_insider_transactions', {'symbol': 'ABC'})]:
            result = tools[name].invoke(args)
            assert 'unavailable' in result.lower() or 'no ' in result.lower()
            assert '0' != result
