"""Recompute supported financial ratios from the admitted SEC income statement."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP, localcontext
import re

from ..dataflows.sec_statements import _header_periods
from ..dataflows.source_policy import classify_public_time

_LABELS = {
    "revenue": {"revenue", "revenues", "total revenue", "total revenues", "net sales", "total net sales"},
    "operating_income": {"operating income", "income from operations",
                         "operating income (loss)", "income (loss) from operations"},
}
_PATTERNS = {
    "operating_margin": re.compile(r"operating (?:profit )?margins?|营业利润率|经营利润率|營業利益率|營業利潤率", re.I),
    "revenue_yoy": re.compile(r"(?:revenue|sales).{0,70}(?:year.over.year|yoy|同比|(?:a|one) year earlier|prior.year)|"
                              r"(?:year.over.year|yoy).{0,70}(?:revenue|sales)|"
                              r"(?:营收|营业收入|收入|營收).{0,25}同比|同比.{0,25}(?:营收|营业收入|收入|營收)", re.I),
}
_PERCENT = re.compile(r"(?<![\w.])[+-]?\d{1,6}(?:\.\d{1,6})?\s*[%％]")
_AMOUNT = re.compile(r"[$€£¥]\s*\d|\d[\d,.]*\s*(?:thousand|million|billion|trillion|USD|EUR|GBP|百萬|百万|亿|億|万|萬)", re.I)
_NUMBER = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_DECLARED = re.compile(r"[+-]?\d{1,6}(?:\.\d{1,6})?")


def _read_cells(rows, names, periods, scale):
    matches = [(i, row) for i, row in enumerate(rows, 1) if row and row[0].casefold() in names]
    if len(matches) != 1:
        return {}
    line, row = matches[0]
    if len(row) != len(periods) + 1:
        return {}
    cells = {}
    for index, (period, raw) in enumerate(zip(periods, row[1:]), 2):
        number = raw.strip()
        negative = number.startswith("(") and number.endswith(")")
        number = number[1:-1] if negative else number
        number = number.removeprefix("$").strip()
        if number.startswith("-") and not negative:
            negative, number = True, number[1:]
        if len(number) > 30 or not _NUMBER.fullmatch(number):
            continue
        value = Decimal(number.replace(",", "")) * scale * (-1 if negative else 1)
        cells[period] = {"label": row[0], "line": line, "column": index,
                         "period_end": period, "raw_value": raw, "value": str(value)}
    return cells


def collect_metrics(records, symbol, cutoff_at):
    """Return metrics only when the saved table establishes units and comparable columns."""
    eligible = [record for record in records if record.get("symbol") == symbol
                and record.get("provider") == "sec" and record.get("method") == "get_income_statement"
                and record.get("admissibility") == "included" and record.get("accession")
                and record.get("record_id") and not classify_public_time(record.get("published_at"), cutoff_at)]
    if len(eligible) != 1:
        return {}
    source = eligible[0]
    content = source.get("content")
    if not isinstance(content, str) or source.get("currency") != "USD":
        return {}
    rows = [line.split("\t") for line in content.splitlines()]
    if len(rows) < 3:
        return {}
    duration = re.findall(r"\b(3|6|9|12) Months Ended\b", "\t".join(rows[0]), re.I)
    scales = re.findall(r"\$\s+in\s+(thousands|millions|billions)\b", rows[0][0], re.I)
    if len(rows[0]) != 2 or len(duration) != 1 or len(scales) != 1:
        return {}
    headers = rows[1][1:] if rows[1][0] == "" else rows[1]
    dates = [_header_periods([header]) for header in headers]
    if not dates or any(len(values) != 1 for values in dates):
        return {}
    periods = [next(iter(values)) for values in dates]
    latest = source.get("period_end")
    if len(set(periods)) != len(periods) or periods[0] != latest:
        return {}
    scale = {"thousands": 1000, "millions": 1000000, "billions": 1000000000}[scales[0].lower()]
    revenue = _read_cells(rows[2:], _LABELS["revenue"], periods, scale)
    operating = _read_cells(rows[2:], _LABELS["operating_income"], periods, scale)
    current = revenue.get(latest)
    if not current or Decimal(current["value"]) <= 0:
        return {}
    base = {"record_id": source["record_id"], "accession": source["accession"],
            "source_url": source.get("source_url"), "currency": "USD",
            "display_scale": scale, "duration_months": int(duration[0]), "period_end": latest}
    for cell in [*revenue.values(), *operating.values()]:
        cell["line"] += 2
    result = {}

    def add(metric, numerator, denominator, offset, formula):
        with localcontext() as ctx:
            ctx.prec = 64
            percentage = (Decimal(numerator["value"]) / Decimal(denominator["value"]) - offset) * 100
        result[metric] = {**base, "inputs": [numerator, denominator],
                          "computed_percentage": str(percentage), "formula": formula}

    comparison = [period for period in periods[1:]
                  if 350 <= (date.fromisoformat(latest) - date.fromisoformat(period)).days <= 380]
    if len(comparison) == 1 and (prior := revenue.get(comparison[0])) and Decimal(prior["value"]) > 0:
        add("revenue_yoy", current, prior, 1, "(current revenue / prior-year revenue - 1) × 100")
    if latest in operating:
        add("operating_margin", operating[latest], current, 0, "operating income / revenue × 100")
    return result


def verify_financial_claims(decision, metrics):
    results = []
    supported = {}
    for index, evidence in enumerate(decision.get("primary_evidence") or [], 1):
        claim = evidence.get("financial_claim")
        if not claim:
            continue
        metric, percentage = claim["metric"], claim["percentage"]
        source = metrics.get(metric)
        outcome = {"evidence_id": f"E{index}", "metric": metric, "declared_percentage": percentage,
                   "status": "insufficient", "reason": "SEC source ID or fiscal period could not be verified."}
        if (source and source["record_id"] == evidence.get("raw_source_id")
                and source["period_end"] == claim["period_end"] and _DECLARED.fullmatch(percentage)
                and evidence.get("provider") in (None, "", "sec")
                and evidence.get("url") in (None, "", source["source_url"])):
            declared = Decimal(percentage)
            rounded = Decimal(source["computed_percentage"]).quantize(
                Decimal(1).scaleb(declared.as_tuple().exponent), rounding=ROUND_HALF_UP)
            outcome.update(source, rounded_percentage=str(rounded))
            if declared == rounded:
                outcome.update(status="supported", reason="Matches the SEC calculation at the declared precision.")
                supported[f"E{index}"] = (metric, declared)
            else:
                outcome.update(status="contradicted", reason=f"SEC calculation rounds to {rounded}%.")
        results.append(outcome)

    texts = [(decision.get(field, ""), supported.keys())
             for field in ("executive_summary", "investment_thesis", "confidence_rationale", "counterargument_response")]
    texts.append((decision.get("counterargument", ""), decision.get("counterargument_evidence_ids") or []))
    texts.extend((risk, supported.keys()) for risk in decision.get("key_risks") or [])
    texts += [(claim["claim"], claim.get("evidence_ids") or []) for claim in (decision.get("core_claims") or [])]
    for index, item in enumerate(decision.get("primary_evidence") or [], 1):
        texts.extend((item.get(field, ""), [f"E{index}"]) for field in ("claim", "excerpt", "interpretation"))
    for value, citations in texts:
        for clause in re.split(r"[;；。]|\.(?=\s|$)|,\s+", " ".join((value or "").split())):
            for metric, pattern in _PATTERNS.items():
                if not pattern.search(clause):
                    continue
                percentages = [Decimal(token[:-1].strip()) for token in _PERCENT.findall(clause)]
                if metric == "revenue_yoy" and re.search(r"\bdoubl(?:ed|es|ing)\b|翻倍", clause, re.I):
                    percentages.append(Decimal(100))
                admitted = {percentage for key, (name, percentage) in supported.items()
                            if name == metric and key in citations}
                if metric == "revenue_yoy" and re.search(
                    r"\b(?:fell|fallen|down|declin(?:e|ed)|decreas(?:e|ed)|dropp?ed)\b|下降|下滑|减少|減少", clause, re.I
                ):
                    percentages = [percentage.copy_abs().copy_negate() for percentage in percentages]
                fiscal_dates = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", clause)
                wrong_period = any(day != metrics.get(metric, {}).get("period_end") for day in fiscal_dates)
                matches = percentages and all(any(
                    value == declared and value.as_tuple().exponent >= declared.as_tuple().exponent
                    for declared in admitted) for value in percentages)
                if _AMOUNT.search(clause):
                    results.append({"metric": metric, "claim": clause.strip(), "status": "insufficient",
                                    "reason": "Separate monetary amounts from verified ratio claims. See the saved inputs."})
                    continue
                if matches and not wrong_period:
                    continue
                results.append({"metric": metric, "claim": clause.strip(),
                                "status": "contradicted" if admitted and (percentages or wrong_period) else "insufficient",
                                "reason": "The narrative claim must match a verified structured SEC percentage and period."})
    return results


def active_financial_metrics():
    """None means the SEC gate does not apply, including for offline demos."""
    from ..dataflows.config import get_audit

    audit = get_audit()
    if audit is None or audit.frozen_inputs is None:
        return None
    frozen = audit.frozen_inputs
    if frozen.snapshot.data_mode != "live":
        return None
    return collect_metrics(frozen.source_records, frozen.snapshot.symbol, audit.cutoff_at)
