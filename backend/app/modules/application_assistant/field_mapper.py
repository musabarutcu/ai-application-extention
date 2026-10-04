"""Form alanlarını profil anahtarlarıyla eşler: önce kurallar, sonra (varsa) LLM."""

import json
import logging
import re

from ...core.llm import LLMError, LLMProvider
from ...core.documents import Document, match_document
from ...core.profile import is_sensitive, masked_profile
from ...core.text import detect_language, detect_limits, normalize
from .field_memory import Learned, lookup
from .schemas import AnalyzeRequest, AnalyzeResponse, AppContext, FormField, Suggestion

log = logging.getLogger(__name__)

# Sıra önemli: daha özel anahtarlar önce (ad_soyad > soyad > ad, eposta > adres).
FIELD_PATTERNS: dict[str, list[str]] = {
    "baba_ad_soyad": ["baba adı soyadı", "baba ad soyad", "babanın adı soyadı", "babanızın adı soyadı",
                      "father's full name", "father full name"],
    "anne_ad_soyad": ["anne adı soyadı", "anne ad soyad", "annenin adı soyadı", "annenizin adı soyadı",
                      "mother's full name", "mother full name"],
    "baba_adi": ["baba adı", "babanızın adı", "babanın adı", "baba ismi", "father's name", "father name"],
    "anne_adi": ["anne adı", "annenizin adı", "annenin adı", "anne ismi", "mother's name", "mother name"],
    "kardes_sayisi": ["kardeş sayısı", "kardeş sayınız", "kardeş sayın", "kaç kardeşsiniz", "kaç kardeşsin",
                      "number of siblings"],
    "kardesler": ["kardeşleriniz", "kardeşlerin", "kardeş bilgileri", "kardeşlerinizin adları", "siblings"],
    "baba_meslek": ["baba mesleği", "babanızın mesleği", "babanın mesleği", "baba meslek", "father's occupation"],
    "anne_meslek": ["anne mesleği", "annenizin mesleği", "annenin mesleği", "anne meslek", "mother's occupation"],
    "baba_calisma_durumu": ["baba çalışma durumu", "babanızın çalışma durumu", "babanın çalışma durumu",
                            "babanız çalışıyor mu", "baba çalışıyor mu"],
    "anne_calisma_durumu": ["anne çalışma durumu", "annenizin çalışma durumu", "annenin çalışma durumu",
                            "anneniz çalışıyor mu", "anne çalışıyor mu"],
    "baba_hayatta": ["baba sağ mı", "babanız sağ mı", "babanız hayatta mı", "baba hayatta mı", "baba sağ vefat",
                     "babanızın durumu"],
    "anne_hayatta": ["anne sağ mı", "anneniz sağ mı", "anneniz hayatta mı", "anne hayatta mı", "anne sağ vefat",
                     "annenizin durumu"],
    "anne_baba_birlikte": ["anne baba birlikte mi", "anne babanız birlikte mi", "anne ve babanız birlikte mi",
                           "anne baba durumu", "ebeveyn durumu", "anne ve babanızın durumu", "anne babanın durumu"],
    "kardes_ogrenim_durumu": ["kardeş öğrenim durumu", "kardeşlerinizin öğrenim durumu", "kardeşlerin öğrenim durumu",
                              "kardeşlerinizin eğitim durumu"],
    "okuyan_kardes_sayisi": ["okuyan kardeş sayısı", "okuyan kardeş sayınız", "öğrenim gören kardeş sayısı",
                             "okuyan kardeşiniz var mı"],
    "hane_kisi_sayisi": ["hane halkı sayısı", "hanedeki kişi sayısı", "hane kişi sayısı", "evde yaşayan kişi sayısı",
                         "aile birey sayısı", "aile fert sayısı", "household size"],
    "kisi_basi_gelir": ["kişi başı gelir", "kişi başına düşen gelir", "kişi başı aylık gelir",
                        "kişi başına düşen aylık gelir"],
    "aile_aylik_gelir": ["ailenin aylık geliri", "aile aylık geliri", "ailenizin aylık geliri", "aylık aile geliri",
                         "ailenizin toplam aylık geliri", "toplam aylık gelir", "hane geliri", "aile geliri",
                         "household income"],
    "aile_ikamet_ili": ["ailenin ikamet ettiği il", "ailenizin ikamet ettiği il", "ailenizin yaşadığı il",
                        "aile ikamet ili", "ailenizin yaşadığı şehir", "ailenin yaşadığı il"],
    "ev_durumu": ["ev durumu", "konut durumu", "oturduğunuz ev", "oturduğunuz evin durumu", "ikamet edilen konut",
                  "ailenizin oturduğu ev", "ev kira mı"],
    "kira_tutari": ["kira tutarı", "aylık kira", "kira bedeli", "ödenen kira", "aylık kira tutarı"],
    "aile_arac": ["araç durumu", "ailenizin aracı var mı", "aracınız var mı", "ailenize ait araç", "araç sahipliği"],
    "aile_tasinmaz": ["taşınmaz durumu", "ailenize ait taşınmaz", "gayrimenkul", "mülk durumu",
                      "ailenize ait ev arsa"],
    "kendi_gelirim": ["kendi geliriniz", "kişisel geliriniz", "sizin aylık geliriniz", "aylık geliriniz"],
    "calisiyor_musun": ["çalışıyor musunuz", "çalışıyor musun", "bir işte çalışıyor musunuz", "çalışma durumunuz"],
    "baska_burs": ["başka burs", "başka bir burs", "burs alıyor musunuz", "başka bir kurumdan burs",
                   "aldığınız burs", "diğer burslar", "kyk"],
    "engel_durumu": ["engel durumu", "engel durumunuz", "engellilik durumu", "engelli misiniz", "disability"],
    "sehit_gazi_yakini": ["şehit gazi yakını", "şehit veya gazi yakını", "şehit yakını", "gazi yakını",
                          "şehit gazi yakını mısınız"],
    "tc_kimlik_no": ["tc kimlik no", "tc kimlik numarası", "tc kimlik numaranız", "tc kimlik numaran", "t.c. kimlik numaran", "t.c. kimlik no",
                     "t.c. kimlik numarası", "t.c. kimlik numaranız", "t.c. kimlik", "kimlik numaranız", "tc no", "tckn", "tc kimlik", "kimlik numarası", "kimlik no",
                     "national id", "national id number", "turkish id number", "identity number"],
    "pasaport_gecerlilik": ["pasaport geçerlilik tarihi", "pasaport son geçerlilik tarihi",
                            "passport expiry date", "passport expiration date",
                            "passport expiry", "pasaport geçerlilik"],
    "pasaport_no": ["pasaport no", "pasaport numarası", "pasaport numaranız", "passport number",
                    "passport no", "passport"],
    "iban": ["iban", "iban no", "iban numarası", "iban numaranız", "iban number"],
    "banka": ["banka", "banka adı", "bank", "bank name"],
    "yas": ["yaş", "yaşınız", "age", "your age"],
    "dogum_yeri": ["doğum yeri", "doğum yeriniz", "place of birth", "birthplace"],
    "eposta": ["e-posta", "eposta", "e-mail", "email", "mail", "e-posta adresi", "e-posta adresin", "mail adresin", "email address"],
    "telefon": ["telefon", "telefon numarası", "telefon numaran", "telefonun", "cep telefonu", "gsm", "phone", "phone number", "mobile", "tel"],
    "ad_soyad": ["ad soyad", "adı soyadı", "adınız soyadınız", "adın soyadın", "ad soyadın", "isim soyisim", "isim soyad",
                 "full name", "name surname", "name", "your name", "ad-soyad"],
    "soyad": ["soyad", "soyadı", "soyadınız", "soyadın", "soyisim", "soyisminiz", "last name", "surname", "family name"],
    "ad": ["ad", "adı", "adınız", "adın", "isim", "isminiz", "first name", "given name"],
    "dogum_tarihi": ["doğum tarihi", "doğum tarihiniz", "doğum tarihin", "date of birth", "birth date", "birthday"],
    "cinsiyet": ["cinsiyet", "cinsiyetiniz", "gender"],
    "uyruk": ["uyruk", "uyruğunuz", "nationality", "citizenship"],
    "sehir": ["şehir", "il", "yaşadığınız şehir", "ikamet ettiğiniz il", "yaşadığınız il", "yaşadığın il",
              "yaşadığın şehir", "ikamet ettiğin il", "bulunduğun il", "bulunduğun şehir", "city"],
    "ulke": ["ülke", "country"],
    "adres": ["adres", "adresiniz", "ikamet adresi", "address"],
    "universite": ["üniversite", "üniversiteniz", "üniversiten", "okuduğunuz üniversite", "okuduğun üniversite", "okul", "university", "school"],
    "fakulte": ["fakülte", "fakülteniz", "faculty"],
    "bolum": ["bölüm", "bölümünüz", "bölümün", "okuduğunuz bölüm", "okuduğun bölüm", "üniversite bölümü",
              "lisans bölümün", "öğrenim gördüğün bölüm", "öğrenim gördüğün lisans bölümün",
              "öğrenim gördüğünüz bölüm", "university department",
              "department", "major", "field of study"],
    "akademik_seviye": ["akademik seviye", "öğrenim seviyesi", "eğitim seviyesi", "eğitim durumu",
                        "academic level", "education level", "degree level", "level of study"],
    "sinif": ["sınıf", "sınıfınız", "sınıfın", "kaçıncı sınıf", "kaçıncı sınıftasın", "year of study", "class", "grade", "current year"],
    "mezuniyet_yili": ["mezuniyet yılı", "tahmini mezuniyet", "beklenen mezuniyet", "graduation year",
                       "expected graduation", "expected graduation date"],
    "gano": ["gano", "agno", "not ortalaması", "not ortalaman", "genel not ortalaması", "gpa", "cgpa"],
    "ingilizce_seviyesi": ["ingilizce seviyesi", "ingilizce seviyeniz", "english level", "english proficiency"],
    "linkedin": ["linkedin", "linkedin profili", "linkedin profil linkin", "linkedin profilin", "linkedin url", "linkedin profile"],
    "github": ["github", "github profili", "github url"],
    "medium": ["medium", "medium profili", "medium profile", "blog"],
    "instagram_kullanici_adi": ["instagram kullanıcı adı", "instagram kullanıcı adın", "instagram kullanıcı adınız",
                                "instagram handle", "instagram username"],
    "instagram": ["instagram", "instagram hesabı", "instagram hesabın", "instagram hesabınız", "instagram profili",
                  "instagram profilin", "instagram adresi", "instagram linki", "instagram profile"],
    "portfolyo": ["portfolyo", "portfolio", "kişisel web sitesi", "web sitesi", "website", "personal website"],
}
_NORMALIZED = {key: [normalize(p) for p in patterns] for key, patterns in FIELD_PATTERNS.items()}
_SKIP_TYPES = {"password"}
_MAX_LABEL_WORDS_FOR_CONTAINS = 6


