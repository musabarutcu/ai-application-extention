// Onaylanan değerleri alanlara yazar. Gönder/submit butonlarına ASLA dokunmaz;
// yalnızca extractor.js'in kaydettiği alanlar ve seçenekleri üzerinde çalışır.
(() => {
  const BA = (window.__BA = window.__BA || {});
  if (BA.fill) return;

  const norm = (s) =>
    (s || "")
      .toLocaleLowerCase("tr")
      .normalize("NFKD")
      .replace(/[̀-ͯ]/g, "")
      .replace(/ı/g, "i")
      .replace(/[^a-z0-9]+/g, " ")
      .trim();
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  function findOption(options, value) {
    const target = norm(value);
    if (!target) return null;
    const labeled = options.map((o) => ({ o, n: norm(o.label) })).filter((x) => x.n);
    const pick = (pred) => labeled.filter(pred).sort((a, b) => a.n.length - b.n.length)[0]?.o;
    return (
      pick((x) => x.n === target) ||
      pick((x) => x.n.startsWith(target + " ") || target.startsWith(x.n + " ")) ||  // "2" ~ "2. Sınıf"
      pick((x) => x.n.includes(target) || target.includes(x.n)) ||
      null
    );
  }

  function highlight(el) {
    if (!el?.style) return;
    const prev = el.style.outline;
    el.style.outline = "2px solid #7c5cff";
    el.style.outlineOffset = "2px";
    setTimeout(() => {
      el.style.outline = prev;
      el.style.outlineOffset = "";
    }, 2500);
  }

  function setNativeValue(el, value) {
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.dispatchEvent(new Event("blur", { bubbles: true }));
  }

  const isChecked = (el) => (el instanceof HTMLInputElement ? el.checked : el.getAttribute("aria-checked") === "true");

  function fillChoice(entry, value) {
    const wanted = entry.type === "checkbox" ? value.split(";").map((v) => v.trim()).filter(Boolean) : [value];
    // Tekil onay kutusu: "evet/true/x" işaretler
    if (entry.options.length === 1 && entry.type === "checkbox") {
      const want = /^(evet|yes|true|1|x|✓)$/i.test(value.trim()) || norm(value) === norm(entry.options[0].label);
      if (want !== isChecked(entry.options[0].el)) entry.options[0].el.click();
      highlight(entry.options[0].el);
      return true;
    }
    const targets = wanted.map((v) => findOption(entry.options, v)).filter(Boolean);
    if (!targets.length) return false;
    for (const opt of entry.options) {
      const should = targets.includes(opt);
      if (entry.type === "radio" ? should && !isChecked(opt.el) : should !== isChecked(opt.el)) opt.el.click();
    }
    targets.forEach((t) => highlight(t.el.labels?.[0] || t.el));
    return true;
  }

  async function fillListbox(entry, value) {
    const target = findOption(entry.options, value);
    if (!target) return false;
    entry.el.click();
    await sleep(350);
    const wanted = norm(target.label);
    const popupOption = [...document.querySelectorAll('[role="option"]')].find(
      (o) => o.getBoundingClientRect().height > 0 && norm(o.getAttribute("data-value") || o.innerText) === wanted
    );
    (popupOption || target.el).click();
    highlight(entry.el);
    return true;
  }

  function fillSelect(el, value) {
    const options = [...el.options].map((o) => ({ el: o, label: o.text }));
    const target = findOption(options, value) || options.find((o) => norm(o.el.value) === norm(value));
    if (!target) return false;
    el.value = target.el.value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    highlight(el);
    return true;
  }

  function findSearchInput(root) {
    const { isShown, popupFor } = BA.util;
    const candidates = [
      document.activeElement,
      root.querySelector('input:not([type="hidden"])'),
      popupFor(root)?.querySelector("input"),
      ...document.querySelectorAll('[class*="search" i] input, input[class*="search" i], input[type="search"]'),
    ];
    return candidates.find((el) => el instanceof HTMLInputElement && el.type !== "hidden" && isShown(el)) || null;
  }

  // Div tabanlı açılır kutu: aç → (gerekirse ara) → doğru seçeneğe tıkla
  async function fillCustomSelect(entry, value) {
    const { openDropdown, closeDropdown, visibleOptions, fire, sleep, clean, PLACEHOLDER } = BA.util;
    const root = entry.el;
    const opened = await openDropdown(root);
    let target = findOption(opened.options, value);
    if (!target) {
      // Uzun / sanal listeler: arama kutusuna yazıp listeyi daralt
      const search = findSearchInput(root);
      if (search) {
        search.focus();
        setNativeValue(search, value);
        await sleep(400);
        target = findOption(visibleOptions(root, opened.before), value);
      }
    }
    if (!target) {
      await closeDropdown(root);
      return false;
    }
    target.el.scrollIntoView({ block: "nearest" });
    fire(target.el);
    await sleep(200);
    // Seçim yapıldıysa kutunun yazısı artık "Seçiniz" olmamalı
    const shown = clean(root.innerText) || root.querySelector("input")?.value || "";
    if (PLACEHOLDER.test(shown) && !norm(shown).includes(norm(target.label))) {
      await closeDropdown(root);
      return false;
    }
    highlight(root);
    return true;
  }

  // Belge yükleme: yan panelin backend'den aldığı dosyayı (base64) <input type=file>'a koyar
  function fillFile(entry, file) {
    if (!file?.b64) return false;
    const binary = atob(file.b64);
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], file.name, { type: file.type, lastModified: Date.now() }));
    entry.el.files = transfer.files;
    entry.el.dispatchEvent(new Event("input", { bubbles: true }));
    entry.el.dispatchEvent(new Event("change", { bubbles: true }));
    highlight([...(entry.el.labels || [])].find(BA.util.isShown) || (BA.util.isShown(entry.el) ? entry.el : entry.el.parentElement));
    return entry.el.files.length === 1 && entry.el.files[0].name === file.name;
  }

  async function fillEntry(entry, value) {
    switch (entry.kind) {
      case "native":
        if (entry.type === "select") {
          const ok = fillSelect(entry.el, value);
          if (ok && entry.ui) highlight(entry.ui);  // gizli select'in görünen arayüzü
          return ok;
        }
        entry.el.focus();
        setNativeValue(entry.el, value);
        highlight(entry.el);
        return true;
      case "native-choice":
      case "aria-choice":
        return fillChoice(entry, value);
      case "aria-listbox":
        return fillListbox(entry, value);
      case "custom-select":
        return fillCustomSelect(entry, value);
      case "file":
        return fillFile(entry, value);
      default:
        return false;
    }
  }

  // Alanların sayfadaki güncel değerleri (kullanıcı doldurduktan sonra düzenlediyse son hali).
  // ids: [id] → { id: değer } ; bu frame'de olmayan id'ler atlanır.
  BA.read = (ids) => {
    const out = {};
    const checked = (el) => (el instanceof HTMLInputElement ? el.checked : el.getAttribute("aria-checked") === "true");
    for (const id of ids) {
      const entry = BA.registry?.get(id);
      if (!entry) continue;
      if (entry.kind === "native") {
        out[id] = entry.type === "select" ? entry.el.selectedOptions[0]?.text?.trim() || "" : entry.el.value;
      } else if (entry.kind === "native-choice" || entry.kind === "aria-choice") {
        out[id] = entry.options.filter((o) => checked(o.el)).map((o) => o.label).join("; ");
      } else if (entry.kind === "custom-select") {
        // kutunun yazısındaki ok/ikon karakterlerini at ("İstanbul ⌄" -> "İstanbul")
        const text = BA.util.clean(entry.el.innerText).replace(/[^\p{L}\p{N}).]+$/u, "");
        out[id] = BA.util.PLACEHOLDER.test(text) ? "" : text;
      }
    }
    return out;
  };

  // items: [{id, value}] — bu frame'de olmayan id'ler "not-found" döner.
  BA.fill = async (items) => {
    const results = [];
    for (const { id, value } of items) {
      const entry = BA.registry?.get(id);
      if (!entry) {
        results.push({ id, ok: false, error: "not-found" });
        continue;
      }
      try {
        results.push({ id, ok: await fillEntry(entry, value) });
      } catch (e) {
        results.push({ id, ok: false, error: String(e) });
      }
    }
    return results;
  };
})();
