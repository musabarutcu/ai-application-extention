"""Açık uçlu sorulara, kullanıcının geçmiş cevapları ve profilinden taslak üretir."""

import json
import re

from ...core.llm import LLMProvider
from ...core.profile import is_sensitive, load_background, load_preferences, load_profile
from ...core.text import detect_limits, fit_to_limits, normalize, tokens
from ...core.vault import Note, Vault
from .field_mapper import match_option
from .schemas import AnswerRequest, AnswerResponse

ANSWERS_FOLDER = "Cevaplar"
_DRAFT = re.compile(r"<!-- AI taslağı:\n(.*?)\n-->", re.DOTALL)


def draft_of(note: Note) -> str:
    """Notta saklanan AI taslağı (yoksa boş)."""
    match = _DRAFT.search(note.body)
    return match.group(1).strip() if match else ""


def edit_examples(vault: Vault, category: str, k: int = 2) -> list[tuple[str, str]]:
    """Kullanıcının AI taslaklarını nasıl düzelttiğine dair en yeni örnekler (taslak, son hal).
    Aynı kategoridekiler önce gelir."""
    pairs = []
    for note in vault.list(ANSWERS_FOLDER):
        draft = draft_of(note)
        if draft and note.content and draft != note.content:
            same = note.meta.get("kategori") == category
            pairs.append((same, str(note.meta.get("tarih", "")), draft, note.content))
    pairs.sort(key=lambda p: (p[0], p[1]), reverse=True)
    return [(draft, final) for _, _, draft, final in pairs[:k]]

CATEGORIES: dict[str, list[str]] = {
    "neden-biz": ["neden biz", "neden bu sirket", "why us", "why our", "why this company", "why do you want to work",
                 "sirketimizi", "kurumumuzu", "neden bizimle"],
    "motivasyon": ["neden", "why do you want", "motivasyon", "motivation", "istemenizin sebebi", "ilgilenmenizin",
                   "basvurma sebebi", "why are you applying", "why should we"],
    "kendini-tanit": ["kendinizden", "kendini", "tell us about yourself", "introduce yourself", "about yourself",
                      "kendinizi tanitin", "bize kendinizden"],
    "kariyer-hedefi": ["kariyer", "career", "5 yil", "five years", "future goals", "hedefleriniz", "gelecek"],
    "guclu-zayif": ["guclu yon", "zayif yon", "strength", "weakness"],
    "deneyim-proje": ["deneyim", "experience", "proje", "project", "tecrube", "staj", "internship"],
    "liderlik-takim": ["liderlik", "leadership", "takim", "team", "ekip", "organizasyon"],
    "basari-zorluk": ["zorluk", "challenge", "basari", "achievement", "basarisiz", "failure", "obstacle"],
    "ilgi-alani": ["ilgi alan", "hobi", "interest", "passion", "merak"],
    "teknik": ["llm", "in production", "what would you do", "ne yapardiniz", "nasil cozersiniz", "debug",
               "algorithm", "algoritma", "system design", "how would you"],
}


WRITE_SYSTEM = """Sen kullanıcının kişisel başvuru asistanısın ve onun ağzından (birinci tekil şahıs) başvuru cevapları yazıyorsun.
Kurallar:
- Yalnızca verilen profil, arka plan ve geçmiş cevaplardaki gerçek bilgileri kullan. Deneyim, ödül, sayı, kurum UYDURMA.
- İlgi alanlarını ve gelecek hedeflerini, yapılmış iş ya da kazanılmış yetkinlik gibi sunma (örn. sadece ilgi alanıysa "X organizasyonunda deneyim kazandım" deme).
- Kanıtı olmayan yetkinlik iddialarından kaçın ("güçlü pratik", "uzmanlık", "ileri düzey" vb.); bunun yerine yaptığın somut işi anlat.
- Kurum hakkında sayfada olmayan bilgi uydurma; kurumu tanımıyorsan genel ama samimi konuş.
- Bilgi eksikse dürüst ve genel bir dil kullan; kullanıcının doldurması gereken yeri [köşeli parantez] içinde belirt.
- Sorunun dilinde yaz (soru İngilizceyse İngilizce, Türkçeyse Türkçe).
- Geçmiş cevaplardaki üslubu ve kişiliği koru ama kopyalama; bu soruya ve bu kuruma özel yaz.
- Klişelerden ve abartılı ifadelerden kaçın. Somut ol.
- Uzunluk sınırına kesinlikle uy.
Yalnızca JSON döndür: {"answer": "...", "category": "..."}"""


def guess_category(question: str) -> str:
    text = f" {normalize(question)} "
    best, best_score = "diger", 0
    for category, patterns in CATEGORIES.items():
        score = sum(len(p) for p in patterns if f" {normalize(p)}" in text)
        if score > best_score:
            best, best_score = category, score
    return best


