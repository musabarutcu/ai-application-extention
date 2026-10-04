"""Vault'taki profil notlarını agent'ın kullanacağı forma çevirir."""

from datetime import date
from typing import Any

from .vault import Vault

PROFILE_NOTE = "Profil/Kişisel Bilgiler.md"
BACKGROUND_NOTES = [
    "Profil/Hakkımda.md",
    "Profil/İlgi Alanları.md",
    "Profil/Deneyimler.md",
    "Profil/Projeler.md",
    "Profil/Beceriler.md",
]
PREFERENCES_NOTE = "Asistan/Ayarlar.md"

# Değerleri LLM'e asla gönderilmeyen alanlar: LLM yalnızca anahtar adını görür,
# değer forma yerel olarak yazılır.
SENSITIVE_KEYS = frozenset({
    "tc_kimlik_no", "pasaport_no", "pasaport_gecerlilik", "iban", "banka",
    "dogum_tarihi", "dogum_yeri", "yas", "adres", "telefon", "eposta",
    # mali / sosyal durum (burs formları)
    "ev_durumu", "kira_tutari", "kendi_gelirim", "calisiyor_musun", "baska_burs", "engel_durumu",
    "sehit_gazi_yakini",
})
# Bu öneklerle başlayan her alan hassastır (aile bilgileri; kullanıcı yenilerini ekleyebilir)
SENSITIVE_PREFIXES = ("baba_", "anne_", "kardes", "okuyan_kardes", "hane_", "aile_")
MASK = "<gizli: yerel olarak doldurulur>"


def is_sensitive(key: str) -> bool:
    return key in SENSITIVE_KEYS or key.startswith(SENSITIVE_PREFIXES)


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_to_text(v) for v in value if _to_text(v))
    return str(value).strip()


def _age(birth: str, today: date) -> int | None:
    try:
        born = date.fromisoformat(birth[:10])
    except ValueError:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def load_profile(vault: Vault, today: date | None = None) -> dict[str, str]:
    """Kişisel Bilgiler notunun frontmatter'ı; boş alanlar atlanır, türetilen alanlar eklenir."""
    note = vault.read(PROFILE_NOTE)
    if not note:
        return {}
    profile = {key: text for key, value in note.meta.items() if (text := _to_text(value))}
    for full, first, last in (("ad_soyad", "ad", "soyad"),
                              ("baba_ad_soyad", "baba_adi", "baba_soyadi"),
                              ("anne_ad_soyad", "anne_adi", "anne_soyadi")):
        if profile.get(first) and profile.get(last):
            profile.setdefault(full, f"{profile[first]} {profile[last]}")
    if "dogum_tarihi" in profile and "yas" not in profile:
        age = _age(profile["dogum_tarihi"], today or date.today())
        if age is not None:
            profile["yas"] = str(age)
    return profile


def masked_profile(profile: dict[str, str]) -> dict[str, str]:
    """LLM'e gönderilecek profil: hassas değerler maskelenir."""
    return {key: (MASK if is_sensitive(key) else value) for key, value in profile.items()}


def load_background(vault: Vault) -> str:
    """Hakkımda, ilgi alanları, deneyimler vb. serbest metin notlarını birleştirir."""
    sections = []
    for rel in BACKGROUND_NOTES:
        note = vault.read(rel)
        if note and note.content:
            sections.append(f"### {note.title}\n{note.content}")
    return "\n\n".join(sections)


def load_preferences(vault: Vault) -> str:
    note = vault.read(PREFERENCES_NOTE)
    if not note:
        return ""
    lines = [f"- {key}: {text}" for key, value in note.meta.items() if (text := _to_text(value))]
    if note.content:
        lines.append(note.content)
    return "\n".join(lines)
