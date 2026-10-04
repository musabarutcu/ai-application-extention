from ...config import Settings
from .base import LLMError, LLMProvider


def create_provider(settings: Settings) -> LLMProvider | None:
    """Ayarlara göre LLM sağlayıcısını oluşturur. Anahtar yoksa None döner (kural tabanlı mod)."""
    provider = settings.llm_provider.lower()
    if provider == "gemini":
        if not settings.gemini_api_key:
            return None
        from .gemini import GeminiProvider

        fallbacks = [m.strip() for m in settings.gemini_fallback_models.split(",")]
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model, fallbacks)
    raise ValueError(f"Bilinmeyen LLM sağlayıcısı: {settings.llm_provider}")


__all__ = ["LLMError", "LLMProvider", "create_provider"]
