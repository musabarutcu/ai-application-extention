import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.core.llm.base import LLMProvider
from app.core.module import AgentContext
from app.core.vault import Vault
from app.server import create_app

FIXTURE_VAULT = Path(__file__).parent / "fixtures" / "vault"
TOKEN = "test-token"


class FakeLLM(LLMProvider):
    """Gerçek API çağırmadan, son prompt'u saklayıp sabit yanıt döner."""

    name = "fake"

    def __init__(self, response: str):
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt, *, system=None, temperature=0.7, json_mode=False):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def vault(tmp_path) -> Vault:
    root = tmp_path / "vault"
    shutil.copytree(FIXTURE_VAULT, root)
    return Vault(root)


def make_client(vault: Vault, llm: LLMProvider | None = None) -> TestClient:
    settings = Settings(_env_file=None, api_token=TOKEN, vault_path=vault.root)
    app = create_app(ctx=AgentContext(settings, vault, llm))
    return TestClient(app, headers={"X-API-Token": TOKEN})
