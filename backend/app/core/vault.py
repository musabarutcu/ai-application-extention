"""Obsidian vault erişimi: Markdown notları + YAML frontmatter."""

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import frontmatter

_INVALID_CHARS = re.compile(r'[<>:"/\\|?*#^\[\]\x00-\x1f]')
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def safe_filename(name: str, max_len: int = 80) -> str:
    cleaned = re.sub(r"\s+", " ", _INVALID_CHARS.sub("", name)).strip().strip(".")
    return cleaned[:max_len].strip() or "Adsız"


def strip_comments(text: str) -> str:
    """Şablonlardaki <!-- yönlendirme --> yorumlarını çıkarır."""
    return _COMMENT.sub("", text).strip()


@dataclass
class Note:
    path: str  # vault köküne göre, '/' ayraçlı
    meta: dict[str, Any]
    body: str

    @property
    def title(self) -> str:
        return PurePosixPath(self.path).stem

    @property
    def content(self) -> str:
        return strip_comments(self.body)


class Vault:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def _abs(self, rel: str) -> Path:
        path = (self.root / rel).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"Vault dışına erişim engellendi: {rel}")
        return path

    def _rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def exists(self, rel: str) -> bool:
        return self._abs(rel).exists()

    def read(self, rel: str) -> Note | None:
        path = self._abs(rel)
        if not path.is_file():
            return None
        post = frontmatter.load(path, encoding="utf-8")
        return Note(self._rel(path), dict(post.metadata), post.content)

    def list(self, folder: str) -> list[Note]:
        """Klasördeki notlar. '_' ile başlayan dosyalar (açıklama notları) atlanır."""
        directory = self._abs(folder)
        if not directory.is_dir():
            return []
        notes = []
        for path in sorted(directory.glob("*.md")):
            if path.name.startswith("_"):
                continue
            note = self.read(self._rel(path))
            if note:
                notes.append(note)
        return notes

    def write(self, rel: str, meta: dict[str, Any], body: str) -> Note:
        path = self._abs(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(body)
        post.metadata.update(meta)
        text = frontmatter.dumps(post, allow_unicode=True, sort_keys=False)
        path.write_text(text + "\n", encoding="utf-8")
        return Note(self._rel(path), dict(meta), body)

    def unique_path(self, folder: str, stem: str) -> str:
        stem = safe_filename(stem)
        candidate = f"{folder}/{stem}.md"
        counter = 2
        while self.exists(candidate):
            candidate = f"{folder}/{stem} ({counter}).md"
            counter += 1
        return candidate