_NUMBERING = re.compile(r"^\s*\d{1,3}\s*[-.)]\s*")


def _clean_label(label: str) -> str:
    label = _NUMBERING.sub("", label)  # "6- Yaşadığın İl" -> "Yaşadığın İl"
    return normalize(label.split("(")[0] if len(label) > 40 else label)


def rule_match(field: FormField) -> str | None:
    """Alanın profil anahtarını kurallarla bulur."""
    if field.type == "email":
        return "eposta"
    if field.type == "tel":
        return "telefon"
    label = _clean_label(field.label)
    candidates = [c for c in (label, normalize(field.name), normalize(field.placeholder)) if c]
    for key, patterns in _NORMALIZED.items():
        if any(c == p for c in candidates for p in patterns):
            return key
    # Kısa etiketlerde ayırt edici kalıp geçiyorsa ("Okuduğunuz bölüm adı", "Email address")
    if label and len(label.split()) <= _MAX_LABEL_WORDS_FOR_CONTAINS:
        padded = f" {label} "
        for key, patterns in _NORMALIZED.items():
            for p in patterns:
                if (len(p) >= 5 or " " in p) and f" {p} " in padded:
                    return key
    return None


def fit_to_options(value: str, field: FormField) -> str:
    """Değeri alanın seçeneklerine uydurur. Özel açılır kutularda (combobox) liste eksik
    okunmuş olabilir; eşleşme yoksa ham değer korunur, eklenti doldururken arayarak bulur."""
    if not field.options or not value:
        return value
    parts = [p.strip() for p in value.split(";") if p.strip()] if field.type == "checkbox" else [value]
    matched = [match_option(p, field.options) for p in parts]
    if field.type == "combobox":
        return "; ".join(m or p for m, p in zip(matched, parts))
    return "; ".join(m for m in matched if m)


