// Sayfadaki form alanlarını çıkarır. Her frame'e ayrı enjekte edilir.
// window.__BA.registry: alan id -> DOM öğesi(leri); filler.js bunu kullanır.
(() => {
  const BA = (window.__BA = window.__BA || {});
  if (BA.extract) return;

  const SKIP_TYPES = new Set(["hidden", "submit", "button", "image", "reset", "password", "search", "range", "color"]);
  const clean = (s) => (s || "").replace(/\s+/g, " ").trim();
  const MAX_LABEL = 300;

  function isShown(el) {
    if (!el || !el.isConnected) return false;
    const st = getComputedStyle(el);
    if (st.display === "none" || st.visibility === "hidden") return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 || r.height > 0;
  }

  // Özel tasarımlı radio/checkbox'larda input gizli olur ama etiketi görünür.
  function isChoiceShown(el) {
    return isShown(el) || [...(el.labels || [])].some(isShown) || isShown(el.parentElement);
  }

  function textOfIds(ids) {
    return clean(ids.split(/\s+/).map((id) => document.getElementById(id)?.innerText || "").join(" "));
  }

  // Konteyner içinde öğeden ÖNCE gelen, form kontrolü olmayan metin.
  function precedingText(container, el) {
    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    let out = "";
    let node;
    while ((node = walker.nextNode())) {
      if (el.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING) break;
      if (node.parentElement?.closest("select, option, textarea, button, script, style, noscript")) continue;
      out += " " + node.textContent;
    }
    out = clean(out);
    return out.length > MAX_LABEL ? out.slice(-200) : out;
  }

  function climbForText(el, levels = 4) {
    let node = el.parentElement;
    for (let i = 0; i < levels && node && node !== document.body; i++, node = node.parentElement) {
      const t = precedingText(node, el);
      if (t) return t;
    }
    return "";
  }

  function headingOf(el) {
    // Google Forms ve benzeri: soru kartı [role=listitem] içinde [role=heading]
    const item = el.closest('[role="listitem"]');
    return clean(item?.querySelector('[role="heading"]')?.innerText || "");
  }

  function labelFor(el) {
    const labelledBy = el.getAttribute("aria-labelledby");
    if (labelledBy) {
      const t = textOfIds(labelledBy);
      if (t) return t.slice(0, MAX_LABEL);
    }
    if (el.labels && el.labels.length) {
      const t = clean([...el.labels].map((l) => l.innerText).join(" "));
      if (t) return t.slice(0, MAX_LABEL);
    }
    const aria = clean(el.getAttribute("aria-label"));
    if (aria) return aria;
    const heading = headingOf(el);
    if (heading) return heading;
    return climbForText(el) || clean(el.placeholder || el.name || el.id || "");
  }

  // ---------- özel (div tabanlı) açılır kutular ----------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const norm = (s) =>
    (s || "").toLocaleLowerCase("tr").normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
      .replace(/ı/g, "i").replace(/[^a-z0-9]+/g, " ").trim();
  const PLACEHOLDER = /^(.*\b)?(se[cç]iniz|se[cç]in|l[uü]tfen se[cç]|select|choose|pick)\b/i;
  const OPTION_SEL = [
    '[role="option"]', '[role="menuitem"]', '[role="treeitem"]', '[role="listbox"] li',
    '[class*="option" i]:not(select):not(option)', '[class*="dropdown" i] li', '[class*="menu" i] li',
    '[class*="list" i] > li', '[class*="item" i][data-value]',
  ].join(",");
  const COMBO_SEL = '[role="combobox"], [aria-haspopup="listbox"], [aria-haspopup="true"], [aria-haspopup="menu"]';
  const CLASS_HINT = /(^|[\s_-])(select|dropdown|combo|picker|choices|multiselect)/i;

  function fire(el) {
    const opts = { bubbles: true, cancelable: true, view: window };
    el.dispatchEvent(new PointerEvent("pointerdown", opts));
    el.dispatchEvent(new MouseEvent("mousedown", opts));
    el.dispatchEvent(new PointerEvent("pointerup", opts));
    el.dispatchEvent(new MouseEvent("mouseup", opts));
    el.dispatchEvent(new MouseEvent("click", opts));
  }

  function popupFor(root) {
    const inner = root.matches("[aria-controls],[aria-owns]") ? root : root.querySelector("[aria-controls],[aria-owns]");
    const id = inner?.getAttribute("aria-controls") || inner?.getAttribute("aria-owns");
    const popup = id && document.getElementById(id);
    return popup && isShown(popup) ? popup : null;
  }

  /** Açık durumdaki görünür seçenekler: önce aria-controls ile bağlı liste, yoksa açınca beliren öğeler. */
  function visibleOptions(root, before) {
    const popup = popupFor(root);
    let els = popup ? [...popup.querySelectorAll(OPTION_SEL)] : [...document.querySelectorAll(OPTION_SEL)];
    // Açmadan önce de görünen öğeler (kutunun kendi yazısı vb.) seçenek değildir
    els = els.filter((o) => isShown(o) && (popup || !before || !before.has(o)));
    // iç içe eşleşmelerde en içtekini tut
    els = els.filter((o) => !els.some((other) => other !== o && o.contains(other)));
    return els.map((el) => ({ el, label: clean(el.getAttribute("data-value") && !el.innerText.trim() ? el.getAttribute("data-value") : el.innerText) }))
      .filter((o) => o.label && o.label.length <= 120 && !PLACEHOLDER.test(o.label));
  }

  async function openDropdown(root) {
    const before = new Set([...document.querySelectorAll(OPTION_SEL)].filter(isShown));
    const target = root.querySelector('[role="combobox"]') || root;
    fire(target);
    await sleep(220);
    let options = visibleOptions(root, before);
    if (!options.length) {
      // klavye ile açılan kutular
      (target.focus ? target : root).focus?.();
      target.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", code: "ArrowDown", bubbles: true }));
      await sleep(220);
      options = visibleOptions(root, before);
    }
    return { before, options };
  }

  async function closeDropdown(root) {
    const active = document.activeElement || root;
    for (const el of [active, root]) {
      el.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", bubbles: true }));
    }
    document.body.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    active.blur?.();
    await sleep(80);
  }

  function findCustomDropdowns() {
    const found = new Set();
    for (const el of document.querySelectorAll(COMBO_SEL)) {
      if (el.tagName === "SELECT" || el.closest("select") || !isShown(el)) continue;
      found.add(el);
    }
    // Rol belirtmeyen bileşenler: sınıf adında select/dropdown geçen, "Seçiniz" yazan tıklanabilir kutular
    for (const el of document.querySelectorAll("div, button, span, a")) {
      if (found.has(el) || !CLASS_HINT.test(el.className?.baseVal ?? el.className ?? "") || !isShown(el)) continue;
      const text = clean(el.innerText);
      if (!text || text.length > 60) continue;
      // "Seçiniz" yazıyorsa açılır kutudur; doldurulmuşsa ("İstanbul") form içinde tıklanabilir olmasına bak.
      // (Form dışındaki menü/navigasyon "dropdown"larını açmamak için.)
      const inForm = el.closest('form, [role="form"], [class*="form" i], [class*="question" i], [class*="field" i]');
      if (!PLACEHOLDER.test(text) && !(inForm && getComputedStyle(el).cursor === "pointer")) continue;
      // İçinde görünür bir metin alanı varsa bu bir açılır kutu değil, form grubudur.
      // (Kapalı menüdeki gizli arama kutusu sayılmaz.)
      if ([...el.querySelectorAll("textarea, select, input:not([type=hidden]):not([role=combobox])")].some(isShown)) continue;
      found.add(el);
    }
    // İç içe adaylarda en dıştakini tut (kontrolün tamamı); ama bir form grubunu tümden yutmasın
    const list = [...found];
    return list.filter((el) => !list.some((other) => other !== el && other.contains(el) && clean(other.innerText).length <= 80));
  }

  BA.util = { sleep, norm, fire, isShown, clean, openDropdown, closeDropdown, visibleOptions, popupFor, PLACEHOLDER };

  function descriptionFor(el) {
    const ids = el.getAttribute("aria-describedby");
    return ids ? textOfIds(ids).slice(0, MAX_LABEL) : "";
  }

  function choiceLabel(el) {
    return clean(
      [...(el.labels || [])].map((l) => l.innerText).join(" ") ||
        el.getAttribute("aria-label") ||
        el.getAttribute("data-value") ||
        el.getAttribute("data-answer-value") ||
        el.innerText ||
        el.value
    );
  }

  function groupLabelFor(first, container) {
    const legend = first.closest("fieldset")?.querySelector("legend");
    if (legend) return clean(legend.innerText);
    const group = container || first.closest('[role="radiogroup"], [role="group"], [role="list"]');
    if (group) {
      const lb = group.getAttribute("aria-labelledby");
      if (lb && textOfIds(lb)) return textOfIds(lb);
      const aria = clean(group.getAttribute("aria-label"));
      if (aria) return aria;
    }
    return headingOf(first) || climbForText(group || first, 5);
  }

  BA.extract = async () => {
    BA.registry = new Map();
    const fields = [];
    const prefix = "f" + Math.random().toString(36).slice(2, 7) + "_";
    let n = 0;
    const add = (entry, meta) => {
      const id = prefix + n++;
      BA.registry.set(id, entry);
      fields.push({ id, ...meta });
    };

    // 0) Özel açılır kutular (div tabanlı). İçlerindeki input'lar yerel alan sayılmaz.
    const customRoots = findCustomDropdowns();
    const insideCustom = (el) => customRoots.some((root) => root.contains(el));
    const coveredRoots = new Set();

    // 1) Yerel form kontrolleri
    const seenGroups = new Set();
    for (const el of document.querySelectorAll("input, textarea, select")) {
      if (el.disabled) continue;
      if (el.tagName === "SELECT" && !isShown(el)) {
        // Gizli <select> + üstünde özel görünüm (Select2, Choices.js, bootstrap-select...): değeri doğrudan select'e yaz
        const ui = customRoots.find((root) => el.parentElement?.contains(root) || root.contains(el));
        if (!ui) continue;
        coveredRoots.add(ui);
        add({ kind: "native", type: "select", el, ui }, {
          type: "select",
          label: labelFor(el) || labelFor(ui),
          name: el.name || "",
          required: el.required,
          options: [...el.options].filter((o) => !o.disabled && o.value !== "").map((o) => clean(o.text)),
        });
        continue;
      }
      if (el.readOnly || insideCustom(el)) continue;
      const type =
        el.tagName === "TEXTAREA" ? "textarea" : el.tagName === "SELECT" ? "select" : (el.type || "text").toLowerCase();
      if (SKIP_TYPES.has(type)) continue;

      if (type === "file") {
        // Dosya alanları çoğunlukla gizlidir; üstünde "Dosya seç" butonu/etiketi görünür
        const visibleUi = isShown(el) || [...(el.labels || [])].some(isShown) || isShown(el.parentElement);
        if (!visibleUi) continue;
        // "Dosya seç" / "Upload" gibi buton yazıları soruyu anlatmaz; o zaman üstteki başlığa bak
        let label = labelFor(el);
        if (!label || /^(dosya (se[cç]|y[uü]kle)|y[uü]kle|g[oö]zat|choose file|browse|upload|select file)/i.test(label)) {
          label = headingOf(el) || climbForText(el.parentElement || el, 5) || label;
        }
        add({ kind: "file", type, el }, {
          type,
          label: label || clean(el.parentElement?.innerText).slice(0, 200),
          description: descriptionFor(el),
          name: el.name || "",
          accept: el.accept || "",
          multiple: el.multiple,
          required: el.required,
        });
        continue;
      }

      if (type === "radio" || type === "checkbox") {
        const key = `${type}:${el.name}`;
        if (el.name && seenGroups.has(key)) continue;
        if (el.name) seenGroups.add(key);
        const scope = el.form || document;
        const members = el.name
          ? [...scope.querySelectorAll(`input[type="${type}"][name="${CSS.escape(el.name)}"]`)]
          : [el];
        const options = members.filter(isChoiceShown).map((m) => ({ el: m, label: choiceLabel(m) }));
        if (!options.length) continue;
        const single = options.length === 1 && type === "checkbox";
        add(
          { kind: "native-choice", type, options },
          {
            type,
            label: single ? options[0].label : groupLabelFor(members[0]),
            options: options.map((o) => o.label),
            required: members.some((m) => m.required),
            name: el.name || "",
          }
        );
        continue;
      }

      if (!isShown(el)) continue;
      const meta = {
        type,
        label: labelFor(el),
        description: descriptionFor(el),
        name: el.name || "",
        placeholder: el.placeholder || "",
        required: el.required || el.getAttribute("aria-required") === "true",
        max_length: el.maxLength > 0 ? el.maxLength : null,
      };
      if (type === "select") {
        meta.options = [...el.options].filter((o) => !o.disabled && o.value !== "").map((o) => clean(o.text));
      }
      add({ kind: "native", type, el }, meta);
    }

    // 2) ARIA tabanlı seçimler (Google Forms vb. div ile çizilen radio/checkbox/dropdown)
    const ariaRadios = [...document.querySelectorAll('[role="radio"]:not(input)')].filter(isShown);
    const ariaChecks = [...document.querySelectorAll('[role="checkbox"]:not(input)')].filter(isShown);
    const groupOf = (el) =>
      el.closest('[role="radiogroup"], [role="group"], [role="list"], [role="listitem"]') || el.parentElement;

    for (const [type, items] of [["radio", ariaRadios], ["checkbox", ariaChecks]]) {
      const groups = new Map();
      for (const el of items) {
        const g = groupOf(el);
        if (!groups.has(g)) groups.set(g, []);
        groups.get(g).push(el);
      }
      for (const [container, members] of groups) {
        const options = members.map((m) => ({ el: m, label: choiceLabel(m) }));
        add(
          { kind: "aria-choice", type, options },
          {
            type,
            label: groupLabelFor(members[0], container),
            options: options.map((o) => o.label),
            required: container.getAttribute?.("aria-required") === "true",
          }
        );
      }
    }

    for (const box of document.querySelectorAll('[role="listbox"]')) {
      if (!isShown(box) || box.closest("select")) continue;
      const options = [...box.querySelectorAll('[role="option"]')]
        .map((o) => ({ el: o, label: clean(o.getAttribute("data-value") || o.innerText) }))
        .filter((o) => o.label);
      // Google Forms'ta ilk seçenek "Seçin" yer tutucusudur (data-value boş)
      const real = options.filter((o) => o.el.getAttribute("data-value") !== "");
      if (!real.length) continue;
      add(
        { kind: "aria-listbox", type: "select", el: box, options: real },
        { type: "select", label: labelFor(box), options: real.map((o) => o.label), required: box.getAttribute("aria-required") === "true" }
      );
    }

    // 3) Özel açılır kutular: bir anlığına açıp seçenekleri oku, sonra kapat
    for (const root of customRoots.slice(0, 40)) {
      if (coveredRoots.has(root)) continue;
      let options = [];
      try {
        const opened = await openDropdown(root);
        options = opened.options;
      } catch {}
      await closeDropdown(root);
      const current = clean(root.innerText);
      add({ kind: "custom-select", type: "combobox", el: root }, {
        type: "combobox",
        label: labelFor(root.querySelector('[role="combobox"]') || root),
        placeholder: PLACEHOLDER.test(current) ? current : "",
        options: [...new Set(options.map((o) => o.label))].slice(0, 400),
        required: root.getAttribute("aria-required") === "true" || !!root.querySelector('[aria-required="true"]'),
      });
    }

    return {
      url: location.href,
      title: document.title,
      isTop: window === window.top,
      page_text: window === window.top ? clean(document.body?.innerText || "").slice(0, 4000) : "",
      fields,
    };
  };
})();
