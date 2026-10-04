import json

from app.modules.application_assistant.answer_writer import draft_of

from .conftest import FakeLLM, make_client

CTX = {"kurum": "TOG", "pozisyon": "Burs", "tip": "burs"}
Q = "Neden bu bursa başvuruyorsunuz?"


def test_memory_saves_final_with_hidden_draft(vault):
    client = make_client(vault)
    res = client.post("/modules/application/memory", json={"context": CTX, "items": [
        {"question": Q, "answer": "Benim son halim, kısa ve net.", "draft": "AI'ın uzun ve süslü taslağı burada."},
    ]}).json()
    assert res["saved_answers"] == ["TOG - Neden bu bursa başvuruyorsunuz"]
    note = vault.read("Cevaplar/TOG - Neden bu bursa başvuruyorsunuz.md")
    assert note.content == "Benim son halim, kısa ve net."        # asistanın gördüğü: yalnızca son hal
    assert draft_of(note) == "AI'ın uzun ve süslü taslağı burada."
    assert note.meta["kaynak"] == "ai-taslak + kullanıcı düzenlemesi" and 0 < note.meta["degisim_orani"] <= 1


def test_memory_upserts_instead_of_duplicating(vault):
    client = make_client(vault)
    for answer in ("İlk hal", "İkinci, daha iyi hal"):
        client.post("/modules/application/memory", json={"context": CTX, "items": [
            {"question": Q, "answer": answer, "draft": "taslak"}]})
    notes = [n for n in vault.list("Cevaplar") if n.meta.get("kurum") == "TOG"]
    assert len(notes) == 1 and notes[0].content == "İkinci, daha iyi hal"
    assert draft_of(notes[0]) == "taslak"


def test_unchanged_draft_marked_as_ai(vault):
    client = make_client(vault)
    client.post("/modules/application/memory", json={"context": CTX, "items": [
        {"question": Q, "answer": "aynı metin", "draft": "aynı metin"}]})
    note = vault.read("Cevaplar/TOG - Neden bu bursa başvuruyorsunuz.md")
    assert note.meta["kaynak"] == "ai-taslak" and "AI taslağı" not in note.body


def test_application_save_twice_updates_same_notes(vault):
    client = make_client(vault)
    body = {"context": CTX, "items": [{"question": Q, "answer": "son hal", "draft": "taslak", "save_to_memory": True}]}
    first = client.post("/modules/application/applications", json=body).json()
    body["items"][0]["answer"] = "daha da son hal"
    second = client.post("/modules/application/applications", json=body).json()
    assert first["application_note"] == second["application_note"]
    assert len(vault.list("Başvurular")) == 1
    assert "daha da son hal" in vault.read(f"Başvurular/{second['application_note']}.md").body


def test_writer_learns_from_user_edits(vault):
    client = make_client(vault)
    client.post("/modules/application/memory", json={"context": CTX, "items": [
        {"question": Q, "answer": "Kısa yazarım, abartmam.", "draft": "Tutkulu ve dinamik bir bireyim!"}]})
    llm = FakeLLM(json.dumps({"answer": "x", "category": "motivasyon"}))
    make_client(vault, llm).post("/modules/application/answer", json={"question": "Neden bu programa katılmak istiyorsunuz?"})
    prompt = llm.prompts[-1]
    assert "nasıl düzelttiği" in prompt
    assert "Tutkulu ve dinamik bir bireyim!" in prompt and "Kısa yazarım, abartmam." in prompt
