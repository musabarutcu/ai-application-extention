"""Vault'taki belgeler (adli sicil, transkript, öğrenci belgesi...) ve form alanlarıyla eşleştirme.

Belgeler `vault/Belgeler/` (alt klasörler dahil) içinde düz dosya olarak durur. Her belgenin yanında
aynı adlı bir bilgi notu (`<belge>.md`) bulunur; ilk görüldüğünde otomatik oluşturulur:

    tur: adli_sicil          # belge türü (DOC_TYPES anahtarı)
    sahip: ben               # ben | baba | anne | kardes
    alinma_tarihi: 2026-09-14  # PDF içindeki belge tarihinden okunur, kullanıcı düzeltebilir

Belge içerikleri ve sahiplerinin adları LLM'e asla gönderilmez; en fazla "Öğrenci belgesi (kardeş)"
gibi anonim bir tanım görünür.
"""

import logging
import mimetypes
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath

from .text import normalize
from .vault import Vault

log = logging.getLogger(__name__)

DOCS_FOLDER = "Belgeler"
DOC_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".heic", ".doc", ".docx", ".zip"}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# tür -> görünen ad, eşleşme kalıpları, "genelde son kaç gün içinde alınmış olmalı" (uyarı için)
DOC_TYPES: dict[str, dict] = {
    "adli_sicil": {"ad": "Adli sicil kaydı", "taze_gun": 90,
                   "kalip": ["adli sicil", "adli sicil kaydı", "sabıka kaydı", "sabika", "criminal record"]},
    "ogrenci_belgesi": {"ad": "Öğrenci belgesi", "taze_gun": 60,
                        "kalip": ["öğrenci belgesi", "öğrencilik belgesi", "student certificate",
                                  "enrollment certificate", "proof of enrollment"]},
    "kardes_belgesi": {"ad": "Kardeş öğrenci belgesi", "taze_gun": 60,
                       "kalip": ["kardeş öğrenci belgesi", "kardeşinizin öğrenci belgesi", "kardeşinin öğrenci belgesi",
                                 "kardeşlerinizin öğrenci belgesi", "kardeş öğrenci"]},
    "transkript": {"ad": "Transkript", "taze_gun": 180,
                   "kalip": ["transkript", "not dökümü", "not durum belgesi", "transcript"]},
    "disiplin_belgesi": {"ad": "Disiplin durum belgesi", "taze_gun": 90,
                         "kalip": ["disiplin durum belgesi", "disiplin belgesi", "disiplin cezası", "disiplin durumu"]},
    "kimlik": {"ad": "Kimlik", "taze_gun": None,
               "kalip": ["kimlik kartı", "kimlik fotokopisi", "nüfus cüzdanı", "kimlik ön", "kimlik arka", "id card",
                         "identity card", "kimlik belgesi", "tc kimlik"]},
    "nufus_kayit": {"ad": "Nüfus kayıt örneği", "taze_gun": 90,
                    "kalip": ["nüfus kayıt örneği", "vukuatlı nüfus", "nüfus kayıt", "aile nüfus kayıt", "nüfus kağıt",
                              "nüfus kağıdı"]},
    "ikametgah": {"ad": "Yerleşim yeri belgesi", "taze_gun": 90,
                  "kalip": ["ikametgah", "yerleşim yeri", "proof of address", "residence certificate"]},
    "gelir_belgesi": {"ad": "Gelir belgesi", "taze_gun": 90,
                      "kalip": ["gelir belgesi", "aile gelir", "maaş bordrosu", "bordro", "gelir durumu",
                                "income statement", "maaş belgesi"]},
    "sgk": {"ad": "SGK hizmet dökümü", "taze_gun": 90,
            "kalip": ["sgk", "hizmet dökümü", "sigortalılık", "4a hizmet"]},
    "mal_varligi": {"ad": "Mal varlığı belgesi", "taze_gun": 90,
                    "kalip": ["tapu", "araç kaydı", "mal varlığı", "taşınmaz", "araç yoktur"]},
    "burs_belgesi": {"ad": "Burs / kredi belgesi", "taze_gun": 90,
                     "kalip": ["kyk", "burs belgesi", "kredi burs", "burs durum belgesi", "burs aldığına dair",
                               "burs almadığına dair"]},
    "osym_sonuc": {"ad": "ÖSYM sınav sonuç belgesi", "taze_gun": None,
                   "kalip": ["ösym sınav", "sınav sonuç belgesi", "sınav sonucu", "yks sonuç", "ösym sonuç"]},
    "osym_yerlestirme": {"ad": "ÖSYM yerleştirme sonuç belgesi", "taze_gun": None,
                         "kalip": ["yerleştirme sonucu", "yerleştirme sonuç", "yerleştirme belgesi", "ösym yerleştirme"]},
    "yatay_gecis": {"ad": "Yatay geçiş belgesi", "taze_gun": None,
                    "kalip": ["yatay geçiş", "engel yoktur"]},
    "cv": {"ad": "CV / özgeçmiş", "taze_gun": None,
           "kalip": ["cv", "özgeçmiş", "resume", "curriculum vitae"]},
    "motivasyon_mektubu": {"ad": "Motivasyon mektubu", "taze_gun": None,
                           "kalip": ["motivasyon mektubu", "niyet mektubu", "motivation letter", "cover letter",
                                     "statement of purpose"]},
    "referans_mektubu": {"ad": "Referans mektubu", "taze_gun": None,
                         "kalip": ["referans mektubu", "tavsiye mektubu", "recommendation letter", "reference letter"]},
    "dil_belgesi": {"ad": "Dil belgesi", "taze_gun": None,
                    "kalip": ["yds", "yökdil", "toefl", "ielts", "dil belgesi", "dil sınavı", "language certificate"]},
    "diploma": {"ad": "Diploma / mezuniyet belgesi", "taze_gun": None,
                "kalip": ["diploma", "mezuniyet belgesi", "lise mezuniyet", "lise diploması"]},
    "pasaport": {"ad": "Pasaport", "taze_gun": None, "kalip": ["pasaport", "passport"]},
    "fotograf": {"ad": "Vesikalık fotoğraf", "taze_gun": None,
                 "kalip": ["vesikalık", "fotoğraf", "photo", "photograph"]},
    "sertifika": {"ad": "Sertifika", "taze_gun": None, "kalip": ["sertifika", "certificate", "katılım belgesi"]},
}
def _stem_regex(pattern: str) -> re.Pattern:
    """Türkçe ekleri tolere eden kalıp: uzun kelimelerin kökü + herhangi bir ek
    ("öğrenci belgesi" ~ "öğrenci belgenizi", "adli sicil kaydı" ~ "adli sicil kaydınız")."""
    parts = []
    for word in normalize(pattern).split():
        parts.append(re.escape(word[: max(4, len(word) - 3)]) + r"\w*" if len(word) >= 5 else re.escape(word))
    return re.compile(r"\b" + r"\s+".join(parts) + r"\b")


