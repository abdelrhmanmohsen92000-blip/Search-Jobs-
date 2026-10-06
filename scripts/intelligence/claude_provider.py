"""Claude AI provider adapter (V1.4 production audit).

A real, clean integration boundary for Claude as the primary reasoning
engine — implemented, but NOT selected by default (config/ai.yaml still
ships `provider: rule_based`) and NEVER required to run this repository or
its test suite.

IMPORTANT — honesty about what has and hasn't been verified:
This sandboxed environment has no outbound network access to api.anthropic.com
(the same egress policy that blocks remoteok.com/remotive.com — see
scripts/sources/base.py and README "Sources"). That means the HTTP call this
adapter makes has been written carefully against the documented Anthropic
Messages API shape, but has NOT been exercised against the real API from
this environment. Do not take its presence as proof that it works end to
end — test it for real in an environment with network access before relying
on it, and treat ANTHROPIC_API_KEY absence/invalidity as the expected
default state, not an edge case.

What this adapter does NOT assume:
    - It does NOT assume a Claude consumer (claude.ai) subscription grants
      API access. The Anthropic API is a separate product from a consumer
      subscription, with its own console, its own billing, and its own key
      (https://console.anthropic.com/ -> API Keys). A consumer subscription
      alone will not make this adapter work.
    - It does NOT fabricate a response when the key is missing, invalid, or
      the call fails for any reason — it reports the failure and falls back
      to RuleBasedAIProvider, labeled so the fallback is never silent.
"""
import datetime as _dt
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.intelligence.ai_provider import AIProvider, RuleBasedAIProvider  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5"
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_RETRIES = 2


class ClaudeAIProvider(AIProvider):
    """Reads its API key from the environment at call time only — never from
    this repository, never logged, never persisted to any tracker.
    """
    name = "claude"

    def __init__(self, model=None, timeout=None, max_retries=None, api_key_env_var="ANTHROPIC_API_KEY"):
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self.api_key_env_var = api_key_env_var
        self.last_usage = None  # {"input_tokens": int, "output_tokens": int} after the most recent successful call

    def _api_key(self):
        return os.environ.get(self.api_key_env_var)

    def analyze(self, prompt, context=None):
        """Returns a dict. On any failure (missing key, network error, non-200,
        malformed response), falls back to RuleBasedAIProvider and labels the
        result so the fallback is visible to the caller — never pretends the
        Claude call succeeded.
        """
        context = context or {}
        api_key = self._api_key()

        if not api_key:
            return self._fallback(prompt, context, status="MISSING_API_KEY",
                                   note=f"No {self.api_key_env_var} set in the environment. "
                                        f"A Claude *consumer* subscription (claude.ai) does not provide this — "
                                        f"generate a key at https://console.anthropic.com/ and set "
                                        f"{self.api_key_env_var} as an environment variable (never in this repo).")

        body = {
            "model": self.model,
            "max_tokens": 1024,
            "system": "Respond with a single JSON object only, no prose outside the JSON.",
            "messages": [{"role": "user", "content": self._build_prompt(prompt, context)}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        data, error = self._post_with_retries(body, headers)
        if error:
            return self._fallback(prompt, context, status="API_CALL_FAILED", note=error)

        try:
            text = data["content"][0]["text"]
            usage = data.get("usage", {})
            self.last_usage = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
            parsed = json.loads(text)
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            return self._fallback(prompt, context, status="MALFORMED_RESPONSE", note=f"{type(e).__name__}: {e}")

        return {
            "provider": self.name,
            "status": "OK",
            "model": self.model,
            "result": parsed,
            "usage": self.last_usage,
            "retrieved_at": _dt.datetime.now().isoformat(timespec="seconds"),
        }

    def _build_prompt(self, prompt, context):
        return f"{prompt}\n\nContext (JSON):\n{json.dumps(context, default=str)}"

    def _post_with_retries(self, body, headers):
        import time

        last_error = None
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status != 200:
                        last_error = f"HTTP {resp.status}"
                    else:
                        return json.loads(resp.read()), None
            except urllib.error.HTTPError as e:
                # 401/403 (bad/missing key) or 429 (rate limit) are not worth retrying blindly;
                # still only reported, never retried past max_retries, never treated as success.
                last_error = f"HTTP {e.code}: {e.reason}"
                if e.code in (401, 403):
                    break
            except urllib.error.URLError as e:
                last_error = f"URLError: {e.reason}"
            except Exception as e:  # noqa: BLE001 - this adapter must never crash the pipeline
                last_error = f"{type(e).__name__}: {e}"
            if attempt < self.max_retries:
                time.sleep(1.5 ** attempt)
        return None, last_error

    def _fallback(self, prompt, context, status, note):
        fallback_result = RuleBasedAIProvider().analyze(prompt, context)
        return {**fallback_result, "provider": self.name, "status": status, "note": note, "fallback_provider": "rule_based"}