def profile_value(profile: dict[str, str], key: str, english: bool) -> str:
    """İngilizce formlarda varsa `<anahtar>_en` değerini tercih eder."""
    if english and profile.get(f"{key}_en"):
        return profile[f"{key}_en"]
    return profile.get(key, "")


def match_option(value: str, options: list[str]) -> str | None:
    target = normalize(value)
    if not target:
        return None
    normalized = [normalize(o) for o in options]
    for opt, norm in zip(options, normalized):
        if norm == target:
            return opt
    for opt, norm in zip(options, normalized):
        if norm and (norm in target or target in norm):
            return opt
    return None


def looks_open_ended(field: FormField) -> bool:
    if field.type == "textarea":
        return True
    if field.type not in {"text", ""} or field.options:
        return False
    return field.label.strip().endswith("?") or len(field.label.split()) >= 8


def _limits(field: FormField) -> tuple[int | None, int | None]:
    chars, words = detect_limits(f"{field.label} {field.description}")
    return (field.max_length or chars, words)


MAP_SYSTEM = (
    "Sen bir başvuru formu analiz asistanısın. Form alanlarını kullanıcının profiliyle eşleştirir, "
    "başvurunun bağlamını çıkarırsın. Yalnızca geçerli JSON döndür."
)

MAP_PROMPT = """## Sayfa
URL: {url}
Başlık: {title}
Sayfa metni (kısaltılmış):
{page_text}

## Kullanıcı profili (anahtar: değer)
{profile}

## Eşlenecek alanlar
{fields}

## Kullanıcının belgeleri (kod: tür (sahip); dosya alanları için)
{documents}

## Kurallar
- Değeri "<gizli...>" olan anahtarlar hassastır: değerini bilmene gerek yok, sadece doğru profile_key'i seç ve value'yu boş bırak.
- kind="profile": alan profildeki bir bilgiyle doldurulabiliyorsa. profile_key profildeki anahtarlardan biri olmalı. value bu değerden türetilmeli (formatı alana uydurabilirsin, örn. tarih biçimi). Profilde yoksa UYDURMA, value boş kalsın.
- Form İngilizceyse ve profilde "<anahtar>_en" varsa onu kullan (örn. bolum_en); yoksa değeri İngilizceye çevir.
- Seçenekli alanlarda (options dolu) value seçeneklerden biriyle birebir aynı olmalı. Birden fazla seçim gerekiyorsa "; " ile ayır.
- type="combobox" açılır kutudur; seçenek listesi eksik olabilir. Profildeki değer listede yoksa bile profil değerini yaz (örn. il, üniversite).
- kind="answer": kullanıcının kendi cümleleriyle yazması gereken açık uçlu soru (motivasyon, deneyim, "neden", "anlatınız", "bizi nereden duydunuz" vb.). value boş kalsın.
- type="file" (dosya yükleme) alanları: uygun belge varsa kind="document" ve "document" alanına belgenin kodunu (örn. "D3") yaz; yoksa kind="skip". Sahip belirtilmemişse kullanıcının kendi belgesini seç; kardeş/anne/baba belgesini yalnızca soru açıkça onu istiyorsa seç.
- kind="skip": onay kutuları (KVKK, şartları kabul), dosya yükleme, profilden çıkarılamayan ve tahmin edilmemesi gereken alanlar.
- Ayrıca başvurunun yapıldığı kurumu, pozisyonu/programı ve türünü (iş, staj, burs, elçilik, yarışma, eğitim, diğer) sayfadan tahmin et. Bilinmiyorsa boş bırak.

## Çıktı
{{"context": {{"kurum": "", "pozisyon": "", "tip": ""}}, "fields": [{{"id": "", "kind": "profile|answer|document|skip", "profile_key": null, "value": "", "document": null}}]}}"""


