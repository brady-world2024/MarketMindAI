from marketmind_ai.dataflows.yfinance_news import _article_to_document


def test_news_keeps_exact_publication_time_and_timezone():
    item = _article_to_document({'content': {'title': 'Exact time', 'pubDate': '2026-06-12T20:01:00Z'}}, 'company')
    assert item['published_at'] == '2026-06-12T20:01:00+00:00'


def test_missing_or_naive_time_is_not_replaced_with_a_date_or_clock():
    assert _article_to_document({'content': {'title': 'Unknown'}}, 'company')['published_at'] == ''
    item = _article_to_document({'content': {'title': 'Naive', 'pubDate': '2026-06-12T18:00:00'}}, 'company')
    assert item['published_at'] == '2026-06-12T18:00:00'


def test_collection_compares_aware_instants_instead_of_dropping_offsets(monkeypatch):
    from types import SimpleNamespace
    from marketmind_ai.dataflows import yfinance_news as module
    articles = [
        {'content': {'title': 'UTC previous date', 'pubDate': '2026-06-12T00:30:00+14:00'}},
        {'content': {'title': 'UTC within window', 'pubDate': '2026-06-11T23:30:00-04:00'}}]
    monkeypatch.setattr(module, 'yf', SimpleNamespace(Ticker=lambda ticker: SimpleNamespace(get_news=lambda **k: articles)))
    docs = module.get_news_documents_yfinance('ABC', '2026-06-12', '2026-06-12')
    assert [doc['title'] for doc in docs] == ['UTC within window']


def test_ranking_accepts_full_publication_timestamps():
    from marketmind_ai.dataflows.news_rag import _recency_weight
    assert _recency_weight('2026-06-12T19:59:00+00:00', '2026-06-12') == 1.0


def test_date_only_publication_does_not_gain_an_invented_midnight():
    item = _article_to_document({'content': {'title': 'Date only', 'pubDate': '2026-06-12'}}, 'company')
    assert item['published_at'] == '2026-06-12'
