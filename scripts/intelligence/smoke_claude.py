#!/usr/bin/env python3
"""Real, isolated Claude API smoke test (production audit Phase 2, §5).

Deliberately named so pytest's default discovery (`test_*.py` / `*_test.py`)
never collects it — this makes one real, minimal, authenticated network call
when a key is available, and must never run as part of `pytest`.

Usage:
    python3 scripts/intelligence/smoke_claude.py

Behavior:
    - If ANTHROPIC_API_KEY is NOT set: prints
          REAL_AUTHENTICATED_TEST = BLOCKED
          REASON = ANTHROPIC_API_KEY not available
      and exits 0 — this is the expected, honest default state, not an error.
    - If ANTHROPIC_API_KEY IS set: sends exactly one tiny, deterministic,
      non-personal prompt ("Reply with exactly the JSON object {"ok": true} "
      "and nothing else.") and reports whether authentication, transport,
      and response-parsing each worked, as VERIFIED or FAILED with the
      provider's own status/note. No personal, profile, or portfolio data is
      ever included in this prompt.

This script never fabricates a result: if it cannot run the real call, it
says BLOCKED, not "probably works."
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.intelligence.claude_provider import ClaudeAIProvider  # noqa: E402

SMOKE_PROMPT = 'Reply with exactly the JSON object {"ok": true} and nothing else.'


def run_smoke_test(api_key_env_var="ANTHROPIC_API_KEY"):
    """Returns a result dict; never raises. Makes a real network call only
    when the named environment variable is actually set.
    """
    if not os.environ.get(api_key_env_var):
        return {
            "REAL_AUTHENTICATED_TEST": "BLOCKED",
            "REASON": f"{api_key_env_var} not available",
        }

    provider = ClaudeAIProvider(api_key_env_var=api_key_env_var)
    response = provider.analyze(SMOKE_PROMPT, context={})  # no personal/profile/portfolio data

    if response.get("status") == "OK":
        return {
            "REAL_AUTHENTICATED_TEST": "VERIFIED",
            "model": response.get("model"),
            "usage": response.get("usage"),
            "parsed_result": response.get("result"),
        }

    return {
        "REAL_AUTHENTICATED_TEST": "FAILED",
        "REASON": response.get("note"),
        "provider_status": response.get("status"),
    }


def main():
    import json

    result = run_smoke_test()
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