_PATTERNS = [(key, normalize(p), _stem_regex(p)) for key, spec in DOC_TYPES.items() for p in spec["kalip"]]
# Uzun kalıplar önce: "kardeş öğrenci belgesi" > "öğrenci belgesi", "kimlik arka" > "fotoğraf"
_PATTERNS.sort(key=lambda item: len(item[1]), reverse=True)

# Doğası gereği aileye ait olabilen belgeler (sahip belirtilmemişse anne/baba belgesi de uygun)
FAMILY_TYPES = {"gelir_belgesi", "mal_varligi"}
OWNERS = {"ben": "Ben", "baba": "Baba", "anne": "Anne", "kardes": "Kardeş"}
_OWNER_HINTS = [
    ("kardes", ["kardes", "kardesinizin", "kardesinin", "sibling", "brother", "sister"]),
    ("baba", ["baba", "babanizin", "babanin", "father"]),
    ("anne", ["anne", "annenizin", "annenin", "mother"]),
    ("aile", ["aile", "ailenizin", "veli", "velinizin", "ebeveyn", "parent", "parents", "family", "household"]),
]
_DATE = re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b")


def detect_type(text: str) -> str | None:
    norm = normalize(text)
    for key, _, regex in _PATTERNS:
        if regex.search(norm):
            return key
    return None


