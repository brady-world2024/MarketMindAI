from marketmind_ai.reporting import ClaimEvidenceAuditor


LEDGER = [
    {"evidence_id": "E1", "claim": "Momentum remains constructive.", "strength": "High"},
    {"evidence_id": "E2", "claim": "Valuation is demanding.", "strength": "Medium"},
]


def test_auditor_accepts_supported_claims_with_valid_evidence_ids():
    decision = {
        "decision_status": "Actionable",
        "core_claims": [
            {
                "claim": "Momentum supports a constructive stance.",
                "evidence_ids": ["E1"],
                "support_level": "supported",
            }
        ],
        "counterargument": "Valuation could cap upside.",
        "counterargument_evidence_ids": ["E2"],
        "counterargument_response": "Sizing is capped because valuation risk remains.",
    }

    result = ClaimEvidenceAuditor().audit(decision, LEDGER)

    assert result["severity"] == "none"
    assert result["claim_support_score"] == 100
    assert result["counterargument_score"] == 100
    assert result["unsupported_claims"] == []
    assert result["issues"] == []


def test_auditor_flags_unsupported_claims_and_rewrite_suggestions():
    decision = {
        "decision_status": "Actionable",
        "core_claims": [
            {
                "claim": "Margins are guaranteed to expand.",
                "evidence_ids": ["E9"],
                "support_level": "supported",
            }
        ],
        "counterargument": "Valuation could cap upside.",
        "counterargument_evidence_ids": ["E2"],
        "counterargument_response": "Sizing is capped because valuation risk remains.",
    }

    result = ClaimEvidenceAuditor().audit(decision, LEDGER)

    assert result["severity"] == "severe"
    assert result["claim_support_score"] < 50
    assert result["unsupported_claims"][0]["claim"] == "Margins are guaranteed to expand."
    assert result["rewrite_suggestions"][0]["suggested_text"].startswith("Evidence does not yet prove")
    assert "unsupported_core_claim" in {issue["code"] for issue in result["issues"]}


def test_auditor_marks_missing_counterargument_without_always_severe():
    decision = {
        "decision_status": "Actionable",
        "core_claims": [
            {
                "claim": "Momentum supports a constructive stance.",
                "evidence_ids": ["E1"],
                "support_level": "supported",
            }
        ],
        "counterargument": "",
        "counterargument_response": "",
    }

    result = ClaimEvidenceAuditor().audit(decision, LEDGER)

    assert result["severity"] == "major"
    assert result["claim_support_score"] == 100
    assert result["counterargument_score"] < 50
    assert "missing_counterargument" in {issue["code"] for issue in result["issues"]}
