"""LLM provider abstraction for the analysis stages (AI-02 → AI-06).

Three providers ship:

* ``OpenAIProvider`` — selected from the administration portal, where the
  API key is entered and stored encrypted. Asks for a JSON object back.
* ``AnthropicProvider`` — the same contract against Claude.
* ``RuleProvider`` — the default. Produces the same shaped output from the
  deterministic scoring result and the extracted document text, with no network
  call at all.

Keeping the fallback first-class matters for two reasons the BRD raises: the
deployment jurisdiction may forbid sending client evidence to an external model
(NFR — privacy), and FR-26 requires the platform to work without AI touching the
calculation. The pipeline therefore always runs; the provider only changes how
rich the wording is.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.ai import config as ai_config

log = logging.getLogger("remas.ai.provider")

PROMPT_VERSION = "1.0"


@dataclass
class ProviderInfo:
    name: str
    model: str | None


class BaseProvider:
    info: ProviderInfo

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> Any:
        raise NotImplementedError


class AnthropicProvider(BaseProvider):
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.info = ProviderInfo(name="anthropic", model=model)

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> Any:
        response = self._client.messages.create(
            model=self.info.model or settings.ai_model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
        return _parse_json(text)


class OpenAIProvider(BaseProvider):
    """Chat Completions in JSON mode.

    `response_format=json_object` is what makes this safe to parse: without it
    the model is free to wrap the object in prose, and a stage that cannot parse
    its answer silently degrades to the rule output.
    """

    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key, base_url=base_url or None, timeout=120.0)
        self.info = ProviderInfo(name="openai", model=model)

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> Any:
        response = self._client.chat.completions.create(
            model=self.info.model or ai_config.DEFAULT_OPENAI_MODEL,
            max_completion_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                # JSON mode requires the word "json" to appear in the prompt.
                {
                    "role": "system",
                    "content": system + "\n\nRespond with a single JSON object.",
                },
                {"role": "user", "content": user},
            ],
        )
        return _parse_json(response.choices[0].message.content or "")


class RuleProvider(BaseProvider):
    """No network. The pipeline supplies pre-computed structures and this
    provider passes them through, so every stage still produces real, traceable
    output on a machine with no API key."""

    def __init__(self) -> None:
        self.info = ProviderInfo(name="rules", model=None)

    def complete_json(self, system: str, user: str, max_tokens: int = 4000) -> Any:
        return None


def _parse_json(text: str) -> Any:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min((i for i in (text.find("{"), text.find("[")) if i >= 0), default=-1)
        if start < 0:
            return None
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
    return None


def build(cfg: ai_config.AIConfig) -> BaseProvider:
    """Instantiate the configured provider, or the rule provider if it cannot be
    reached. A missing key is a configuration state, not an error: the pipeline
    still has to produce a full, traceable result (FR-26)."""
    if not cfg.usable or cfg.provider == "rules":
        return RuleProvider()
    try:
        if cfg.provider == "openai":
            return OpenAIProvider(
                cfg.api_key or "", cfg.model or ai_config.DEFAULT_OPENAI_MODEL, cfg.base_url
            )
        if cfg.provider == "anthropic":
            return AnthropicProvider(
                cfg.api_key or "", cfg.model or ai_config.DEFAULT_ANTHROPIC_MODEL
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("%s provider unavailable (%s) — falling back to rules", cfg.provider, exc)
    return RuleProvider()


def get_provider(db: Session | None = None) -> BaseProvider:
    return build(ai_config.resolve(db))
