"""Canonical venue names shared by lookup and registered-security checks."""
import re


def normalize_exchange(value: str | None) -> str:
    original = str(value or '').strip()
    normalized = re.sub(r'[^a-z]', '', original.lower()).removeprefix('the').removesuffix('llc')
    if normalized in {'nasdaq', 'nasdaqstockmarket', 'nasdaqglobalmarket',
                      'nasdaqglobalselectmarket', 'nasdaqcapitalmarket', 'nms', 'ngm', 'ncm'}:
        return 'NASDAQ'
    if normalized in {'nyse', 'newyorkstockexchange', 'nyq', 'nys'}:
        return 'NYSE'
    return original.upper()


def normalize_region(value: str | None) -> str:
    normalized = re.sub(r'[^a-z]', '', str(value or '').lower())
    return 'US' if normalized in {'us', 'usa', 'unitedstates', 'unitedstatesofamerica'} else normalized.upper()
