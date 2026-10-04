import logging
import re
import secrets

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import modules  # noqa: F401  (modülleri kayıt eder)
from .config import Settings, ensure_token
from .core.llm import create_provider
from .core.module import AgentContext, registered_modules
from .core.profile import load_profile
from .core.vault import Vault

log = logging.getLogger("basvuru_asistani")

_EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")


def create_app(settings: Settings | None = None, ctx: AgentContext | None = None) -> FastAPI:
    if ctx is None:
        settings = settings or Settings()
        ensure_token(settings)
        ctx = AgentContext(settings, Vault(settings.vault_path), create_provider(settings))
    settings = ctx.settings

    def verify_token(x_api_token: str = Header(default="")) -> None:
        if not secrets.compare_digest(x_api_token, settings.api_token):
            raise HTTPException(401, "Geçersiz API token")

    app = FastAPI(title="Başvuru Asistanı", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^chrome-extension://[a-z]+$",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    active_modules = [cls(ctx) for cls in registered_modules()]

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "llm": ctx.llm.name if ctx.llm else None,
            "vault": ctx.vault.root.is_dir(),
            "modules": [m.name for m in active_modules],
        }

    @app.post("/pair")
    def pair(origin: str = Header(default="")):
        """Eklentinin token'ı kendiliğinden alması. Tarayıcılar Origin başlığını sahteletmez;
        bu yüzden yalnızca Chrome eklentilerinden gelen isteklere token verilir."""
        if not _EXTENSION_ORIGIN.match(origin):
            raise HTTPException(403, "Eşleşme yalnızca Chrome eklentisinden yapılabilir")
        return {"token": settings.api_token}

    api = APIRouter(dependencies=[Depends(verify_token)])

    @api.get("/profile")
    def profile():
        return {"profile": load_profile(ctx.vault)}

    @api.get("/modules")
    def list_modules():
        return {"modules": [m.info() for m in active_modules]}

    for module in active_modules:
        api.include_router(module.router(), prefix=f"/modules/{module.name}")

    app.include_router(api)

    if not ctx.vault.root.is_dir():
        log.warning("Vault klasörü bulunamadı: %s", ctx.vault.root)
    if ctx.llm is None:
        log.warning("LLM yapılandırılmamış; sadece kural tabanlı doldurma çalışır.")
    return app
