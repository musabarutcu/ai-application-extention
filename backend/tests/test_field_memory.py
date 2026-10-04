import json

from app.modules.application_assistant.field_memory import MEMORY_NOTE, label_key, load_field_memory

from .conftest import FakeLLM, make_client


def learn(client, *items):
    return client.post("/modules/application/learn", json={"items": list(items)}).json()["learned"]


def analyze(client, *fields):
    res = client.post("/modules/application/analyze", json={"fields": list(fields)}).json()
    return {s["id"]: s for s in res["suggestions"]}


def test_label_key_ignores_numbering_and_star():
    assert label_key("6- Yaşadığın İl*") == label_key("Yaşadığın il") == "yasadigin il"


def test_learns_profile_key_from_matching_value(vault):
    client = make_client(vault)
    # kullanıcı "Okul" alanına profildeki üniversite değerini elle yazdı
    assert learn(client, {"label": "12- Okul", "kind": "profile", "value": "Örnek Teknik Üniversitesi"}) == 1
    entry = load_field_memory(vault)["okul"]
    assert entry.profile_key == "universite" and entry.value == ""
    s = analyze(client, {"id": "x", "label": "3- Okul*", "type": "text"})["x"]
    assert s["source"] == "memory" and s["value"] == "Örnek Teknik Üniversitesi"


def test_learns_constant_value_and_kind(vault):
    client = make_client(vault)
    learn(client,
          {"label": "Öğrenci numaranız", "kind": "profile", "value": "190401 | A"},
          {"label": "Bizi nereden duydunuz?", "kind": "skip"},
          {"label": "Hobileriniz", "kind": "answer"})
    s = analyze(client,
                {"id": "a", "label": "Öğrenci numaranız", "type": "text"},
                {"id": "b", "label": "Bizi nereden duydunuz?", "type": "text"},
                {"id": "c", "label": "Hobileriniz", "type": "text"})
    assert s["a"]["value"] == "190401 | A"          # | karakteri tabloda kaçışlanıp geri okunur
    assert s["b"]["kind"] == "skip" and s["c"]["kind"] == "answer"
    note = vault.read(MEMORY_NOTE)
    assert "| Öğrenci numaranız | profil |" in note.body and "190401 \| A" in note.body


def test_memory_beats_rules_and_skips_llm(vault):
    llm = FakeLLM(json.dumps({"context": {}, "fields": []}))
    client = make_client(vault, llm)
    learn(client, {"label": "E-posta", "kind": "profile", "value": "okul@ornek.edu"})
    s = analyze(client, {"id": "e", "label": "E-posta", "type": "email"})["e"]
    assert s["value"] == "okul@ornek.edu" and s["source"] == "memory"
    assert "E-posta" not in llm.prompts[-1].split("## Eşlenecek alanlar")[1]


def test_repeated_correction_counts_and_user_can_delete_row(vault):
    client = make_client(vault)
    for _ in range(3):
        learn(client, {"label": "Okul", "kind": "profile", "value": "Örnek Teknik Üniversitesi"})
    assert load_field_memory(vault)["okul"].count == 3
    note = vault.read(MEMORY_NOTE)
    vault.write(MEMORY_NOTE, note.meta, "\n".join(l for l in note.body.splitlines() if "| Okul |" not in l))
    assert "okul" not in load_field_memory(vault)
    assert analyze(client, {"id": "x", "label": "Okul", "type": "text"})["x"]["source"] != "memory"


def test_learned_profile_key_removed_falls_back(vault):
    client = make_client(vault)
    learn(client, {"label": "Lakap", "kind": "profile", "profile_key": "sehir", "value": "İstanbul"})
    note = vault.read("Profil/Kişisel Bilgiler.md")
    vault.write(note.path, {k: v for k, v in note.meta.items() if k != "sehir"}, note.body)
    assert analyze(client, {"id": "x", "label": "Lakap", "type": "text"})["x"]["source"] != "memory"
