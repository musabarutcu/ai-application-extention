"""Yapılan başvuruları ve cevapların son hallerini vault'a kaydeder (agent'ın hafızası büyür).

Cevaplar kurum + soru başına tek nottur: aynı cevap tekrar kaydedilirse yeni not açılmaz, mevcut
not güncellenir. AI'ın ilk taslağı notun içinde yorum olarak saklanır; asistan sonraki taslaklarda
kullanıcının taslakları nasıl düzelttiğini buradan öğrenir.
"""

from datetime import date
from difflib import SequenceMatcher

from ...core.text import detect_language
from ...core.vault import Note, Vault, safe_filename
from .answer_writer import ANSWERS_FOLDER, draft_of, guess_category
from .schemas import AppContext, MemoryResponse, QAItem, SaveRequest, SaveResponse

APPLICATIONS_FOLDER = "Başvurular"


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0]


def _change_ratio(draft: str, final: str) -> float:
    return round(1 - SequenceMatcher(None, draft, final).ratio(), 2)


def _answer_path(vault: Vault, kurum: str, question: str) -> str:
    """Kurum + soru için sabit not yolu; aynı soruya ait eski not varsa onu döner."""
    stem = safe_filename(f"{kurum} - {_short(question, 50)}")
    rel = f"{ANSWERS_FOLDER}/{stem}.md"
    existing = vault.read(rel)
    if existing is None or str(existing.meta.get("soru", "")).strip() == question.strip():
        return rel
    return vault.unique_path(ANSWERS_FOLDER, stem)  # aynı ada denk gelen farklı soru


def save_answer(vault: Vault, ctx: AppContext, item: QAItem, today: str | None = None) -> Note:
    """Cevabın son halini hafızaya yazar (varsa günceller)."""
    today = today or date.today().isoformat()
    kurum = ctx.kurum.strip() or "Bilinmeyen Kurum"
    final = item.answer.strip()
    draft = item.draft.strip()
    rel = _answer_path(vault, kurum, item.question)
    previous = vault.read(rel)
    draft = draft or (draft_of(previous) if previous else "")

    meta = {
        "soru": item.question.strip(),
        "kategori": item.category or guess_category(item.question),
        "kurum": ctx.kurum,
        "tip": ctx.tip,
        "tarih": today,
        "dil": detect_language(final),
        "kelime_sayisi": len(final.split()),
    }
    body = final
    if draft and draft != final:
        meta["kaynak"] = "ai-taslak + kullanıcı düzenlemesi"
        meta["degisim_orani"] = _change_ratio(draft, final)
        body += "\n\n<!-- AI taslağı:\n" + draft.replace("-->", "-- >") + "\n-->"
    else:
        meta["kaynak"] = "ai-taslak" if draft else "kullanıcı"
    return vault.write(rel, meta, body)


def save_answers(vault: Vault, ctx: AppContext, items: list[QAItem]) -> MemoryResponse:
    saved = [save_answer(vault, ctx, item).title for item in items if item.answer.strip()]
    return MemoryResponse(saved_answers=saved)


def save_application(vault: Vault, req: SaveRequest) -> SaveResponse:
    today = date.today().isoformat()
    ctx = req.context
    kurum = ctx.kurum.strip() or "Bilinmeyen Kurum"

    saved: list[str] = []
    links: dict[int, str] = {}
    for index, item in enumerate(req.items):
        if item.save_to_memory and item.answer.strip():
            note = save_answer(vault, ctx, item, today)
            saved.append(note.title)
            links[index] = note.title

    title = " - ".join(p for p in (kurum, ctx.pozisyon.strip()) if p)
    # Aynı gün aynı başvuru tekrar kaydedilirse not güncellenir (kopya açılmaz)
    rel = f"{APPLICATIONS_FOLDER}/{safe_filename(f'{today} {title}')}.md"
    body = [f"# {title}", ""]
    if req.notes.strip():
        body += ["## Notlar", req.notes.strip(), ""]
    if req.documents:
        body += ["## Yüklenen belgeler", *[f"- {doc_title}" for doc_title in req.documents], ""]
    if req.items:
        body += ["## Sorular ve Cevaplar", ""]
        for index, item in enumerate(req.items):
            body += [f"### {item.question.strip()}", item.answer.strip()]
            if index in links:
                body.append(f"\n→ [[{links[index]}]]")
            body.append("")
    note = vault.write(
        rel,
        {
            "kurum": ctx.kurum,
            "pozisyon": ctx.pozisyon,
            "tip": ctx.tip,
            "durum": req.status,
            "tarih": today,
            "url": req.url,
        },
        "\n".join(body).strip(),
    )
    return SaveResponse(application_note=note.title, saved_answers=saved)


def list_applications(vault: Vault, limit: int = 50) -> list[dict]:
    notes = sorted(vault.list(APPLICATIONS_FOLDER), key=lambda n: n.title, reverse=True)[:limit]
    return [{"title": n.title, **{k: str(v) for k, v in n.meta.items()}} for n in notes]
