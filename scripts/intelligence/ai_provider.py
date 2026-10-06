"""AI provider abstraction (V1.4).

The repository MUST run and pass its full test suite without any API key.
`get_ai_provider()` defaults to RuleBasedAIProvider — deterministic local
heuristics, no network calls — per config/ai.yaml's `provider: rule_based`.
Swapping in a real LLM later means implementing `analyze()` on a new
AIProvider subclass and selecting it in config/ai.yaml; nothing else in
scripts/intelligence/ needs to change, since every module here depends only
on this interface.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.lib import config as cfg_lib  # noqa: E402


class AIProvider:
    name = "base"

    def analyze(self, prompt, context=None):
        """prompt: a short description of what's being analyzed.
        context: a dict of grounding facts (skills, requirements, scores...).

        Returns a dict. Implementations must never fabricate facts not
        present in `context` — a rule-based provider reasons only over what
        context supplies; a future LLM provider must be prompted the same way.
        """
        raise NotImplementedError


class RuleBasedAIProvider(AIProvider):
    """Deterministic, local, zero-dependency reasoning used by every
    scripts/intelligence/* module today. 'analyze' here is a dispatch point
    for narrow, explainable rules — not a general-purpose LLM call — so its
    output is fully reproducible and requires no credentials.
    """
    name = "rule_based"

    def analyze(self, prompt, context=None):
        context = context or {}
        return {
            "provider": self.name,
            "prompt": prompt,
            "note": "Rule-based analysis is performed directly by each scripts/intelligence/* "
                    "module using its own explainable logic, grounded only in the supplied context. "
                    "This generic analyze() is a placeholder for a future LLM-backed provider with "
                    "the same interface — it does not itself reason about arbitrary prompts.",
            "context_keys": sorted(context.keys()),
        }


class UnimplementedAIProvider(AIProvider):
    """Returned for a configured provider (openai/claude/local_llm) that has
    no working implementation yet — never silently falls back to pretending
    to be that provider, and never requires or reads an API key to construct.
    """
    def __init__(self, name):
        self.name = name

    def analyze(self, prompt, context=None):
        return {
            **RuleBasedAIProvider().analyze(prompt, context),
            "provider": self.name,
            "status": "NOT_IMPLEMENTED",
            "note": f"Provider '{self.name}' is a configured placeholder (see config/ai.yaml) with no "
                    f"working implementation yet. Falling back to rule_based for this call.",
        }


_PROVIDERS = {
    "rule_based": RuleBasedAIProvider,
}


DEFAULT_TIERS = {"tier_2_min": 70, "tier_3_min": 85, "tier_4_min": 90}


def get_tiers(config=None):
    config = config or cfg_lib.load_ai_config()
    return {**DEFAULT_TIERS, **(config or {}).get("tiers", {})}


def tier_for_score(score, tiers=None):
    """AI cost control (V1.4 Phase 23): 1 = rule-based scoring only,
    2 = job_analyzer runs, 3 = deep analysis, 4 = full application strategy.
    """
    tiers = tiers or get_tiers()
    if score is None:
        return 1
    if score >= tiers["tier_4_min"]:
        return 4
    if score >= tiers["tier_3_min"]:
        return 3
    if score >= tiers["tier_2_min"]:
        return 2
    return 1


def get_ai_provider(config=None):
    """Returns the configured AIProvider instance. Always succeeds without
    any API key: an unimplemented provider name falls back to rule_based
    behavior (wrapped so callers can see the fallback happened) rather than
    raising or pretending to call a real API.
    """
    config = config or cfg_lib.load_ai_config()
    provider_name = (config or {}).get("provider", "rule_based")

    if provider_name in _PROVIDERS:
        return _PROVIDERS[provider_name]()

    provider_meta = (config or {}).get("providers", {}).get(provider_name, {})
    if provider_meta and not provider_meta.get("implemented", False):
        return UnimplementedAIProvider(provider_name)

    return RuleBasedAIProvider()
