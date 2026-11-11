"""A closed data-tool boundary: replay never calls a provider adapter."""
from copy import deepcopy
from datetime import date, timedelta

from ..agents.utils.research_types import FundamentalSnapshot, NewsItem, PriceBar
from .results import DataMode, SourceMaterial, VendorResult
from .source_policy import aware_time
from .source_records import ResearchDataSnapshot
from .stockstats_utils import render_indicator_report


class FrozenInputs:
    def __init__(self, snapshot: ResearchDataSnapshot):
        from .source_store import snapshot_fingerprint
        self.snapshot = ResearchDataSnapshot.model_validate(snapshot.to_dict())
        self.manifest_sha256 = snapshot_fingerprint(self.snapshot)
        self.source_records = [record.to_dict() for record in self.snapshot.records]

    def _unavailable(self):
        return VendorResult(status='empty', data_mode=self.snapshot.data_mode)

    @staticmethod
    def _argument(args, kwargs, position, names, default=None):
        if len(args) > position:
            return args[position]
        return next((kwargs[name] for name in names if name in kwargs), default)

    def read(self, method: str, *args, aggregate: bool = False, **kwargs) -> VendorResult:
        try:
            return self._read(method, args, kwargs, aggregate)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            return self._unavailable()

    def _read(self, method, args, kwargs, aggregate):
        global_method = method in {'get_global_news', 'get_global_news_documents'}
        if not global_method:
            symbol = self._argument(args, kwargs, 0, ('symbol', 'ticker', 'query'))
            if not isinstance(symbol, str) or symbol.upper() != self.snapshot.symbol.upper():
                return self._unavailable()
        dates = {self.snapshot.cutoff['requested_date'], self.snapshot.cutoff['effective_session_date']}
        dated = {'get_price_history', 'get_indicators', 'get_news', 'get_fundamental_documents',
                 'get_insider_transactions', 'get_instrument_metadata', 'get_global_news', 'get_global_news_documents'}
        if method in dated:
            requested = self._argument(args, kwargs, 0 if global_method else 1,
                                       ('analysis_date', 'curr_date', 'trade_date'))
            if requested not in dates:
                return self._unavailable()
        if method == 'get_indicators':
            price = self._read('get_price_history', (self.snapshot.symbol, self.snapshot.cutoff['effective_session_date'], 260), {}, False)
            if not price.available:
                return price
            indicators = self._argument(args, kwargs, 2, ('indicators',))
            price.value = render_indicator_report(price.value, indicators)
            return price
        entry = self.snapshot.inputs.get(method)
        if not entry or not entry.get('available'):
            return self._unavailable()
        value = deepcopy(entry.get('value'))
        if method == 'get_price_history':
            lookback = self._argument(args, kwargs, 2, ('lookback_days',), 180)
            if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback <= 0 or lookback > 260:
                return self._unavailable()
            value = [PriceBar(**bar) for bar in value[-lookback:]]
        elif method == 'get_fundamentals':
            value = FundamentalSnapshot(**value)
        elif method in {'get_news', 'get_global_news'}:
            limit = self._argument(args, kwargs, 2, ('limit',), 8)
            if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
                return self._unavailable()
            if global_method:
                theme = self._argument(args, kwargs, 1, ('theme',), 'macro')
                if theme not in {'macro', 'market'}:
                    return self._unavailable()
            value = [NewsItem(**item) for item in value[:limit]]
        elif method == 'get_news_documents':
            start = self._argument(args, kwargs, 1, ('start_date',))
            end = self._argument(args, kwargs, 2, ('end_date',))
            if (end not in dates or date.fromisoformat(start) > date.fromisoformat(end)
                    or start < entry.get('window_start', start)):
                return self._unavailable()
            value = [item for item in value if item.get('published_at', '')[:10] >= start]
        elif method == 'get_global_news_documents':
            lookback = self._argument(args, kwargs, 1, ('look_back_days',), 7)
            limit = self._argument(args, kwargs, 2, ('limit',), 25)
            if (isinstance(lookback, bool) or not isinstance(lookback, int)
                    or not 0 < lookback <= entry.get('window_days', 8)
                    or isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
                return self._unavailable()
            start = (date.fromisoformat(self.snapshot.cutoff['effective_session_date']) - timedelta(days=lookback)).isoformat()
            value = [item for item in value if item.get('published_at', '')[:10] >= start][:limit]
        records = [record for record in self.snapshot.records if record.record_id in entry.get('record_ids', [])
                   and record.admissibility == 'included']
        materials = [SourceMaterial(method=method, provider=record.provider, data_mode=record.data_mode,
                        retrieved_at=aware_time(record.retrieved_at), content=record.content, source_url=record.source_url)
                     for record in records]
        return VendorResult(value=value, provider=entry.get('provider'), data_mode=self.snapshot.data_mode,
                            status='success', materials=materials)
