import json

from app.modules.application_assistant.answer_writer import find_similar, guess_category
from app.modules.application_assistant.field_mapper import match_option, rule_match
from app.modules.application_assistant.schemas import FormField

from .conftest import FakeLLM, make_client


def field(label, type="text", **kw):
    return FormField(id=label, label=label, type=type, **kw)


def test_rule_match_common_labels():
    assert rule_match(field("Adınız")) == "ad"
    assert rule_match(field("Soyadınız *")) == "soyad"
    assert rule_match(field("Ad Soyad")) == "ad_soyad"
    assert rule_match(field("Full Name")) == "ad_soyad"
    assert rule_match(field("E-posta Adresiniz")) == "eposta"
    assert rule_match(field("Email Address")) == "eposta"
    assert rule_match(field("x", type="tel")) == "telefon"
    assert rule_match(field("Okuduğunuz bölüm")) == "bolum"
    assert rule_match(field("Not ortalaması (GANO)")) == "gano"
    assert rule_match(field("Adres")) == "adres"


def test_rule_match_ignores_long_questions():
    assert rule_match(field("Üniversite elçiliği programımıza neden katılmak istiyorsunuz, anlatınız?")) is None


def test_match_option():
    assert match_option("3", ["1. sınıf", "2. sınıf", "3. sınıf"]) == "3. sınıf"
    assert match_option("istanbul", ["Ankara", "İstanbul"]) == "İstanbul"
    assert match_option("x", ["a", "b"]) is None


def test_guess_category():
    assert guess_category("Neden bu programa katılmak istiyorsunuz?") == "motivasyon"
    assert guess_category("Why do you want to work at our company?") == "neden-biz"
    assert guess_category("Tell us about yourself") == "kendini-tanit"


def test_find_similar_prefers_matching_question(vault):
    notes = find_similar(vault, "Neden bu programa başvuruyorsunuz?", "motivasyon")
    assert notes[0].meta["kurum"] == "Acme"


def test_health_and_auth(vault):
    client = make_client(vault)
    assert client.get("/health").json()["modules"] == ["application"]
    assert client.get("/profile", headers={"X-API-Token": "yanlis"}).status_code == 401
    assert client.get("/profile").json()["profile"]["ad"] == "Deniz"


def test_analyze_rule_only(vault):
    client = make_client(vault)
    body = {
        "fields": [
            {"id": "1", "label": "Adınız", "type": "text"},
            {"id": "2", "label": "E-posta", "type": "email"},
            {"id": "3", "label": "Sınıf", "type": "select", "options": ["1", "2", "3", "4"]},
            {"id": "4", "label": "Neden bize katılmak istiyorsunuz? (max 200 kelime)", "type": "textarea"},
            {"id": "5", "label": "KVKK metnini okudum", "type": "checkbox", "options": ["KVKK metnini okudum"]},
        ]
    }
    res = client.post("/modules/application/analyze", json=body).json()
    s = {x["id"]: x for x in res["suggestions"]}
    assert s["1"]["value"] == "Deniz" and s["1"]["source"] == "rule"
    assert s["2"]["value"] == "deniz@example.com"
    assert s["3"]["value"] == "3"
    assert s["4"]["kind"] == "answer" and s["4"]["max_words"] == 200
    assert s["5"]["kind"] == "skip"
    assert res["llm_used"] is False


def test_analyze_with_llm_validates_output(vault):
    llm = FakeLLM(json.dumps({
        "context": {"kurum": "Acme", "pozisyon": "Kampüs Elçisi", "tip": "elçilik"},
        "fields": [
            {"id": "a", "kind": "profile", "profile_key": "sehir", "value": "istanbul"},
            {"id": "b", "kind": "profile", "profile_key": "uydurma", "value": "x"},
            {"id": "c", "kind": "answer", "profile_key": None, "value": ""},
        ],
    }))
    client = make_client(vault, llm)
    body = {"fields": [
        {"id": "a", "label": "Yaşadığın yer", "type": "select", "options": ["Ankara", "İstanbul"]},
        {"id": "b", "label": "Bir şey", "type": "text"},
        {"id": "c", "label": "Bizi nereden duydun", "type": "text"},
    ]}
    res = client.post("/modules/application/analyze", json=body).json()
    s = {x["id"]: x for x in res["suggestions"]}
    assert res["context"]["kurum"] == "Acme"
    assert s["a"]["value"] == "İstanbul"
    assert s["b"]["profile_key"] is None
    assert s["c"]["kind"] == "answer"


