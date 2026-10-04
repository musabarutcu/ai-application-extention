import json
import os
import time
from datetime import date

from app.core.documents import detect_type, list_documents, match_document

from .conftest import FakeLLM, make_client


def add_doc(vault, name, content=b"%PDF-1.4 test", days_old=0, meta=None):
    path = vault.root / "Belgeler" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    stamp = time.time() - days_old * 86400
    os.utime(path, (stamp, stamp))
    if meta:
        vault.write(f"Belgeler/{path.stem}.md", meta, "")
    return path


def test_detect_type():
    assert detect_type("Adli Sicil Kaydı") == "adli_sicil"
    assert detect_type("Lütfen son 3 ay içinde alınmış adli sicil kaydınızı yükleyiniz") == "adli_sicil"
    assert detect_type("Öğrenci Belgesi (e-Devlet)") == "ogrenci_belgesi"
    assert detect_type("Kardeş öğrenci belgesi") == "kardes_belgesi"  # uzun kalıp önce
    assert detect_type("Upload your CV") == "cv"
    assert detect_type("Not dökümü / Transkript") == "transkript"
    assert detect_type("Motivasyon") is None


def test_list_documents_reads_meta_and_freshness(vault):
    add_doc(vault, "Adli Sicil Kaydı.pdf", days_old=120)
    add_doc(vault, "e-Devlet belgesi.pdf", meta={"tur": "ogrenci_belgesi", "alinma_tarihi": "2026-09-30"})
    docs = {d.title: d for d in list_documents(vault)}
    assert set(docs) == {"Adli Sicil Kaydı", "e-Devlet belgesi"}  # .md notlar belge sayılmaz
    adli = docs["Adli Sicil Kaydı"]
    assert adli.type == "adli_sicil" and "120 gün" in adli.warning()
    ogr = docs["e-Devlet belgesi"]
    assert ogr.type == "ogrenci_belgesi" and ogr.obtained == date(2026, 9, 30)


def test_match_prefers_newest_and_respects_accept(vault):
    add_doc(vault, "Adli Sicil 2025.pdf", days_old=300)
    add_doc(vault, "Adli Sicil 2026.pdf", days_old=5)
    add_doc(vault, "Vesikalık.jpg", content=b"\xff\xd8\xff")
    docs = list_documents(vault)
    assert match_document("Adli sicil kaydınızı yükleyiniz", "", docs).title == "Adli Sicil 2026"
    assert match_document("Vesikalık fotoğraf", "image/*", docs).title == "Vesikalık"
    assert match_document("Vesikalık fotoğraf", ".pdf", docs) is None
    assert match_document("Proje dosyanız", "", docs) is None


def test_analyze_suggests_document_for_file_field(vault):
    add_doc(vault, "Adli Sicil Kaydı.pdf")
    client = make_client(vault)
    body = {"fields": [
        {"id": "a", "label": "12- Adli Sicil Kaydı*", "type": "file", "accept": ".pdf"},
        {"id": "b", "label": "Proje sunumu", "type": "file"},
    ]}
    res = client.post("/modules/application/analyze", json=body).json()
    s = {x["id"]: x for x in res["suggestions"]}
    assert s["a"]["kind"] == "document" and s["a"]["value"] == "Belgeler/Adli Sicil Kaydı.pdf"
    assert s["a"]["document"]["type_name"] == "Adli sicil kaydı"
    assert s["b"]["kind"] == "skip"
    assert len(res["documents"]) == 1


def test_llm_picks_document_by_anonymous_code(vault):
    add_doc(vault, "Zeki-Kaya-Maaş-Bordrosu.pdf")
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "baba_adi": "Zeki"}, note.body)
    llm = FakeLLM(json.dumps({"context": {}, "fields": [
        {"id": "x", "kind": "document", "document": "d1"},
        {"id": "y", "kind": "document", "document": "D99"},
    ]}))
    client = make_client(vault, llm)
    body = {"fields": [
        {"id": "x", "label": "Ailenizin aylık kazancını gösteren evrak", "type": "file"},
        {"id": "y", "label": "Başka evrak", "type": "file"},
    ]}
    s = {x["id"]: x for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s["x"]["kind"] == "document" and s["x"]["source"] == "llm"
    assert s["y"]["kind"] == "skip"
    prompt = llm.prompts[-1]
    assert "D1: Gelir belgesi (baba)" in prompt
    assert "Zeki" not in prompt and "Bordrosu" not in prompt and "%PDF" not in prompt


def test_owner_detection_and_matching(vault):
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "baba_adi": "Kemal", "anne_adi": "Ayten",
                            "kardesler": "Elif Yılmaz (abla), Can Yılmaz (kardeş)"}, note.body)
    from app.core.profile import load_profile
    profile = load_profile(vault)
    add_doc(vault, "Öğrenci-Belgesi.pdf", days_old=3)
    add_doc(vault, "Elif-Yılmaz-Öğrenci-Belgesi.pdf", days_old=1)   # daha yeni ama ablanın
    add_doc(vault, "Kemal Yılmaz-Sgk-Hizmet-Dökümü.pdf")
    add_doc(vault, "Ayten-Yılmaz-Sgk-Hizmet-Dökümü.pdf")
    add_doc(vault, "Deniz-Yılmaz-Sgk-Hizmet-Dökümü.pdf")
    docs = {d.title: d for d in list_documents(vault, profile)}
    assert docs["Elif-Yılmaz-Öğrenci-Belgesi"].owner == "kardes"
    assert docs["Elif-Yılmaz-Öğrenci-Belgesi"].type == "kardes_belgesi"
    assert docs["Kemal Yılmaz-Sgk-Hizmet-Dökümü"].owner == "baba"
    assert docs["Deniz-Yılmaz-Sgk-Hizmet-Dökümü"].owner == "ben"
    all_docs = list(docs.values())
    pick = lambda text: (match_document(text, "", all_docs) or type("N", (), {"title": None})).title
    assert pick("Öğrenci belgeniz") == "Öğrenci-Belgesi"                  # kardeşinki asla değil
    assert pick("Kardeşinizin öğrenci belgesi") == "Elif-Yılmaz-Öğrenci-Belgesi"
    assert pick("SGK hizmet dökümünüz") == "Deniz-Yılmaz-Sgk-Hizmet-Dökümü"
    assert pick("Babanızın SGK hizmet dökümü") == "Kemal Yılmaz-Sgk-Hizmet-Dökümü"
    assert pick("Annenizin SGK hizmet dökümü") == "Ayten-Yılmaz-Sgk-Hizmet-Dökümü"


