"""Alan hafızası: kullanıcının yan panelde yaptığı düzeltmeleri öğrenir.

Bir form etiketi için türü (profil / cevap / belge / atla) ya da değeri elle düzelttiğinde bu
`vault/Asistan/Alan Hafızası.md` notuna bir tablo satırı olarak yazılır. Aynı (ya da numarası farklı)
etiket bir daha geldiğinde kurallardan ve LLM'den önce bu satır uygulanır. Kullanıcı istemediği
satırı Obsidian'da silebilir.
"""

import re
from dataclasses import dataclass
from datetime import date

from ...core.text import normalize
from ...core.vault import Vault
from .schemas import FormField, LearnItem

MEMORY_NOTE = "Asistan/Alan Hafızası.md"
KINDS = {"profile": "profil", "answer": "cevap", "document": "belge", "skip": "atla"}
_KIND_BACK = {v: k for k, v in KINDS.items()}
_NUMBERING = re.compile(r"^\s*\d{1,3}\s*[-.)]\s*")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")

HEADER = """# Alan Hafızası

Yan panelde bir alanı düzelttiğinde (türünü değiştirdiğinde ya da değerini elle girdiğinde) asistan
bunu buraya yazar ve aynı soruyla tekrar karşılaşınca **sana sormadan** uygular.
İstemediğin bir satırı silebilir ya da düzenleyebilirsin.

- **Tür**: profil · cevap · belge · atla
- **Profil alanı**: değer [[Kişisel Bilgiler]] dosyasındaki bu alandan alınır (güncel kalır)
- **Sabit değer**: profilde karşılığı olmayan, her seferinde aynı yazılan değer
"""
TABLE_HEAD = "| Form etiketi | Tür | Profil alanı | Sabit değer | Kaç kez | Son |\n|---|---|---|---|---|---|"


def label_key(label: str) -> str:
    """'6- Yaşadığın İl*' ve 'Yaşadığın il' aynı anahtara düşer."""
    return normalize(_NUMBERING.sub("", label))


@dataclass
class Learned:
    label: str
    kind: str                 # profile | answer | document | skip
    profile_key: str = ""
    value: str = ""
    count: int = 1
    updated: str = ""


def _esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _unesc(text: str) -> str:
    return text.replace("\\|", "|").strip()


def load_field_memory(vault: Vault) -> dict[str, Learned]:
    note = vault.read(MEMORY_NOTE)
    if not note:
        return {}
    memory = {}
    for line in note.body.splitlines():
        line = line.strip()
        if not line.startswith("|") or line.startswith("|---") or "Form etiketi" in line:
            continue
        cells = [_unesc(c) for c in _CELL_SPLIT.split(line.strip("|"))]
        if len(cells) < 4 or cells[1] not in _KIND_BACK:
            continue
        count = int(cells[4]) if len(cells) > 4 and cells[4].isdigit() else 1
        entry = Learned(cells[0], _KIND_BACK[cells[1]], cells[2].strip("`"), cells[3],
                        count, cells[5] if len(cells) > 5 else "")
        memory[label_key(entry.label)] = entry
    return memory


def save_field_memory(vault: Vault, memory: dict[str, Learned]) -> None:
    rows = sorted(memory.values(), key=lambda e: e.label.lower())
    lines = [TABLE_HEAD] + [
        f"| {_esc(e.label)} | {KINDS[e.kind]} | {f'`{e.profile_key}`' if e.profile_key else ''} | "
        f"{_esc(e.value)} | {e.count} | {e.updated} |"
        for e in rows
    ]
    vault.write(MEMORY_NOTE, {}, HEADER + "\n" + "\n".join(lines))


def _profile_key_for(value: str, profile: dict[str, str]) -> str:
    """Elle girilen değer profildeki bir alanla aynıysa o alanın adı (değer orada güncel kalsın)."""
    target = normalize(value)
    if not target:
        return ""
    return next((key for key, v in profile.items() if normalize(v) == target), "")


def learn(vault: Vault, items: list[LearnItem], profile: dict[str, str]) -> int:
    memory = load_field_memory(vault)
    today = date.today().isoformat()
    learned = 0
    for item in items:
        key = label_key(item.label)
        if not key or item.kind not in KINDS:
            continue
        entry = Learned(item.label.strip(), item.kind, updated=today)
        if item.kind == "profile":
            entry.profile_key = item.profile_key if item.profile_key in profile else _profile_key_for(item.value, profile)
            entry.value = "" if entry.profile_key else item.value.strip()
            if not entry.profile_key and not entry.value:
                continue
        elif item.kind == "document":
            entry.value = item.value.strip()
            if not entry.value:
                continue
        old = memory.get(key)
        same = old and (old.kind, old.profile_key, old.value) == (entry.kind, entry.profile_key, entry.value)
        entry.count = old.count + 1 if same else 1
        memory[key] = entry
        learned += 1
    if learned:
        save_field_memory(vault, memory)
    return learned


def lookup(memory: dict[str, Learned], field: FormField) -> Learned | None:
    return memory.get(label_key(field.label)) if field.label else None
