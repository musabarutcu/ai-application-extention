import logging
import time

from .base import LLMError, LLMProvider

log = logging.getLogger(__name__)

# Geçici hatalar: yoğunluk / kota / sunucu hatası.
_RETRYABLE = ("503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL")
# Kalıcı model hatası: model kaldırılmış / yok.
_MODEL_GONE = ("404", "NOT_FOUND")


class GeminiProvider(LLMProvider):
    """Gemini sağlayıcısı. Yoğun ya da kaldırılmış modeli bir süre dinlenmeye alır ve
    sıradaki yedek modele geçer; böylece sonraki istekler doğrudan çalışan modele gider."""

    name = "gemini"

    def __init__(self, api_key: str, model: str, fallback_models: list[str] | None = None,
                 rounds: int = 2, backoff: float = 2.0, cooldown: float = 300.0):
        from google import genai
        from google.genai import types

        self._types = types
        self.client = genai.Client(api_key=api_key)
        self.models = [model, *[m for m in (fallback_models or []) if m and m != model]]
        self.rounds = rounds
        self.backoff = backoff
        self.cooldown = cooldown
        self._resting: dict[str, float] = {}  # model -> dinlenmenin bittiği an

    def _candidates(self) -> list[str]:
        now = time.monotonic()
        ready = [m for m in self.models if self._resting.get(m, 0) <= now]
        return ready or list(self.models)  # hepsi dinleniyorsa yine de dene

    def _call(self, model: str, prompt: str, config) -> str:
        response = self.client.models.generate_content(model=model, contents=prompt, config=config)
        if not response.text:
            raise LLMError("Gemini boş yanıt döndürdü")
        return response.text

    def generate(self, prompt, *, system=None, temperature=0.7, json_mode=False):
        config = self._types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
            automatic_function_calling=self._types.AutomaticFunctionCallingConfig(disable=True),
        )
        last_error: Exception | None = None
        for round_no in range(self.rounds):
            if round_no:
                time.sleep(self.backoff * round_no)
            for model in self._candidates():
                try:
                    text = self._call(model, prompt, config)
                    self._resting.pop(model, None)
                    return text
                except LLMError:
                    raise
                except Exception as exc:  # SDK farklı hata tipleri fırlatabiliyor
                    last_error = exc
                    message = str(exc)
                    gone = any(code in message for code in _MODEL_GONE)
                    if not gone and not any(code in message for code in _RETRYABLE):
                        raise LLMError(f"Gemini hatası: {exc}") from exc
                    rest = self.cooldown * (12 if gone else 1)
                    self._resting[model] = time.monotonic() + rest
                    log.warning("Gemini modeli %s %s, %d sn dinlenmeye alındı",
                                model, "kullanılamıyor" if gone else "yoğun", rest)
        raise LLMError(f"Gemini şu an yanıt vermiyor (denenen modeller: {', '.join(self.models)}). "
                       f"Biraz sonra tekrar dene. Son hata: {last_error}")