def find_similar(vault: Vault, question: str, category: str, k: int = 3) -> list[Note]:
    """Kategori + kelime örtüşmesiyle en benzer geçmiş cevaplar."""
    q_tokens = set(tokens(question))
    scored = []
    for note in vault.list(ANSWERS_FOLDER):
        if not note.content:
            continue
        soru_tokens = set(tokens(str(note.meta.get("soru", ""))))
        body_tokens = set(tokens(note.content))
        score = 2.0 * len(q_tokens & soru_tokens) + 0.3 * len(q_tokens & body_tokens)
        if note.meta.get("kategori") == category and category != "diger":
            score += 4
        scored.append((score, str(note.meta.get("tarih", "")), note))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [note for _, _, note in scored[:k]]


def _length_instruction(req: AnswerRequest, max_chars: int | None, max_words: int | None) -> str:
    if req.options:
        multi = "Birden fazla seçilebilir; seçtiklerini \"; \" ile ayır." if req.field_type == "checkbox" else "Tek bir seçenek seç."
        return ("Bu bir seçmeli soru. answer alanına YALNIZCA şu seçeneklerden birini aynen yaz: "
                + " | ".join(req.options) + f". {multi} "
                "Kullanıcının bilgilerinden çıkarılamıyorsa (örn. 'bizi nereden duydunuz') answer boş string olsun.")
    parts = []
    if max_words:
        parts.append(f"en fazla {max_words} kelime")
    if max_chars:
        parts.append(f"en fazla {max_chars} karakter (boşluklar dahil)")
    if parts:
        return "Sınır: " + ", ".join(parts) + ". Sınırın %80-95'i civarını hedefle."
    if req.field_type != "textarea":
        return "Kısa bir alan: 1-2 cümle."
    return "Belirtilmiş sınır yok: 120-220 kelime arası yaz."


def write_answer(vault: Vault, llm: LLMProvider, req: AnswerRequest) -> AnswerResponse:
    question = req.question.strip()
    full_question = f"{question}\n{req.description.strip()}".strip()
    category = guess_category(full_question)
    detected_chars, detected_words = detect_limits(full_question)
    max_chars = req.max_chars or detected_chars
    max_words = req.max_words or detected_words

    similar = find_similar(vault, full_question, category)
    profile = {k: v for k, v in load_profile(vault).items() if not is_sensitive(k)}

    sections = [
        "## Başvuru bağlamı",
        f"Kurum: {req.context.kurum or '-'}\nPozisyon/Program: {req.context.pozisyon or '-'}\n"
        f"Tür: {req.context.tip or '-'}\nURL: {req.url or '-'}",
    ]
    if req.page_text:
        sections += ["Sayfadaki ilan/açıklama metni (kısaltılmış):", req.page_text[:2500]]
    sections += ["## Soru", full_question, "## Uzunluk", _length_instruction(req, max_chars, max_words)]
    if prefs := load_preferences(vault):
        sections += ["## Kullanıcının yazım tercihleri", prefs]
    sections += ["## Profil", json.dumps(profile, ensure_ascii=False, indent=1)]
    if background := load_background(vault):
        sections += ["## Arka plan (kullanıcının kendi notları)", background]
    if similar:
        sections.append("## Kullanıcının daha önce yazdığı benzer cevaplar (üslup ve içerik referansı)")
        for note in similar:
            sections.append(f"### Soru: {note.meta.get('soru', note.title)}\n{note.content}")
    if examples := edit_examples(vault, category):
        sections.append("## Kullanıcının AI taslaklarını nasıl düzelttiği "
                        "(bu farkları öğren: kelime seçimi, ton, uzunluk, neyi çıkarıp neyi eklediği; baştan böyle yaz)")
        for draft, final in examples:
            sections.append(f"### AI taslağı\n{draft[:800]}\n### Kullanıcının son hali\n{final[:800]}")
    if req.previous:
        sections += ["## Önceki taslak", req.previous]
    if req.hint:
        sections += ["## Kullanıcının bu cevap için yönlendirmesi (öncelikli uy)", req.hint]

    result = llm.generate_json("\n\n".join(sections), system=WRITE_SYSTEM, temperature=0.7)
    if not isinstance(result, dict):
        result = {}
    answer = str(result.get("answer", "")).strip()
    if req.options:
        parts = [p.strip() for p in answer.split(";") if p.strip()]
        picked = [match_option(p, req.options) or (p if req.field_type == "combobox" else None) for p in parts]
        answer = "; ".join(dict.fromkeys(p for p in picked if p))
    else:
        answer = fit_to_limits(answer, max_chars, max_words)
    return AnswerResponse(
        answer=answer,
        category=category if category != "diger" else str(result.get("category") or category),
        used_answers=[note.title for note in similar],
    )