def test_ensure_notes_written_once(vault):
    from app.core.documents import ensure_document_notes
    add_doc(vault, "Adli-Sicil-Kaydı.pdf")
    assert ensure_document_notes(vault, {}) == ["Belgeler/Adli-Sicil-Kaydı.md"]
    meta = vault.read("Belgeler/Adli-Sicil-Kaydı.md").meta
    assert meta["tur"] == "adli_sicil" and meta["sahip"] == "ben"
    vault.write("Belgeler/Adli-Sicil-Kaydı.md", {**meta, "alinma_tarihi": "2026-01-02"}, "")
    assert ensure_document_notes(vault, {}) == []                        # kullanıcının düzeltmesi korunur
    doc = list_documents(vault)[0]
    assert doc.obtained == date(2026, 1, 2)


def test_new_types():
    assert detect_type("Akdeniz-Üniversitesi-Disiplin-Durum-Belgesi") == "disiplin_belgesi"
    assert detect_type("Kyk-Burs-Belgesi") == "burs_belgesi"
    assert detect_type("Nüfus-Kağıt-Örneği") == "nufus_kayit"
    assert detect_type("Ösym-Yerleştirme-Sonucu-Belgesi") == "osym_yerlestirme"
    assert detect_type("Ösym-Sınav-Sonuçu-Belgesi") == "osym_sonuc"
    assert detect_type("Kimlik-Arka-Yüzü-Fotoğraf") == "kimlik"
    assert detect_type("Lise-Mezuniyet-Belgesi") == "diploma"
    assert detect_type("Yatay-Geçiş-Yapmasına-Engel-Yoktur-Belgesi") == "yatay_gecis"


def test_document_file_endpoint(vault):
    add_doc(vault, "CV.pdf", content=b"%PDF-cv")
    (vault.root / "Profil" / "gizli.pdf").write_bytes(b"x")
    client = make_client(vault)
    res = client.get("/modules/application/documents/file", params={"path": "Belgeler/CV.pdf"})
    assert res.status_code == 200 and res.content == b"%PDF-cv"
    assert res.headers["content-type"] == "application/pdf"
    for bad in ("Profil/gizli.pdf", "Belgeler/../Profil/gizli.pdf", "../.env", "Belgeler/yok.pdf"):
        assert client.get("/modules/application/documents/file", params={"path": bad}).status_code == 404
    assert client.get("/modules/application/documents/file", params={"path": "Belgeler/CV.pdf"},
                      headers={"X-API-Token": "yanlis"}).status_code == 401


def test_save_lists_uploaded_documents(vault):
    client = make_client(vault)
    res = client.post("/modules/application/applications", json={
        "context": {"kurum": "TOG"}, "documents": ["Adli Sicil Kaydı", "Transkript"],
    }).json()
    note = vault.read(f"Başvurular/{res['application_note']}.md")
    assert "## Yüklenen belgeler\n- Adli Sicil Kaydı\n- Transkript" in note.body


def test_detect_type_tolerates_turkish_suffixes():
    assert detect_type("Öğrenci belgenizi yükleyiniz") == "ogrenci_belgesi"
    assert detect_type("Adli sicil kaydınızı ekleyin") == "adli_sicil"
    assert detect_type("Transkriptinizi yükleyin") == "transkript"
    assert detect_type("Kimlik kartınızın ön yüzü") == "kimlik"
    assert detect_type("Proje dosyanız") is None
    assert detect_type("Belgelerinizi yükleyin") is None


def test_identity_side_preference(vault):
    add_doc(vault, "TC-Kimlik-Belgesi.pdf")
    add_doc(vault, "Kimlik-Arka-Yüzü-Fotoğraf.jpg", content=b"\xff\xd8\xff")
    add_doc(vault, "Kimlik-Ön-Yüzü.jpg", content=b"\xff\xd8\xff")
    docs = list_documents(vault)
    assert match_document("Kimlik fotokopisi", "", docs).title == "TC-Kimlik-Belgesi"
    assert match_document("Kimlik kartı arka yüzü", "", docs).title == "Kimlik-Arka-Yüzü-Fotoğraf"
    assert match_document("Kimlik kartınızın ön yüzü", "image/*", docs).title == "Kimlik-Ön-Yüzü"
