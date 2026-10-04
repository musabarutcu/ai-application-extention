# Başvuru Asistanı

İş, staj, burs ve kampüs elçiliği başvurularında kişisel bilgilerini otomatik dolduran ve açık
uçlu sorulara **senin geçmiş cevaplarından ve profilinden** taslak yazan kişisel agent.
Chrome eklentisi arayüzdür. Beyin yerel bir Python backend'idir. Hafıza ise bir Obsidian vault'udur.

```
Chrome eklentisi (yan panel) ──localhost + token──▶ FastAPI backend ──▶ Obsidian vault (vault/)
                                                     ├─ LLM katmanı (Gemini, değiştirilebilir)
                                                     └─ Modüller: application (başvuru asistanı), ...
```

## Kurulum

1. **Python 3.11+** (python.org sürümü) kurulu olmalı.
2. `.env.example` dosyasını `.env` olarak kopyala ve `GEMINI_API_KEY` değerini gir
   ([AI Studio](https://aistudio.google.com/apikey)).
3. `baslat.bat` dosyasına çift tıkla. İlk seferde sanal ortamı kurar, sonra backend'i başlatır.
   Backend'in Windows açılışında **penceresiz** kendiliğinden başlaması için bir kez:
   `powershell -ExecutionPolicy Bypass -File otomatik-baslat.ps1` (kapatmak için sonuna `-Kaldir`).
   Loglar: `%LOCALAPPDATA%\basvuru-asistani\backend.log`.
4. Chrome'da `chrome://extensions` → sağ üstten **Geliştirici modu** → **Paketlenmemiş öğe yükle**
   → `extension/` klasörünü seç.
5. Eklenti simgesine tıkla. Yan panel backend'e **otomatik bağlanır** (token elle girilmez).
6. Obsidian'da **Open folder as vault** → `vault/` klasörünü seç ve profilini doldur.

## Kullanım

1. Başvuru formunu aç → yan panelde **Formu tara**.
2. Kısa alanlar profilinden dolar. Açık uçlu sorular için taslaklar otomatik yazılır.
   Her alanı düzenleyebilir, "Yönlendirme" ile yeniden yazdırabilir, türünü değiştirebilirsin.
3. **Doldur** → anahtarı açık alanlar sayfaya yazılır. Eklenti **asla formu göndermez**. Son kontrol ve gönderme sende.
4. **Başvuruyu kaydet** → `vault/Başvurular/` altına kayıt düşer. "Hafızaya kaydet" işaretli
   cevaplar `vault/Cevaplar/` klasörüne eklenir ve sonraki başvurularda referans olur.

### Öğrenen ve çok sayfalı formlarda çalışan özellikler
- **Alan hafızası:** Panelde bir alanın türünü ya da değerini düzeltip "Doldur"a bastığında asistan bunu
  `vault/Asistan/Alan Hafızası.md` tablosuna yazar; aynı soru tekrar gelince kendisi uygular.
- **Cevap hafızası:** Sayfada düzenlediğin son hal ("↥ Son halini kaydet" ya da "Kaydet") `Cevaplar/`a yazılır;
  AI taslağı gizli saklanır ve asistan senin düzeltmelerinden öğrenir.
- **Çok sayfalı formlar:** "İleri"ye basınca panel yeni soruları kendiliğinden tarar; önceki sayfaların
  cevapları unutulmaz ve "Kaydet"e dahil edilir. Sayfada yaptığın düzenlemeler panele canlı yansır.
- **Sayfa içi "✦ Yaz":** Taramadan sonra cevap kutularının köşesinde çıkar; tek soruya taslak yazıp doldurur
  (yan panel açık olmalı).

## Gizlilik

- Backend yalnızca `127.0.0.1` üzerinde dinler ve her istek API token ister.
- Cevap üretirken profilin, notların ve sayfa metni **seçtiğin LLM sağlayıcısına (Gemini) gönderilir**.
  E-posta, telefon, adres, doğum tarihi cevap üretim isteklerine eklenmez. Form eşleme isteği ise
  profilin tamamını içerir.
- `vault/` ve `.env` `.gitignore` içindedir.

## Geliştirme

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m pytest
```

Eklentiyi denemek için `tests/fixtures/sample_form.html` örnek formunu kullanabilirsin
(dosya olarak açacaksan eklenti ayarlarında "Dosya URL'lerine erişime izin ver" seçeneğini aç).

Yan panel arayüzünü Chrome'a yüklemeden görmek için proje kökünde
`python -m http.server 8800` çalıştırıp `http://127.0.0.1:8800/tests/fixtures/sidepanel_preview.html`
adresini aç (Chrome API'leri ve backend taklit edilir).

### Yeni modül eklemek

`backend/app/core/module.py` içindeki açıklamaya bak. Kısaca: `app/modules/<ad>/` altında
`BaseModule`'den türeyen bir sınıf yaz, `@register` ile işaretle, `app/modules/__init__.py`'de import et.
Router'ı otomatik olarak `/modules/<ad>` altına bağlanır. Vault, LLM ve ayarlara `self.ctx` ile erişir.

### LLM sağlayıcısını değiştirmek

`backend/app/core/llm/` altına `LLMProvider`'dan türeyen bir sınıf ekle (tek metot: `generate`),
`create_provider` fabrikasına bağla ve `.env` içinde `LLM_PROVIDER` değerini değiştir.
