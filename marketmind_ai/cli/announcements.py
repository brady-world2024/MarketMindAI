from __future__ import annotations

import json
import sys
import urllib.request

from .config import CLI_CONFIG
from .models import AnnouncementPayload


def fetch_announcements(url: str | None = None, timeout: float | None = None) -> AnnouncementPayload:
    endpoint = url or CLI_CONFIG["announcements_url"]
    request_timeout = timeout or CLI_CONFIG["announcements_timeout"]
    fallback = CLI_CONFIG["announcements_fallback"]

    if not endpoint:
        return AnnouncementPayload(announcements=[], require_attention=False)

    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/json",
            "User-Agent": "MarketMindAI-CLI/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return AnnouncementPayload(announcements=[fallback], require_attention=False)

    return AnnouncementPayload(
        announcements=list(payload.get("announcements", []) or [fallback]),
        require_attention=bool(payload.get("require_attention", False)),
    )


def display_announcements(payload: AnnouncementPayload) -> None:
    if not payload.announcements:
        return
    print("Announcements", file=sys.stderr)
    for item in payload.announcements:
        print(f"- {item}", file=sys.stderr)
    if payload.require_attention:
        print("", file=sys.stderr)
