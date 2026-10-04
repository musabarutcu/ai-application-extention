from app.core.llm.base import parse_json
from app.core.profile import load_background, load_profile
from app.core.text import detect_limits, fit_to_limits, normalize
from app.core.vault import safe_filename


def test_normalize_turkish():
    assert normalize("İSTANBUL Şehri, Ünİversİte!") == "istanbul sehri universite"
    assert normalize("E-posta Adresiniz:") == "e posta adresiniz"


def test_detect_limits():
    assert detect_limits("Neden biz? (en fazla 300 kelime)") == (None, 300)
    assert detect_limits("Max 1000 characters") == (1000, None)
    assert detect_limits("250-300 kelime arası yazınız") == (None, 300)
    assert detect_limits("Kendinizden bahsedin") == (None, None)


def test_fit_to_limits_cuts_at_sentence():
    text = "Birinci cümle burada. İkinci cümle de burada. Üçüncü cümle çok uzun olacak şekilde devam ediyor"
    result = fit_to_limits(text, max_chars=60)
    assert len(result) <= 60 and result.endswith(".")


def test_parse_json_with_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Tabii: {"a": 2} umarım işe yarar') == {"a": 2}


def test_safe_filename():
    assert safe_filename('Acme: "Neden?" / test') == "Acme Neden test"


def test_load_profile_skips_empty_and_derives_full_name(vault):
    profile = load_profile(vault)
    assert profile["ad_soyad"] == "Deniz Yılmaz"
    assert profile["dogum_tarihi"] == "2003-05-14"
    assert "github" not in profile


def test_background_strips_comments(vault):
    background = load_background(vault)
    assert "yorum" not in background
    assert "eğitim teknolojileri" in background


def test_vault_write_roundtrip(vault):
    path = vault.unique_path("Cevaplar", "Acme - Neden bu programa katılmak istiyorsunuz")
    assert path.endswith("(2).md")
    vault.write(path, {"soru": "Ş?", "kurum": "Çağ"}, "Gövde")
    note = vault.read(path)
    assert note.meta == {"soru": "Ş?", "kurum": "Çağ"} and note.body == "Gövde"
