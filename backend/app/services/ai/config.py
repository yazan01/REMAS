"""One place that answers "which model is this deployment allowed to call?".

Both the analysis pipeline (AI-02 → AI-06) and the OCR stage (AI-01) resolve
through here, so an administrator changing the provider in the portal changes it
everywhere at once rather than in two half-synchronised places.

Resolution order, weakest first:

1. environment / `.env` — what the deployment shipped with;
2. the ``platform_settings`` table — what an administrator chose in the portal.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services import settings_store

#: Setting keys, so the routes and the resolver cannot drift apart.
AI_PROVIDER = "ai.provider"
AI_MODEL = "ai.model"
AI_ENABLED = "ai.enabled"
OPENAI_API_KEY = "ai.openai_api_key"
OPENAI_BASE_URL = "ai.openai_base_url"
ANTHROPIC_API_KEY = "ai.anthropic_api_key"
OCR_PROVIDER = "ai.ocr_provider"
OCR_MODEL = "ai.ocr_model"

#: What an administrator may choose. `rules` is the deterministic, no-network
#: provider and is always available — FR-26 requires the platform to produce a
#: full result without any model being reachable.
PROVIDERS = ("rules", "openai", "anthropic")
OCR_PROVIDERS = ("auto", "tesseract", "azure", "openai", "none")

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_OCR_MODEL = "gpt-4o"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-5"


@dataclass(frozen=True)
class AIConfig:
    provider: str
    model: str | None
    api_key: str | None
    base_url: str | None
    enabled: bool
    ocr_provider: str
    ocr_model: str

    @property
    def is_llm(self) -> bool:
        return self.provider in ("openai", "anthropic")

    @property
    def usable(self) -> bool:
        """A configured LLM provider with no key is not a provider."""
        return self.enabled and (self.provider == "rules" or bool(self.api_key))


def default_model(provider: str) -> str | None:
    return {
        "openai": DEFAULT_OPENAI_MODEL,
        "anthropic": DEFAULT_ANTHROPIC_MODEL,
    }.get(provider)


def _env_provider() -> str:
    """What the environment alone implies, for a deployment with no portal row."""
    if (settings.anthropic_api_key or "").strip():
        return "anthropic"
    return "rules"


def resolve(db: Session | None = None) -> AIConfig:
    stored: dict[str, str | None] = settings_store.all_values(db) if db is not None else {}

    provider = (stored.get(AI_PROVIDER) or _env_provider()).lower()
    if provider not in PROVIDERS:
        provider = "rules"

    if provider == "openai":
        api_key = stored.get(OPENAI_API_KEY) or (settings.openai_api_key or "").strip() or None
    elif provider == "anthropic":
        api_key = stored.get(ANTHROPIC_API_KEY) or (settings.anthropic_api_key or "").strip() or None
    else:
        api_key = None

    enabled_raw = stored.get(AI_ENABLED)
    enabled = settings.ai_enabled if enabled_raw is None else enabled_raw == "true"

    ocr_provider = (stored.get(OCR_PROVIDER) or settings.ocr_provider or "auto").lower()
    if ocr_provider not in OCR_PROVIDERS:
        ocr_provider = "auto"

    return AIConfig(
        provider=provider,
        model=stored.get(AI_MODEL) or default_model(provider),
        api_key=api_key,
        base_url=stored.get(OPENAI_BASE_URL) or settings.openai_base_url,
        enabled=enabled,
        ocr_provider=ocr_provider,
        ocr_model=stored.get(OCR_MODEL) or DEFAULT_OPENAI_OCR_MODEL,
    )


def openai_key(db: Session | None = None) -> str | None:
    """The OpenAI key regardless of which provider is selected — the OCR stage
    can be pointed at OpenAI vision while the analysis stays on rules."""
    stored = settings_store.all_values(db) if db is not None else {}
    return stored.get(OPENAI_API_KEY) or (settings.openai_api_key or "").strip() or None