def test_answer_requires_llm(vault):
    client = make_client(vault)
    assert client.post("/modules/application/answer", json={"question": "Neden?"}).status_code == 503


def test_answer_uses_similar_and_enforces_limit(vault):
    llm = FakeLLM(json.dumps({"answer": "kelime " * 50, "category": "motivasyon"}))
    client = make_client(vault, llm)
    res = client.post("/modules/application/answer", json={
        "question": "Neden bu programa katılmak istiyorsunuz? (en fazla 20 kelime)",
        "context": {"kurum": "Gamma"},
    }).json()
    assert len(res["answer"].split()) == 20
    assert res["used_answers"][0].startswith("Acme")
    prompt = llm.prompts[-1]
    assert "insanları bir araya getirmeyi" in prompt
    assert "deniz@example.com" not in prompt  # iletişim bilgisi gönderilmez


def test_save_application_writes_notes(vault):
    client = make_client(vault)
    res = client.post("/modules/application/applications", json={
        "context": {"kurum": "Gamma", "pozisyon": "Stajyer", "tip": "staj"},
        "url": "https://example.com/form",
        "items": [
            {"question": "Neden biz?", "answer": "Çünkü...", "save_to_memory": True},
            {"question": "Hobiler?", "answer": "Satranç", "save_to_memory": False},
        ],
    }).json()
    assert res["saved_answers"] == ["Gamma - Neden biz"]
    app_note = vault.read(f"Başvurular/{res['application_note']}.md")
    assert app_note.meta["durum"] == "gönderildi"
    assert "[[Gamma - Neden biz]]" in app_note.body
    saved = vault.read("Cevaplar/Gamma - Neden biz.md")
    assert saved.meta["kategori"] == "neden-biz" and saved.body == "Çünkü..."
    listed = client.get("/modules/application/applications").json()["applications"]
    assert listed[0]["kurum"] == "Gamma"


def test_english_form_prefers_en_values(vault):
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "bolum_en": "Computer Engineering", "universite_en": "Example Tech"}, note.body)
    client = make_client(vault)
    body = {"title": "AI Engineer Bootcamp Application", "fields": [
        {"id": "u", "label": "University", "type": "text"},
        {"id": "d", "label": "University Department", "type": "text"},
        {"id": "n", "label": "Full Name", "type": "text"},
        {"id": "b", "label": "Date of Birth", "type": "date"},
        {"id": "l", "label": "Academic Level", "type": "text"},
    ]}
    s = {x["id"]: x for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s["u"]["value"] == "Example Tech"
    assert s["d"]["profile_key"] == "bolum" and s["d"]["value"] == "Computer Engineering"
    assert s["n"]["value"] == "Deniz Yılmaz"
    assert s["b"]["value"] == "2003-05-14"
    assert s["l"]["profile_key"] == "akademik_seviye"


def test_turkish_form_keeps_turkish_values(vault):
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "bolum_en": "Computer Engineering"}, note.body)
    client = make_client(vault)
    body = {"fields": [{"id": "d", "label": "Okuduğunuz bölüm", "type": "text"}]}
    s = client.post("/modules/application/analyze", json=body).json()["suggestions"][0]
    assert s["value"] == "Bilgisayar Mühendisliği"


