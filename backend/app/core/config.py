from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

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

    # AI pipeline. With no key the pipeline still runs on its deterministic
    # provider — see services/ai/provider.py.
    anthropic_api_key: str | None = None
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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()
