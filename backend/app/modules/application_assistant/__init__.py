from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from ...core.documents import MAX_UPLOAD_BYTES, ensure_document_notes, list_documents, resolve_document
from ...core.llm import LLMError
from ...core.module import BaseModule, register
from ...core.profile import load_profile
from .answer_writer import write_answer
from .field_mapper import analyze_form
from .field_memory import learn, load_field_memory
from .schemas import (AnalyzeRequest, AnalyzeResponse, AnswerRequest, AnswerResponse, LearnRequest,
                      MemoryRequest, MemoryResponse, SaveRequest, SaveResponse)
from .tracker import list_applications, save_answers, save_application


@register
class ApplicationAssistant(BaseModule):
    name = "application"
    description = "Başvuru formlarını analiz eder, profil alanlarını doldurur, açık uçlu sorulara taslak yazar."

    def router(self) -> APIRouter:
        ctx = self.ctx
        router = APIRouter(tags=["application"])

        def documents_with_notes(profile):
            ensure_document_notes(ctx.vault, profile)  # yeni eklenen belgeler için bilgi notu
            return list_documents(ctx.vault, profile)

        @router.post("/analyze", response_model=AnalyzeResponse)
        def analyze(req: AnalyzeRequest):
            profile = load_profile(ctx.vault)
            return analyze_form(req, profile, ctx.llm, documents_with_notes(profile), load_field_memory(ctx.vault))

        @router.post("/learn")
        def learn_fields(req: LearnRequest):
            """Yan paneldeki düzeltmeleri alan hafızasına yazar."""
            return {"learned": learn(ctx.vault, req.items, load_profile(ctx.vault))}

        @router.post("/answer", response_model=AnswerResponse)
        def answer(req: AnswerRequest):
            llm = ctx.require_llm()
            try:
                return write_answer(ctx.vault, llm, req)
            except LLMError as exc:
                raise HTTPException(502, str(exc)) from exc

        @router.post("/applications", response_model=SaveResponse)
        def save(req: SaveRequest):
            return save_application(ctx.vault, req)

        @router.post("/memory", response_model=MemoryResponse)
        def memory(req: MemoryRequest):
            """Cevapların son hallerini hafızaya (vault/Cevaplar) yazar; başvuru notu oluşturmaz."""
            return save_answers(ctx.vault, req.context, req.items)

        @router.get("/documents")
        def documents():
            return {"documents": [d.to_dict() for d in documents_with_notes(load_profile(ctx.vault))]}

        @router.get("/documents/file")
        def document_file(path: str = Query(...)):
            doc = resolve_document(ctx.vault, path)
            if doc is None:
                raise HTTPException(404, "Belge bulunamadı")
            if doc.size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "Belge çok büyük (25 MB üstü)")
            return FileResponse(ctx.vault.root / doc.path, media_type=doc.mime, filename=doc.filename)

        @router.get("/applications")
        def applications():
            return {"applications": list_applications(ctx.vault)}

        return router