def test_sensitive_rules_and_age(vault):
    from datetime import date
    from app.core.profile import load_profile
    assert rule_match(field("T.C. Kimlik Numaranız")) == "tc_kimlik_no"
    assert rule_match(field("IBAN")) == "iban"
    assert rule_match(field("Passport Expiry")) == "pasaport_gecerlilik"
    assert rule_match(field("Pasaport No")) == "pasaport_no"
    assert rule_match(field("Yaşınız")) == "yas"
    assert load_profile(vault, today=date(2026, 5, 13))["yas"] == "22"
    assert load_profile(vault, today=date(2026, 5, 14))["yas"] == "23"


def test_sensitive_values_never_reach_llm(vault):
    llm = FakeLLM(json.dumps({"context": {}, "fields": [
        {"id": "x", "kind": "profile", "profile_key": "tc_kimlik_no", "value": "uydurma"},
        {"id": "y", "kind": "profile", "profile_key": "iban", "value": ""},
    ]}))
    client = make_client(vault, llm)
    body = {"fields": [
        {"id": "x", "label": "Vatandaşlık numarası", "type": "text"},
        {"id": "y", "label": "Bursun yatırılacağı hesap", "type": "text"},
    ]}
    s = {x["id"]: x for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s["x"]["value"] == "11111111110"
    assert s["y"]["value"].startswith("TR00")
    prompt = llm.prompts[-1]
    for secret in ("11111111110", "TR00", "deniz@example.com", "2003-05-14", "+90 555"):
        assert secret not in prompt
    assert "tc_kimlik_no" in prompt  # anahtar adı görünür


def test_answer_prompt_excludes_sensitive(vault):
    llm = FakeLLM(json.dumps({"answer": "ok", "category": "diger"}))
    make_client(vault, llm).post("/modules/application/answer", json={"question": "Kendinizden bahsedin"})
    prompt = llm.prompts[-1]
    assert "11111111110" not in prompt and "tc_kimlik_no" not in prompt and "yas" not in prompt


def test_answer_choice_question_picks_valid_option(vault):
    llm = FakeLLM(json.dumps({"answer": "evet", "category": "deneyim-proje"}))
    client = make_client(vault, llm)
    res = client.post("/modules/application/answer", json={
        "question": "Daha önce bir toplulukta görev aldınız mı?", "field_type": "radio", "options": ["Evet", "Hayır"],
    }).json()
    assert res["answer"] == "Evet"
    assert "YALNIZCA şu seçeneklerden" in llm.prompts[-1]


def test_answer_choice_unknown_returns_empty(vault):
    llm = FakeLLM(json.dumps({"answer": "Bir arkadaşımdan", "category": "diger"}))
    client = make_client(vault, llm)
    res = client.post("/modules/application/answer", json={
        "question": "Programı nereden duydunuz?", "field_type": "radio", "options": ["Instagram", "LinkedIn"],
    }).json()
    assert res["answer"] == ""


def test_pair_only_for_extension_origin(vault):
    client = make_client(vault)
    ext = {"Origin": "chrome-extension://abcdefghijklmnopabcdefghijklmnop"}
    assert client.post("/pair", headers=ext).json() == {"token": "test-token"}
    assert client.post("/pair", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/pair").status_code == 403


def test_informal_numbered_labels():
    assert rule_match(field("6- Yaşadığın İl*")) == "sehir"
    assert rule_match(field("7- Sınıfın*")) == "sinif"
    assert rule_match(field("8- Üniversiten*")) == "universite"
    assert rule_match(field("9- Öğrenim Gördüğün Lisans Bölümün*")) == "bolum"
    assert rule_match(field("5- T.C. Kimlik Numaran*")) == "tc_kimlik_no"
    assert rule_match(field("LinkedIn Profil Linkin*")) == "linkedin"


def test_combobox_keeps_value_when_options_partial(vault):
    client = make_client(vault)
    body = {"fields": [
        {"id": "il", "label": "6- Yaşadığın İl*", "type": "combobox", "options": ["Adana", "Adıyaman", "Afyon"]},
        {"id": "s", "label": "Sınıfın", "type": "combobox", "options": ["1. Sınıf", "2. Sınıf", "3. Sınıf", "4. Sınıf"]},
        {"id": "u", "label": "Üniversiten", "type": "select", "options": ["Ankara Üniversitesi"]},
    ]}
    s = {x["id"]: x for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s["il"]["value"] == "İstanbul"          # listede yok ama combobox: korunur
    assert s["s"]["value"] == "3. Sınıf"           # listede var: seçeneğe uydurulur
    assert s["u"]["value"] == ""                   # gerçek select: uymayan değer yazılmaz


def test_family_fields(vault):
    from app.core.profile import load_profile, masked_profile
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "baba_adi": "Kemal", "baba_soyadi": "Yılmaz", "anne_adi": "Ayten",
                            "anne_soyadi": "Yılmaz", "kardes_sayisi": "1"}, note.body)
    profile = load_profile(vault)
    assert profile["baba_ad_soyad"] == "Kemal Yılmaz" and profile["anne_ad_soyad"] == "Ayten Yılmaz"
    assert all(v.startswith("<gizli") for k, v in masked_profile(profile).items() if k.startswith(("baba", "anne", "kardes")))
    assert rule_match(field("Baba Adı")) == "baba_adi"
    assert rule_match(field("Annenizin Adı")) == "anne_adi"
    assert rule_match(field("Baba Adı Soyadı")) == "baba_ad_soyad"
    assert rule_match(field("Kaç kardeşsiniz?")) == "kardes_sayisi"
    assert rule_match(field("Adınız")) == "ad"  # aile kalıpları kişinin kendi adını bozmamalı
    client = make_client(vault)
    body = {"fields": [{"id": "b", "label": "Baba Adı", "type": "text"}, {"id": "a", "label": "Anne Adı Soyadı", "type": "text"}]}
    s = {x["id"]: x["value"] for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s == {"b": "Kemal", "a": "Ayten Yılmaz"}


def test_financial_fields_are_private_and_mapped(vault):
    from app.core.profile import is_sensitive
    for key in ("aile_aylik_gelir", "ev_durumu", "kira_tutari", "baba_meslek", "anne_yeni_alan", "hane_kisi_sayisi"):
        assert is_sensitive(key)
    assert not is_sensitive("bolum")
    assert rule_match(field("Ailenizin aylık geliri (TL)")) == "aile_aylik_gelir"
    assert rule_match(field("Kişi başına düşen gelir")) == "kisi_basi_gelir"
    assert rule_match(field("Babanızın mesleği")) == "baba_meslek"
    assert rule_match(field("Annenizin çalışma durumu")) == "anne_calisma_durumu"
    assert rule_match(field("Oturduğunuz evin durumu")) == "ev_durumu"
    assert rule_match(field("Başka bir burs alıyor musunuz?")) == "baska_burs"
    assert rule_match(field("Hane halkı sayısı")) == "hane_kisi_sayisi"
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {**note.meta, "aile_aylik_gelir": "41234", "ev_durumu": "Kira"}, note.body)
    llm = FakeLLM(json.dumps({"context": {}, "fields": [{"id": "e", "kind": "profile", "profile_key": "ev_durumu", "value": "uydurma"}]}))
    client = make_client(vault, llm)
    body = {"fields": [
        {"id": "g", "label": "Ailenizin aylık geliri", "type": "text"},
        {"id": "e", "label": "Kaldığınız yer", "type": "select", "options": ["Kira", "Kendimize ait", "Lojman"]},
    ]}
    s = {x["id"]: x["value"] for x in client.post("/modules/application/analyze", json=body).json()["suggestions"]}
    assert s == {"g": "41234", "e": "Kira"}
    assert "41234" not in llm.prompts[-1] and "Kira\"" not in llm.prompts[-1].split("## Eşlenecek")[0]


def test_instagram_field():
    assert rule_match(field("Instagram hesabınız")) == "instagram"
    assert rule_match(field("Instagram kullanıcı adınız")) == "instagram_kullanici_adi"
    assert rule_match(field("Instagram")) == "instagram"
