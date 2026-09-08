"""LLM provider abstraction for the analysis stages (AI-02 → AI-06).

Two providers ship:

* ``AnthropicProvider`` — used when ``ANTHROPIC_API_KEY`` is configured. Sends
  the assessment's own data and asks for structured JSON back.
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

from app.core.config import settings

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


def get_provider() -> BaseProvider:
    key = (settings.anthropic_api_key or "").strip()
    if key:
        try:
            return AnthropicProvider(key, settings.ai_model)
        except Exception as exc:  # noqa: BLE001
            log.warning("Anthropic provider unavailable (%s) — falling back to rules", exc)
    return RuleProvider()
