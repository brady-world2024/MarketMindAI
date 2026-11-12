"""User-confirmed admission rules, separate from transport and model prompts."""
from dataclasses import dataclass
from datetime import datetime, timezone

from .results import Serializable

POLICY_VERSION = 'us-common-close-v1'
PROCESSING_VERSION = 'frozen-inputs-v1'


@dataclass(frozen=True)
class SourcePolicy(Serializable):
    policy_version: str = POLICY_VERSION
    minimum_price_bars: int = 50
    required: tuple[str, ...] = ('price_history', 'income_statement', 'balance_sheet', 'cashflow')
    statement_provider: str = 'sec'
    optional: tuple[str, ...] = ('fundamentals', 'news', 'fundamental_documents', 'global_news', 'insider_transactions')


DEFAULT_SOURCE_POLICY = SourcePolicy()


def aware_time(value) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, AttributeError, OverflowError):
        return None


def classify_public_time(published_at, cutoff_at) -> str | None:
    published, cutoff = aware_time(published_at), aware_time(cutoff_at)
    if published is None or cutoff is None:
        return 'public_time_unverified'
    return 'published_after_cutoff' if published > cutoff else None