def requested_owner(text: str) -> str | None:
    """Form alanı kimin belgesini istiyor? (baba / anne / kardes / aile / None=kişinin kendisi)"""
    words = set(normalize(text).split())
    for owner, hints in _OWNER_HINTS:
        if words & set(hints):
            return owner
    return None


def _family_names(profile: dict[str, str]) -> list[tuple[str, str]]:
    """(sahip, normalize edilmiş ad) çiftleri. Kardeş adları 'Ad Soyad (abla), ...' biçiminden ayrıştırılır."""
    names = []
    for owner, key in (("baba", "baba_adi"), ("anne", "anne_adi")):
        if profile.get(key):
            names.append((owner, normalize(profile[key])))
    for part in (profile.get("kardesler") or "").split(","):
        full = re.sub(r"\(.*?\)", "", part).strip()
        surname = normalize(profile.get("soyad", ""))
        first = normalize(full)
        if surname and first.endswith(" " + surname):
            first = first[: -len(surname) - 1]
        if first:
            names.append(("kardes", first))
    return names


def detect_owner(title: str, profile: dict[str, str]) -> str:
    padded = f" {normalize(title)} "
    for owner, name in _family_names(profile):
        if f" {name} " in padded:
            return owner
    return "ben"


def _parse_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def pdf_issue_date(path: Path, today: date | None = None) -> date | None:
    """PDF metnindeki en yeni (bugünden ileri olmayan) tarih; e-Devlet belgelerinde düzenlenme tarihidir."""
    if path.suffix.lower() != ".pdf":
        return None
    try:
        from pypdf import PdfReader

        reader = PdfReader(path)
        text = " ".join((page.extract_text() or "") for page in reader.pages[:2])
    except Exception as exc:  # bozuk / şifreli PDF
        log.info("PDF okunamadı (%s): %s", path.name, exc)
        return None
    today = today or date.today()
    found = []
    for d, m, y in _DATE.findall(text):
        try:
            found.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    recent = [d for d in found if date(2000, 1, 1) <= d <= today]
    return max(recent) if recent else None


@dataclass
class Document:
    path: str            # vault köküne göre
    filename: str
    title: str
    type: str | None
    owner: str           # ben | baba | anne | kardes
    obtained: date | None
    size: int
    mime: str
    note: str = ""

    @property
    def extension(self) -> str:
        return PurePosixPath(self.filename).suffix.lower()

    @property
    def type_name(self) -> str:
        return DOC_TYPES.get(self.type or "", {}).get("ad", "Belge")

    @property
    def safe_label(self) -> str:
        """LLM'e gösterilebilecek anonim tanım (ad / içerik yok)."""
        owner = "" if self.owner == "ben" else f" ({OWNERS[self.owner].lower()})"
        return f"{self.type_name}{owner}"

    def age_days(self, today: date | None = None) -> int | None:
        return (today or date.today()).toordinal() - self.obtained.toordinal() if self.obtained else None

    def warning(self, today: date | None = None) -> str | None:
        limit = DOC_TYPES.get(self.type or "", {}).get("taze_gun")
        age = self.age_days(today)
        if not limit or age is None or age <= limit:
            return None
        return f"{age} gün önce alınmış; bu belge genelde son {limit} gün içinde istenir. Güncelini almayı düşün."

    def to_dict(self, today: date | None = None) -> dict:
        return {
            "path": self.path, "filename": self.filename, "title": self.title,
            "type": self.type, "type_name": self.type_name,
            "owner": self.owner, "owner_name": OWNERS.get(self.owner, ""),
            "obtained": self.obtained.isoformat() if self.obtained else None,
            "age_days": self.age_days(today), "size": self.size, "mime": self.mime,
            "note": self.note, "warning": self.warning(today),
        }


def _document_files(vault: Vault) -> list[Path]:
    folder = vault.root / DOCS_FOLDER
    if not folder.is_dir():
        return []
    return [f for f in sorted(folder.rglob("*"))
            if f.is_file() and f.suffix.lower() in DOC_EXTENSIONS and not f.name.startswith("_")]


