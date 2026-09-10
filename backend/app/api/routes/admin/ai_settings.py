"""Which AI provider the platform calls, and the key it calls it with.

FR-31 — configuration, not a code change. The key is sealed before it reaches
the database and is never returned by any endpoint; see
`services/settings_store.py` for the envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_ivalue, require_ivalue_admin
from app.core.config import settings
from app.core.errors import APIError
from app.db.session import get_db
from app.models import User
from app.services import audit, settings_store
from app.services.ai import config as ai_config
from app.services.ai import provider as provider_module

router = APIRouter()

# ─────────────────── AI provider configuration (FR-31, AI-01 → AI-07) ───────


class AISettingsIn(BaseModel):
    """Only the fields the administrator sent are applied; omitting `api_key`
    leaves the stored key untouched, which is what lets the form be saved
    without retyping the secret."""

    provider: str | None = None
    model: str | None = None
    enabled: bool | None = None
    api_key: str | None = None
    base_url: str | None = None
    ocr_provider: str | None = None
    ocr_model: str | None = None


def _ai_state(db: Session) -> dict:
    cfg = ai_config.resolve(db)
    stored_hints = settings_store.hints(db)
    from app.services.ai import ocr as ocr_engine

    return {
        "provider": cfg.provider,
        "model": cfg.model,
        "enabled": cfg.enabled,
        "base_url": cfg.base_url,
        "ocr_provider": cfg.ocr_provider,
        "ocr_model": cfg.ocr_model,
        # Which engine an upload would actually be read by right now — the
        # selection and the reality can differ when a key is missing.
        "ocr_effective": ocr_engine.available_provider(cfg) or "none",
        "providers": list(ai_config.PROVIDERS),
        "ocr_providers": list(ai_config.OCR_PROVIDERS),
        "default_models": {
            "openai": ai_config.DEFAULT_OPENAI_MODEL,
            "anthropic": ai_config.DEFAULT_ANTHROPIC_MODEL,
        },
        # Never the key itself.
        "openai_key_hint": stored_hints.get(ai_config.OPENAI_API_KEY),
        "anthropic_key_hint": stored_hints.get(ai_config.ANTHROPIC_API_KEY),
        "openai_key_from_env": bool((settings.openai_api_key or "").strip()),
        "anthropic_key_from_env": bool((settings.anthropic_api_key or "").strip()),
        "key_present": bool(cfg.api_key),
        # A provider that is selected but has no reachable key silently degrades
        # to the deterministic engine; say so rather than let it look configured.
        "effective_provider": provider_module.build(cfg).info.name,
        "secrets_encrypted": bool(settings.evidence_master_key),
    }


@router.get("/settings/ai", response_model=dict)
def get_ai_settings(_u: User = Depends(require_ivalue), db: Session = Depends(get_db)) -> dict:
    return _ai_state(db)


@router.put("/settings/ai", response_model=dict)
def update_ai_settings(
    payload: AISettingsIn,
    request: Request,
    actor: User = Depends(require_ivalue_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Store the AI configuration. The key is sealed with AES-256-GCM before it
    reaches the table and is never returned by any endpoint."""
    if payload.provider is not None and payload.provider not in ai_config.PROVIDERS:
        raise APIError(
            "ai.unknown_provider", status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"valid": list(ai_config.PROVIDERS)},
        )
    if payload.ocr_provider is not None and payload.ocr_provider not in ai_config.OCR_PROVIDERS:
        raise APIError(
            "ai.unknown_provider", status.HTTP_422_UNPROCESSABLE_CONTENT,
            {"valid": list(ai_config.OCR_PROVIDERS)},
        )
    if payload.api_key and not settings.evidence_master_key:
        # Storing it unsealed would break the security NFR; refuse instead.
        raise APIError("ai.no_master_key", status.HTTP_409_CONFLICT)

    target_provider = payload.provider or ai_config.resolve(db).provider
    changed: list[str] = []

    def store(key: str, value: str | None, *, secret: bool = False) -> None:
        settings_store.put(db, key, value, secret=secret, actor_id=actor.id)
        changed.append(key)

    if payload.provider is not None:
        store(ai_config.AI_PROVIDER, payload.provider)
        if payload.model is None:
            # Switching provider without naming a model would otherwise leave
            # the previous provider's model id behind.
            store(ai_config.AI_MODEL, ai_config.default_model(payload.provider))
    if payload.model is not None:
        store(ai_config.AI_MODEL, payload.model.strip() or None)
    if payload.enabled is not None:
        store(ai_config.AI_ENABLED, "true" if payload.enabled else "false")
    if payload.base_url is not None:
        store(ai_config.OPENAI_BASE_URL, payload.base_url.strip() or None)
    if payload.ocr_provider is not None:
        store(ai_config.OCR_PROVIDER, payload.ocr_provider)
    if payload.ocr_model is not None:
        store(ai_config.OCR_MODEL, payload.ocr_model.strip() or None)
    if payload.api_key is not None:
        key_name = (
            ai_config.ANTHROPIC_API_KEY
            if target_provider == "anthropic"
            else ai_config.OPENAI_API_KEY
        )
        store(key_name, payload.api_key.strip() or None, secret=True)

    audit.record(
        db, action="admin.ai_settings_updated", entity_type="platform_settings",
        entity_id=None, actor=actor,
        # The key value is never written to the audit trail, only the fact that
        # it changed.
        payload={"keys": changed, "provider": target_provider},
        ip_address=client_ip(request),
    )
    db.commit()
    settings_store.invalidate()
    return _ai_state(db)


@router.post("/settings/ai/test", response_model=dict)
def test_ai_settings(
    request: Request,
    actor: User = Depends(require_ivalue_admin),
    db: Session = Depends(get_db),
) -> dict:
    """Send one tiny prompt to the configured model and report what came back.

    Worth its own endpoint: a wrong key or an unavailable model otherwise shows
    up as silently degraded output on a customer's report, hours later.
    """
    import time

    cfg = ai_config.resolve(db)
    if cfg.provider == "rules":
        return {"ok": True, "provider": "rules", "model": None,
                "detail": "deterministic", "latency_ms": 0}
    if not cfg.api_key:
        return {"ok": False, "provider": cfg.provider, "model": cfg.model,
                "detail": "no_api_key", "latency_ms": None}

    started = time.perf_counter()
    try:
        provider = provider_module.build(cfg)
        if provider.info.name == "rules":
            return {"ok": False, "provider": cfg.provider, "model": cfg.model,
                    "detail": "sdk_unavailable", "latency_ms": None}
        answer = provider.complete_json(
            "You are a connectivity probe.",
            'Reply with exactly {"ok": true} and nothing else.',
            max_tokens=64,
        )
        latency = int((time.perf_counter() - started) * 1000)
        ok = isinstance(answer, dict)
        audit.record(
            db, action="admin.ai_settings_tested", entity_type="platform_settings",
            entity_id=None, actor=actor,
            payload={"provider": cfg.provider, "model": cfg.model, "ok": ok},
            ip_address=client_ip(request),
        )
        db.commit()
        return {"ok": ok, "provider": provider.info.name, "model": provider.info.model,
                "detail": "reachable" if ok else "unparsable_response",
                "latency_ms": latency}
    except Exception as exc:  # noqa: BLE001 - the reason is the whole point
        return {
            "ok": False,
            "provider": cfg.provider,
            "model": cfg.model,
            # Message text can carry the key back in some SDK errors; the type
            # name is enough to tell an auth failure from a network failure.
            "detail": type(exc).__name__,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
