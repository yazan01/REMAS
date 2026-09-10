import logging
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.crypto import generate_master_key, read_secret

log = logging.getLogger("remas.config")

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "REMAS API"
    environment: str = "development"
    api_prefix: str = "/api/v1"

    # SQLite by default so the stack runs with no external services.
    # Point at PostgreSQL for staging/production:
    #   postgresql+psycopg://user:pass@host:5432/remas
    database_url: str = f"sqlite:///{BASE_DIR / 'remas.db'}"

    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60 * 12
    verification_token_hours: int = 48

    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    storage_dir: Path = BASE_DIR / "storage"
    max_upload_mb: int = 25
    allowed_upload_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "image/png",
        "image/jpeg",
    ]

    default_locale: str = "ar"

    # FR-32 allows several assessment tools to exist at once, so "the current
    # framework" has to name one rather than guess at the newest publish.
    default_framework_code: str = "REMAS"

    # AI pipeline. With no key the pipeline still runs on its deterministic
    # provider — see services/ai/provider.py.
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
    # Set only to reach an OpenAI-compatible gateway (Azure OpenAI, a proxy).
    openai_base_url: str | None = None
    ai_model: str = "claude-sonnet-5"
    ai_enabled: bool = True

    # Layer gating (BRD FR-01 / section 10)
    layer_features: dict[str, list[str]] = {
        "quick_score": ["scoring", "dashboard", "evidence_ai_review"],
        "ai_report": ["scoring", "dashboard", "evidence_ai_review", "ai_analysis",
                      "initiatives", "roadmap", "pdf_report"],
        "deep_dive": ["scoring", "dashboard", "evidence_ai_review", "ai_analysis",
                      "initiatives", "roadmap", "pdf_report", "expert_review"],
    }

    # ── security NFR: encryption at rest + secrets management ──────────────
    # Evidence files are encrypted with a per-tenant key derived from this
    # master key. Supply it through EVIDENCE_MASTER_KEY, or mount it as a file
    # and point EVIDENCE_MASTER_KEY_FILE at the path.
    evidence_master_key: str | None = None
    encrypt_evidence: bool = True

    # ── OCR for scanned documents (AI-01 / AI-07) ──────────────────────────
    ocr_provider: str = "auto"  # auto | tesseract | azure | openai | none
    ocr_languages: str = "ara+eng"
    ocr_min_confidence: float = 0.6
    # Second gate: the engine's confidence is unreliable on degraded Arabic, so
    # output that does not read like language is flagged regardless of it.
    ocr_min_plausibility: float = 0.55
    ocr_endpoint: str | None = None
    ocr_api_key: str | None = None
    tesseract_cmd: str | None = None
    # Where the language models live. A local directory keeps `ara.traineddata`
    # under version control of the deployment rather than the OS install.
    tessdata_dir: Path | None = BASE_DIR / "tessdata"

    # ── operations ─────────────────────────────────────────────────────────
    metrics_enabled: bool = True
    backup_dir: Path | None = None


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    # Secrets may arrive as files (Docker/Kubernetes secret mounts) rather than
    # environment variables, so the value never sits in a compose file.
    for field, env in (
        ("jwt_secret", "JWT_SECRET"),
        ("evidence_master_key", "EVIDENCE_MASTER_KEY"),
        ("anthropic_api_key", "ANTHROPIC_API_KEY"),
        ("openai_api_key", "OPENAI_API_KEY"),
        ("ocr_api_key", "OCR_API_KEY"),
        ("database_url", "DATABASE_URL"),
    ):
        value = read_secret(env)
        if value:
            setattr(settings, field, value)

    if settings.environment != "development":
        # Refuse to run a production deployment on the shipped placeholder.
        if settings.jwt_secret == "change-me-in-production":
            raise RuntimeError(
                "JWT_SECRET is still the default placeholder. Set JWT_SECRET or "
                "JWT_SECRET_FILE before starting outside development."
            )
        # RFC 7518 3.2: an HMAC-SHA256 key must be at least as long as the hash.
        if len(settings.jwt_secret.encode("utf-8")) < 32:
            raise RuntimeError(
                "JWT_SECRET must be at least 32 bytes for HS256. Generate one "
                "with: python -m app.core.keygen"
            )
        if settings.encrypt_evidence and not settings.evidence_master_key:
            raise RuntimeError(
                "EVIDENCE_MASTER_KEY is required when encrypt_evidence is on. "
                "Generate one with: python -m app.core.keygen"
            )

    # Short development secrets are stretched rather than used raw, so the
    # signing key always meets the RFC 7518 minimum length.
    if len(settings.jwt_secret.encode("utf-8")) < 32:
        import base64
        import hashlib

        settings.jwt_secret = base64.urlsafe_b64encode(
            hashlib.sha256(settings.jwt_secret.encode("utf-8")).digest()
        ).decode()

    if settings.encrypt_evidence and not settings.evidence_master_key:
        # Development convenience: a stable per-machine key so uploads survive
        # a restart, with a loud warning that it is not a managed secret.
        settings.evidence_master_key = generate_master_key()
        log.warning(
            "EVIDENCE_MASTER_KEY not set — generated an ephemeral development key. "
            "Files encrypted now will not be readable after a restart."
        )

    return settings


settings = get_settings()
