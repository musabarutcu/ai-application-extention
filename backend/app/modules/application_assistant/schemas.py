from typing import Literal

from pydantic import BaseModel, Field

FieldKind = Literal["profile", "answer", "document", "skip"]


class FormField(BaseModel):
    id: str
    label: str = ""
    description: str = ""
    type: str = "text"
    name: str = ""
    placeholder: str = ""
    options: list[str] = Field(default_factory=list)
    max_length: int | None = None
    required: bool = False
    accept: str = ""        # dosya alanları: <input accept="...">
    multiple: bool = False


class AppContext(BaseModel):
    kurum: str = ""
    pozisyon: str = ""
    tip: str = ""


class AnalyzeRequest(BaseModel):
    url: str = ""
    title: str = ""
    page_text: str = ""
    fields: list[FormField]


class Suggestion(BaseModel):
    id: str
    kind: FieldKind
    value: str = ""
    profile_key: str | None = None
    source: Literal["rule", "llm", "heuristic", "memory"] = "heuristic"
    max_chars: int | None = None
    max_words: int | None = None
    document: dict | None = None   # kind="document": eşleşen belgenin bilgileri (value = belge yolu)


class AnalyzeResponse(BaseModel):
    suggestions: list[Suggestion]
    context: AppContext
    llm_used: bool
    warnings: list[str] = Field(default_factory=list)
    documents: list[dict] = Field(default_factory=list)  # yan paneldeki belge seçimi için tüm belgeler


class LearnItem(BaseModel):
    """Kullanıcının yan paneldeki düzeltmesi: bu etiket için tür / profil alanı / değer."""
    label: str
    type: str = "text"
    kind: FieldKind
    profile_key: str = ""
    value: str = ""


class LearnRequest(BaseModel):
    items: list[LearnItem]


class AnswerRequest(BaseModel):
    question: str
    description: str = ""
    field_type: str = "textarea"
    options: list[str] = Field(default_factory=list)
    context: AppContext = Field(default_factory=AppContext)
    url: str = ""
    page_text: str = ""
    max_chars: int | None = None
    max_words: int | None = None
    hint: str = ""
    previous: str = ""


class AnswerResponse(BaseModel):
    answer: str
    category: str
    used_answers: list[str]


class QAItem(BaseModel):
    question: str
    answer: str            # son hal (kullanıcının sayfada düzenlediği metin)
    draft: str = ""        # AI'ın ilk taslağı (düzeltmelerden öğrenmek için)
    category: str = ""
    save_to_memory: bool = False


class MemoryRequest(BaseModel):
    context: AppContext
    items: list[QAItem]


class MemoryResponse(BaseModel):
    saved_answers: list[str]


class SaveRequest(BaseModel):
    context: AppContext
    url: str = ""
    status: str = "gönderildi"
    items: list[QAItem] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)  # yüklenen belgelerin başlıkları
    notes: str = ""


class SaveResponse(BaseModel):
    application_note: str
    saved_answers: list[str]