def _llm_map(llm: LLMProvider, req: AnalyzeRequest, fields: list[FormField], profile: dict[str, str],
             docs: list[Document]) -> dict:
    payload = [
        {k: v for k, v in f.model_dump().items() if v not in ("", [], None, False) and k != "max_length"}
        for f in fields
    ]
    prompt = MAP_PROMPT.format(
        url=req.url,
        title=req.title,
        page_text=req.page_text[:2500],
        profile=json.dumps(masked_profile(profile), ensure_ascii=False, indent=1),
        fields=json.dumps(payload, ensure_ascii=False, indent=1),
        documents="\n".join(f"- D{i}: {d.safe_label}" for i, d in enumerate(docs, 1)) or "(belge yok)",
    )
    result = llm.generate_json(prompt, system=MAP_SYSTEM)
    return result if isinstance(result, dict) else {}


def _apply_learned(learned: Learned, field: FormField, profile: dict[str, str], english: bool,
                   docs: list[Document]) -> Suggestion | None:
    """Alan hafızasındaki düzeltmeyi uygular. Uygulanamıyorsa (profil alanı silinmiş, belge yok) None."""
    max_chars, max_words = _limits(field)
    base = {"id": field.id, "source": "memory"}
    if learned.kind in ("skip", "answer"):
        return Suggestion(kind=learned.kind, max_chars=max_chars, max_words=max_words, **base)
    if learned.kind == "document":
        doc = next((d for d in docs if d.path == learned.value), None)
        return Suggestion(kind="document", value=doc.path, document=doc.to_dict(), **base) if doc else None
    if learned.profile_key:
        value = profile_value(profile, learned.profile_key, english)
        if not value:
            return None
        return Suggestion(kind="profile", profile_key=learned.profile_key, value=fit_to_options(value, field), **base)
    if learned.value:
        return Suggestion(kind="profile", value=fit_to_options(learned.value, field), **base)
    return None


