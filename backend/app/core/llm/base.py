"""Sağlayıcıdan bağımsız LLM arayüzü.

Yeni bir sağlayıcı eklemek için LLMProvider'dan
türetip `generate` metodunu yazmak ve `app/core/llm/__init__.py` içindeki
fabrikaya eklemek yeterli.
"""

import json
import re
from abc import ABC, abstractmethod
from typing import Any


class LLMError(Exception):
    pass


class LLMProvider(ABC):
    name = "base"

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str: ...

    def generate_json(self, prompt: str, *, system: str | None = None, temperature: float = 0.2) -> Any:
        raw = self.generate(prompt, system=system, temperature=temperature, json_mode=True)
        return parse_json(raw)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json(raw: str) -> Any:
    text = _FENCE.sub("", raw.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError(f"Model geçerli JSON döndürmedi: {raw[:200]}")
