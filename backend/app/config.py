"""Uygulama ayarları. Değerler proje kökündeki .env dosyasından okunur."""

import secrets
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = "gemini"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    # Ana model yoğun/kaldırılmışsa sırayla denenecek yedekler (virgülle ayrılmış)
    gemini_fallback_models: str = "gemini-3.8-flash,gemini-3.5-flash,gemini-flash-lite-latest"

    vault_path: Path = PROJECT_ROOT / "vault"
    api_token: str = ""

    host: str = "127.0.0.1"
    port: int = 8765

    @field_validator("vault_path")
    @classmethod
    def _resolve_vault(cls, value: Path) -> Path:
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


def ensure_token(settings: Settings, env_file: Path = ENV_FILE) -> str:
    """API_TOKEN boşsa üretir ve .env dosyasına ekler."""
    if settings.api_token:
        return settings.api_token
    token = secrets.token_urlsafe(24)
    existing = env_file.read_text(encoding="utf-8") if env_file.exists() else ""
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    with env_file.open("a", encoding="utf-8") as fh:
        fh.write(f"{prefix}API_TOKEN={token}\n")
    settings.api_token = token
    return token