def analyze_form(req: AnalyzeRequest, profile: dict[str, str], llm: LLMProvider | None,
                 docs: list[Document] | None = None, memory: dict[str, Learned] | None = None) -> AnalyzeResponse:
    docs = docs or []
    memory = memory or {}
    docs_by_code = {f"D{i}": d for i, d in enumerate(docs, 1)}
    by_id: dict[str, Suggestion] = {}
    unresolved: list[FormField] = []
    warnings: list[str] = []

    english = detect_language(" ".join(f.label for f in req.fields) + " " + req.title) == "en"

    for field in req.fields:
        max_chars, max_words = _limits(field)
        if field.type in _SKIP_TYPES:
            by_id[field.id] = Suggestion(id=field.id, kind="skip")
            continue
        learned = lookup(memory, field)
        if learned and (suggestion := _apply_learned(learned, field, profile, english, docs)):
            by_id[field.id] = suggestion  # kullanıcının önceki düzeltmesi: kurallar ve LLM'e gitmez
            continue
        if field.type == "file":
            text = f"{_NUMBERING.sub('', field.label)} {field.description} {field.name}"
            doc = match_document(text, field.accept, docs)
            if doc:
                by_id[field.id] = Suggestion(id=field.id, kind="document", value=doc.path, source="rule",
                                             document=doc.to_dict())
            else:
                unresolved.append(field)
                by_id[field.id] = Suggestion(id=field.id, kind="skip")
            continue
        key = rule_match(field)
        if key:
            value = profile_value(profile, key, english)
            value = fit_to_options(value, field)
            if value or not field.options:
                by_id[field.id] = Suggestion(id=field.id, kind="profile", profile_key=key, value=value, source="rule")
                continue
        unresolved.append(field)
        # LLM yoksa ya da başarısız olursa geçerli olacak varsayılan
        kind = "answer" if looks_open_ended(field) else "skip"
        by_id[field.id] = Suggestion(id=field.id, kind=kind, max_chars=max_chars, max_words=max_words)

    context = AppContext()
    llm_used = False
    if llm is not None:
        try:
            result = _llm_map(llm, req, unresolved, profile, docs)
            llm_used = True
            ctx = result.get("context") or {}
            context = AppContext(**{k: str(ctx.get(k) or "") for k in ("kurum", "pozisyon", "tip")})
            fields_by_id = {f.id: f for f in unresolved}
            for item in result.get("fields") or []:
                field = fields_by_id.get(str(item.get("id")))
                if not field or item.get("kind") not in ("profile", "answer", "document", "skip"):
                    continue
                suggestion = by_id[field.id]
                if item["kind"] == "document" or field.type == "file":
                    # LLM yalnızca belge adını seçer; geçersiz ad ya da dosya olmayan alan yok sayılır
                    doc = docs_by_code.get(str(item.get("document") or "").strip().upper())
                    if field.type == "file" and doc:
                        suggestion.kind, suggestion.value, suggestion.source = "document", doc.path, "llm"
                        suggestion.document = doc.to_dict()
                    continue
                suggestion.kind = item["kind"]
                suggestion.source = "llm"
                if item["kind"] == "profile":
                    key = item.get("profile_key")
                    suggestion.profile_key = key if key in profile else None
                    value = str(item.get("value") or "")
                    if key and is_sensitive(key):
                        # LLM hassas değeri hiç görmedi; gerçek değer yerelden gelir
                        value = profile.get(key, "")
                    suggestion.value = fit_to_options(value, field)
        except LLMError as exc:
            log.warning("LLM eşleme hatası: %s", exc)
            warnings.append(f"Yapay zekâ eşlemesi başarısız, sadece kurallar kullanıldı: {exc}")
    else:
        warnings.append("LLM yapılandırılmamış; sadece kural tabanlı eşleme yapıldı.")

    suggestions = [by_id[f.id] for f in req.fields]
    return AnalyzeResponse(suggestions=suggestions, context=context, llm_used=llm_used, warnings=warnings,
                           documents=[d.to_dict() for d in docs])
