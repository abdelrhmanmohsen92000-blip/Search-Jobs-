"""Claude AI provider adapter (V1.4 production audit).

A real, clean integration boundary for Claude as the primary reasoning
engine — implemented, but NOT selected by default (config/ai.yaml still
ships `provider: rule_based`) and NEVER required to run this repository or
its test suite.

IMPORTANT — honesty about what has and hasn't been verified (updated in the
Phase 2 production audit, docs/PRODUCTION_READINESS.md):
This sandboxed environment CAN reach api.anthropic.com — confirmed directly
with a real request that returned a genuine 401 Unauthorized, both via plain
curl and via this adapter's own code path with a fake key. That is different
from remoteok.com/remotive.com, which this same environment's egress policy
blocks outright (see scripts/sources/base.py and README "Sources"). What
remains unverified is a *successful, authenticated* call: no real
ANTHROPIC_API_KEY exists in this environment to test one, and none should be
placed here to find out. Do not take network reachability as proof the full
request/response cycle works end to end — run scripts/intelligence/smoke_claude.py
for real, with a real key, in an environment that has one, before relying on
this adapter in production. Treat ANTHROPIC_API_KEY absence/invalidity as the
expected default state here, not an edge case.

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
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_TIMEOUT = 20
DEFAULT_MAX_RETRIES = 2
DEFAULT_MAX_TOKENS = 16000  # thinking is always on for current models; leave room for it
DEFAULT_EFFORT = "low"  # extraction/classification work: lowest effort that holds quality


class ClaudeAIProvider(AIProvider):
    """Reads its API key from the environment at call time only — never from
    this repository, never logged, never persisted to any tracker. The model
    is likewise configurable from the environment (`model_env_var`, e.g.
    ANTHROPIC_MODEL), so swapping models never requires a code change — the
    constructor/config value is only the fallback when that env var is unset.
    """
    name = "claude"

    def __init__(self, model=None, timeout=None, max_retries=None, max_tokens=None,
                 api_key_env_var="ANTHROPIC_API_KEY", model_env_var="ANTHROPIC_MODEL", effort=None):
        self._configured_model = model or DEFAULT_MODEL
        self.effort = effort or DEFAULT_EFFORT
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.max_retries = max_retries if max_retries is not None else DEFAULT_MAX_RETRIES
        self.max_tokens = max_tokens or DEFAULT_MAX_TOKENS
        self.api_key_env_var = api_key_env_var
        self.model_env_var = model_env_var
        self.last_usage = None  # {"input_tokens": int, "output_tokens": int} after the most recent successful call

    @property
    def model(self):
        # environment variable wins, so an operator can switch models without
        # touching config/ai.yaml or this code
        return os.environ.get(self.model_env_var) or self._configured_model

    def _api_key(self):
        return os.environ.get(self.api_key_env_var)

    def analyze(self, prompt, context=None):
        """Returns a dict. On any failure (missing key, network error, non-200,
        malformed response), falls back to RuleBasedAIProvider and labels the
        result so the fallback is visible to the caller — never pretends the
        Claude call succeeded.
        """
        context = context or {}
        from scripts.lib import runtime
        if runtime.is_offline():
            return self._fallback(prompt, context, status="NETWORK_OFFLINE", note="NETWORK_MODE=offline — no API call made.")
        api_key = self._api_key()

        if not api_key:
            return self._fallback(prompt, context, status="MISSING_API_KEY",
                                   note=f"No {self.api_key_env_var} set in the environment. "
                                        f"A Claude *consumer* subscription (claude.ai) does not provide this — "
                                        f"generate a key at https://console.anthropic.com/ and set "
                                        f"{self.api_key_env_var} as an environment variable (never in this repo).")

        body = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": "Respond with a single JSON object only, no prose outside the JSON.",
            "messages": [{"role": "user", "content": self._build_prompt(prompt, context)}],
            "output_config": {"effort": self.effort},
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }

        data, error, error_kind = self._post_with_retries(body, headers)
        if error:
            return self._fallback(prompt, context, status=error_kind, note=error)

        if data.get("stop_reason") == "refusal":
            details = data.get("stop_details") or {}
            return self._fallback(prompt, context, status="REFUSAL",
                                  note=f"Model declined the request (category: {details.get('category')}).")
        try:
            # Current models return thinking blocks before the answer: read the first text block.
            text = next(b["text"] for b in data["content"] if b.get("type", "text") == "text" and "text" in b)
            usage = data.get("usage", {})
            self.last_usage = {
                "input_tokens": usage.get("input_tokens"),
                "output_tokens": usage.get("output_tokens"),
            }
            parsed = json.loads(text)
        except (KeyError, IndexError, StopIteration, TypeError, json.JSONDecodeError) as e:
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
        """Returns (data, error_message, error_kind). error_kind is one of
        TIMEOUT / HTTP_ERROR / API_CALL_FAILED, distinguishing a slow/
        unreachable network from a server-returned error from any other
        failure — each surfaces as its own `status` on the caller's result.
        """
        import socket
        import time

        last_error = None
        last_kind = "API_CALL_FAILED"
        for attempt in range(self.max_retries + 1):
            try:
                req = urllib.request.Request(API_URL, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status != 200:
                        last_error, last_kind = f"HTTP {resp.status}", "HTTP_ERROR"
                    else:
                        return json.loads(resp.read()), None, None
            except urllib.error.HTTPError as e:
                # 401/403 (bad/missing key) are not worth retrying blindly;
                # still only reported, never retried past max_retries, never treated as success.
                last_error, last_kind = f"HTTP {e.code}: {e.reason}", "HTTP_ERROR"
                if e.code in (401, 403):
                    break
            except socket.timeout:
                last_error, last_kind = f"Timed out after {self.timeout}s", "TIMEOUT"
            except urllib.error.URLError as e:
                if "timed out" in str(e.reason).lower():
                    last_error, last_kind = f"URLError: {e.reason}", "TIMEOUT"
                else:
                    last_error, last_kind = f"URLError: {e.reason}", "API_CALL_FAILED"
            except Exception as e:  # noqa: BLE001 - this adapter must never crash the pipeline
                last_error, last_kind = f"{type(e).__name__}: {e}", "API_CALL_FAILED"
            if attempt < self.max_retries:
                time.sleep(1.5 ** attempt)
        return None, last_error, last_kind

    def _fallback(self, prompt, context, status, note):
        fallback_result = RuleBasedAIProvider().analyze(prompt, context)
        return {**fallback_result, "provider": self.name, "status": status, "note": note, "fallback_provider": "rule_based"}
