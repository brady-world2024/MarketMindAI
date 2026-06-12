from __future__ import annotations

import re


ACTIONABLE = "Actionable"
NO_RECOMMENDATION = "No Recommendation"
RATINGS_5_TIER = ("Buy", "Overweight", "Hold", "Underweight", "Sell")

_RATING_LABEL_RE = re.compile(
    r"^\s*\*{0,2}(?:Rating|Recommendation|Action)\*{0,2}\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_STATUS_LABEL_RE = re.compile(
    r"^\s*\*{0,2}(?:Decision Status|Recommendation Status|Action Status)\*{0,2}\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_CONFIDENCE_RE = re.compile(
    r"^\s*\*{0,2}Confidence\*{0,2}\s*:\s*(\d{1,3})(?:\s*/\s*100)?\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _normalize_rating(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split()).strip("*`_ ").lower()
    mapping = {
        "buy": "Buy",
        "overweight": "Overweight",
        "hold": "Hold",
        "underweight": "Underweight",
        "sell": "Sell",
        "no recommendation": NO_RECOMMENDATION,
        "none": NO_RECOMMENDATION,
    }
    return mapping.get(cleaned)


def parse_decision_status(text: str) -> str:
    match = _STATUS_LABEL_RE.search(text or "")
    if match:
        cleaned = " ".join(match.group(1).strip().split()).lower()
        if cleaned.startswith("no recommendation"):
            return NO_RECOMMENDATION
        if cleaned.startswith("actionable"):
            return ACTIONABLE
    rating = parse_rating(text)
    if rating == NO_RECOMMENDATION:
        return NO_RECOMMENDATION
    return ACTIONABLE


def parse_rating(text: str, default: str = "Hold") -> str:
    source = text or ""
    status = _STATUS_LABEL_RE.search(source)
    if status:
        cleaned = " ".join(status.group(1).strip().split()).lower()
        if cleaned.startswith("no recommendation"):
            return NO_RECOMMENDATION

    label = _RATING_LABEL_RE.search(source)
    if label:
        normalized = _normalize_rating(label.group(1))
        if normalized:
            return normalized

    lowered = source.lower()
    if "no recommendation" in lowered:
        return NO_RECOMMENDATION

    directional_words = [
        ("overweight", "Overweight"),
        ("underweight", "Underweight"),
        ("buy", "Buy"),
        ("sell", "Sell"),
        ("hold", "Hold"),
    ]
    for needle, rating in directional_words:
        if re.search(rf"\b{re.escape(needle)}\b", lowered):
            return rating
    return default


def parse_confidence(text: str) -> int | None:
    match = _CONFIDENCE_RE.search(text or "")
    if not match:
        return None
    value = int(match.group(1))
    if 0 <= value <= 100:
        return value
    return None
