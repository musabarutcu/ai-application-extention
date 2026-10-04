import pytest

from app.core.llm.base import LLMError
from app.core.llm.gemini import GeminiProvider


class FakeResponse:
    def __init__(self, text):
        self.text = text


def make_provider(behaviour):
    """behaviour: model -> sonuç listesi (Exception ya da metin), sırayla tüketilir."""
    from google.genai import types

    provider = GeminiProvider.__new__(GeminiProvider)
    provider._types = types
    provider.models = list(behaviour)
    provider.rounds = 2
    provider.backoff = 0
    provider.cooldown = 300
    provider._resting = {}
    calls = []

    class Models:
        def generate_content(self, model, contents, config):
            calls.append(model)
            result = behaviour[model].pop(0)
            if isinstance(result, Exception):
                raise result
            return FakeResponse(result)

    provider.client = type("C", (), {"models": Models()})()
    return provider, calls


def test_busy_model_skipped_on_next_request():
    provider, calls = make_provider({"ana": [Exception("503 UNAVAILABLE")], "yedek": ["bir", "iki"]})
    assert provider.generate("x") == "bir"
    assert provider.generate("x") == "iki"
    assert calls == ["ana", "yedek", "yedek"]  # ikinci istekte yoğun model atlandı


def test_falls_back_when_model_removed():
    provider, calls = make_provider({"eski": [Exception("404 NOT_FOUND")], "yeni": ["ok"]})
    assert provider.generate("x") == "ok"
    assert calls == ["eski", "yeni"]


def test_second_round_after_all_busy():
    provider, calls = make_provider({"ana": [Exception("503"), "ok"], "yedek": [Exception("429")]})
    assert provider.generate("x") == "ok"
    assert calls == ["ana", "yedek", "ana"]


def test_gives_up_after_rounds():
    provider, _ = make_provider({"ana": [Exception("503")] * 2})
    with pytest.raises(LLMError, match="yanıt vermiyor"):
        provider.generate("x")


def test_non_retryable_error_raises_immediately():
    provider, calls = make_provider({"ana": [Exception("400 API key not valid")], "yedek": ["ok"]})
    with pytest.raises(LLMError, match="API key"):
        provider.generate("x")
    assert calls == ["ana"]
