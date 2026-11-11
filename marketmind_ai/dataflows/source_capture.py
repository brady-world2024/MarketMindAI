"""Capture safe transport bodies without changing adapter return contracts."""
from .config import get_audit
from .results import safe_json, utc_now


def capture_source_response(source_url: str, body: str, content_type: str):
    audit = get_audit()
    if audit is not None and audit.frozen_inputs is None:
        method, provider, attempt_id = audit.capture_context or ('source_transport', 'unknown', None)
        audit.raw_captures.append({'source_url': safe_json(source_url), 'body': safe_json(body),
            'content_type': content_type, 'retrieved_at': utc_now().isoformat(),
            'method': method, 'provider': provider, 'attempt_id': attempt_id})
