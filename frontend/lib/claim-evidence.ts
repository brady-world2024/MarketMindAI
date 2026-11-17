import type { RunSnapshot } from "./api-types";

export function claimCheckId(snapshot: RunSnapshot, kind: "claim-check" | "calculation", index: number) {
  return `${snapshot.run_id}-${kind}-${index + 1}`;
}

export function claimCheckLinks(snapshot: RunSnapshot, index: number) {
  const claim = snapshot.final_structured_decision?.core_claims?.[index];
  if (!claim?.claim) return [];
  const links: { id: string; label: string }[] = [];
  (snapshot.report_verification?.qualitative_claims ?? []).forEach((check, checkIndex) => {
    if (check.claim_number === index + 1 && check.claim === claim.claim) {
      links.push({ id: claimCheckId(snapshot, "claim-check", checkIndex), label: "Source check" });
    }
  });
  const evidenceIds = new Set((snapshot.evidence_ledger ?? []).map(item => item.evidence_id));
  (snapshot.report_verification?.financial_claims ?? []).forEach((check, checkIndex) => {
    if (check.evidence_id && evidenceIds.has(check.evidence_id) && claim.evidence_ids?.includes(check.evidence_id)) {
      links.push({ id: claimCheckId(snapshot, "calculation", checkIndex), label: `Calculation ${check.evidence_id}` });
    }
  });
  return links;
}