def ensure_document_notes(vault: Vault, profile: dict[str, str]) -> list[str]:
    """Bilgi notu olmayan belgeler için not oluşturur (tür, sahip, PDF'ten okunan tarih)."""
    created = []
    for file in _document_files(vault):
        rel = file.relative_to(vault.root).as_posix()
        note_rel = str(PurePosixPath(rel).with_suffix(".md"))
        if vault.exists(note_rel):
            continue
        obtained = pdf_issue_date(file)
        vault.write(note_rel, {
            "tur": detect_type(file.stem) or "",
            "sahip": detect_owner(file.stem, profile),
            "alinma_tarihi": obtained.isoformat() if obtained else "",
            "aciklama": "",
        }, "<!-- Otomatik oluşturuldu. Tür, sahip (ben/baba/anne/kardes) ya da tarih yanlışsa düzelt. -->")
        created.append(note_rel)
    return created


def list_documents(vault: Vault, profile: dict[str, str] | None = None) -> list[Document]:
    profile = profile or {}
    docs = []
    for file in _document_files(vault):
        rel = file.relative_to(vault.root).as_posix()
        meta_note = vault.read(str(PurePosixPath(rel).with_suffix(".md")))
        meta = meta_note.meta if meta_note else {}
        doc_type = meta.get("tur") if meta.get("tur") in DOC_TYPES else detect_type(file.stem)
        owner = meta.get("sahip") if meta.get("sahip") in OWNERS else detect_owner(file.stem, profile)
        if owner == "kardes" and doc_type == "ogrenci_belgesi":
            doc_type = "kardes_belgesi"
        # Bilgi notu varsa tarih oradan gelir (boşsa bilinmiyor); yoksa dosya tarihi tahmini kullanılır
        obtained = _parse_date(meta.get("alinma_tarihi")) if meta_note else \
            (_parse_date(file.stem[:10]) or date.fromtimestamp(file.stat().st_mtime))
        docs.append(Document(
            path=rel, filename=file.name, title=file.stem, type=doc_type, owner=owner, obtained=obtained,
            size=file.stat().st_size, mime=mimetypes.guess_type(file.name)[0] or "application/octet-stream",
            note=str(meta.get("aciklama") or ""),
        ))
    return docs


def _accepts(accept: str, doc: Document) -> bool:
    """<input accept=".pdf,image/*"> ile uyumluluk."""
    if not accept.strip():
        return True
    for token in (t.strip().lower() for t in accept.split(",")):
        if not token:
            continue
        if token.startswith(".") and doc.extension == token:
            return True
        if token.endswith("/*") and doc.mime.startswith(token[:-1]):
            return True
        if token == doc.mime:
            return True
    return False


def match_document(field_text: str, accept: str, docs: list[Document]) -> Document | None:
    """Alan metninden belge türünü ve kimin belgesi istendiğini bulur; uygun en yeni belgeyi döner.
    Sahip belirtilmemişse yalnızca kişinin kendi belgeleri seçilir (kardeşin belgesi asla yanlışlıkla gitmez)."""
    doc_type = detect_type(field_text)
    if not doc_type:
        return None
    owner = requested_owner(field_text)
    if doc_type == "kardes_belgesi" or (owner == "kardes" and doc_type == "ogrenci_belgesi"):
        doc_type, owner = "kardes_belgesi", "kardes"
    if owner in ("baba", "anne", "kardes"):
        allowed = {owner}
    elif owner == "aile" or doc_type in FAMILY_TYPES:
        allowed = {"ben", "baba", "anne"}
    else:
        allowed = {"ben"}
    candidates = [d for d in docs if d.type == doc_type and d.owner in allowed and _accepts(accept, d)]
    if not candidates:
        return None
    # Kimlik vb.: alan "ön/arka yüz" istiyorsa o yüz; istemiyorsa tek yüzlü değil tam belge tercih edilir
    wanted_side = _side(field_text)
    return max(candidates, key=lambda d: (_side(d.title) == wanted_side, d.obtained or date.min))


def _side(text: str) -> str | None:
    words = normalize(text).split()
    if "arka" in words:
        return "arka"
    if "on" in words and any(w.startswith("yuz") for w in words):
        return "on"
    return None


def resolve_document(vault: Vault, rel: str) -> Document | None:
    """Yalnızca Belgeler klasöründeki izinli dosyalar servis edilir."""
    if not rel.startswith(DOCS_FOLDER + "/"):
        return None
    return next((d for d in list_documents(vault) if d.path == rel), None)
