"""Türkçe/İngilizce metin yardımcıları."""

import re
import unicodedata

_TR_MAP = str.maketrans({"ı": "i", "ş": "s", "ğ": "g", "ü": "u", "ö": "o", "ç": "c"})

STOPWORDS = {
    # tr
    "bir", "bu", "şu", "ve", "ile", "için", "icin", "ama", "gibi", "daha", "çok", "cok", "olan", "olarak",
    "neden", "nasil", "nedir", "hangi", "sizin", "bizim", "sizi", "sen", "siz", "ben", "biz", "bunu",
    "kadar", "veya", "yada", "her", "ise", "mi", "mu", "lutfen", "kisaca", "ne", "nedenleri",
    # en
    "the", "and", "for", "you", "your", "with", "this", "that", "are", "what", "why", "how", "our",
    "who", "which", "please", "describe", "about", "have", "has", "from", "into", "would", "will",
}

_WORD_LIMIT = re.compile(r"(\d{2,5})\s+(?:kelime|sozcuk|words?)\b")
_CHAR_LIMIT = re.compile(r"(\d{2,5})\s+(?:karakter|characters?|chars?)\b")


def normalize(text: str) -> str:
    """Küçük harf, Türkçe karakterleri ASCII'ye indir, noktalama -> boşluk."""
    text = (text or "").replace("İ", "i").lower().translate(_TR_MAP)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def tokens(text: str) -> list[str]:
    return [t for t in normalize(text).split() if len(t) >= 3 and t not in STOPWORDS]


def detect_limits(text: str) -> tuple[int | None, int | None]:
    """Soru metnindeki '300 kelime', 'max 1000 characters' gibi sınırları bulur."""
    norm = normalize(text)
    chars = _CHAR_LIMIT.search(norm)
    words = _WORD_LIMIT.search(norm)
    return (int(chars.group(1)) if chars else None, int(words.group(1)) if words else None)


def fit_to_limits(text: str, max_chars: int | None = None, max_words: int | None = None) -> str:
    """Sınırı aşan metni, mümkünse cümle sonundan keserek kısaltır."""
    text = text.strip()
    truncated = False
    if max_words:
        words = text.split()
        if len(words) > max_words:
            text = " ".join(words[:max_words])
            truncated = True
    if max_chars and len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    if truncated:
        end = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
        if end >= len(text) * 0.6:
            text = text[: end + 1]
    return text.strip()


def detect_language(text: str) -> str:
    return "tr" if re.search(r"[çğıöşüÇĞİÖŞÜ]", text) else "en"
