"""`python -m app` ile backend'i başlatır.

`pythonw -m app` ile penceresiz de çalışır (Windows açılışında otomatik başlatma böyle yapılır);
o durumda çıktılar `%LOCALAPPDATA%\\basvuru-asistani\\backend.log` dosyasına yazılır.
"""

import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

from .config import Settings, ensure_token

LOG_FILE = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "basvuru-asistani" / "backend.log"


def _already_running(host: str, port: int) -> bool:
    """Port doluysa ve orada zaten Başvuru Asistanı çalışıyorsa True."""
    with socket.socket() as sock:
        sock.settimeout(0.5)
        if sock.connect_ex((host, port)) != 0:
            return False
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2) as res:
            return json.load(res).get("status") == "ok"
    except Exception:
        return False


def _redirect_output_if_windowless() -> None:
    # pythonw'da konsol yoktur (sys.stdout None); loglar dosyaya gider
    if sys.stdout is None or sys.stderr is None:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        stream = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream


if __name__ == "__main__":
    _redirect_output_if_windowless()
    settings = Settings()
    ensure_token(settings)
    if _already_running(settings.host, settings.port):
        print(f"Başvuru Asistanı zaten çalışıyor: http://{settings.host}:{settings.port}")
        sys.exit(0)

    import uvicorn

    print(f"\n  Başvuru Asistanı -> http://{settings.host}:{settings.port}")
    print(f"  Vault           -> {settings.vault_path}")
    print("  Eklenti backend'e otomatik bağlanır.\n")
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
