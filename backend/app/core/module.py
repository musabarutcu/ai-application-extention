"""Agent modül sistemi.

Her yetenek (başvuru asistanı, fırsat bulucu, ...) bir BaseModule'dür.
Yeni modül eklemek:
  1. app/modules/<ad>/ altında BaseModule'den türeyen bir sınıf yaz, @register ile işaretle.
  2. app/modules/__init__.py içinde import et.
Modülün router'ı otomatik olarak /modules/<name> altına bağlanır ve
ortak bağlama (ayarlar, vault, LLM) self.ctx üzerinden erişir.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException

from ..config import Settings
from .llm import LLMProvider
from .vault import Vault


@dataclass
class AgentContext:
    settings: Settings
    vault: Vault
    llm: LLMProvider | None

    def require_llm(self) -> LLMProvider:
        if self.llm is None:
            raise HTTPException(503, "LLM yapılandırılmamış: .env içinde GEMINI_API_KEY değerini ayarla.")
        return self.llm


class BaseModule(ABC):
    name: str = ""
    description: str = ""

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx

    @abstractmethod
    def router(self) -> APIRouter: ...

    def info(self) -> dict[str, str]:
        return {"name": self.name, "description": self.description}


_REGISTRY: list[type[BaseModule]] = []


def register(cls: type[BaseModule]) -> type[BaseModule]:
    _REGISTRY.append(cls)
    return cls


def registered_modules() -> list[type[BaseModule]]:
    return list(_REGISTRY)
