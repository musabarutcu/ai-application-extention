const DEFAULT_URL = "http://127.0.0.1:8765";
const $ = (id) => document.getElementById(id);

const state = {
  settings: { baseUrl: DEFAULT_URL, token: "" },
  tabId: null,
  page: { url: "", title: "", page_text: "" },
  documents: [], // vault/Belgeler içindeki tüm belgeler (analyze cevabından)
  carried: new Map(), // çok sayfalı formlar: önceki taramalardaki alanlar (etiket anahtarı -> item)
  host: "",           // aynı başvurunun sayfalarını tanımak için
  scanning: false,
  items: [], // { field, kind, value, include, remember, hint, category, used, max_chars, max_words, profile_key, status, writing, node }
};

const KIND_LABELS = { profile: "Profil", answer: "Cevap", skip: "Atla" };
const FILE_KIND_LABELS = { document: "Belge", skip: "Atla" };

// ---------- yardımcılar ----------

/** Küçük DOM yardımcısı. Sayfadan gelen metinler her zaman textContent ile yazılır. */
function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) if (child != null && child !== false) el.append(child);
  return el;
}

let toastTimer;
function toast(message, type = "") {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast glass ${type}`;
  clearTimeout(toastTimer);
  if (type !== "err") toastTimer = setTimeout(() => el.classList.add("hidden"), 4500);
}
$("toast").addEventListener("click", () => $("toast").classList.add("hidden"));

function setConn(status, text) {
  $("conn").className = `conn ${status}`;
  $("conn-text").textContent = text;
}

function setLoading(button, loading) {
  button.disabled = loading;
  button.classList.toggle("loading", loading);
}

async function runPool(tasks, limit = 2) {
  const queue = [...tasks];
  await Promise.all(Array.from({ length: limit }, async () => {
    while (queue.length) await queue.shift()();
  }));
}

const countWords = (s) => (s.trim() ? s.trim().split(/\s+/).length : 0);
const getContext = () => ({ kurum: $("ctx-kurum").value.trim(), pozisyon: $("ctx-pozisyon").value.trim(), tip: $("ctx-tip").value });
const backendUrl = (path) => state.settings.baseUrl.replace(/\/+$/, "") + path;

// ---------- backend ----------

// Token'ı backend'den otomatik al (yalnızca eklenti kökeninden izinli). Elle girmeye gerek kalmaz.
async function pair() {
  const res = await fetch(backendUrl("/pair"), { method: "POST" });
  if (!res.ok) throw new Error("Otomatik eşleşme başarısız.");
  const { token } = await res.json();
  state.settings.token = token;
  await chrome.storage.local.set({ token });
  $("api-token").value = token;
}

async function api(path, body, retried = false) {
  let res;
  try {
    if (!state.settings.token && path !== "/health") await pair();
    res = await fetch(backendUrl(path), {
      method: body ? "POST" : "GET",
      headers: { "Content-Type": "application/json", "X-API-Token": state.settings.token },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new Error("Backend'e ulaşılamadı. baslat.bat çalışıyor mu?");
  }
  if (res.status === 401 && !retried) {
    // Token değişmiş olabilir (.env yenilendi): yeniden eşleş ve bir kez daha dene
    state.settings.token = "";
    return api(path, body, true);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {}
    throw new Error(res.status === 401 ? "Token geçersiz; ayarlardan 'Otomatik eşleş'e bas." : detail);
  }
  return res.json();
}

/** Belgeyi backend'den alıp sayfaya taşınabilir hale getirir: {name, type, b64}. */
async function fetchDocument(path, retried = false) {
  if (!state.settings.token) await pair();
  let res;
  try {
    res = await fetch(backendUrl("/modules/application/documents/file?path=" + encodeURIComponent(path)), {
      headers: { "X-API-Token": state.settings.token },
    });
  } catch {
    throw new Error("Backend'e ulaşılamadı.");
  }
  if (res.status === 401 && !retried) {
    state.settings.token = "";
    return fetchDocument(path, true);
  }
  if (!res.ok) throw new Error(res.status === 404 ? "Belge bulunamadı" : `Belge alınamadı (${res.status})`);
  const bytes = new Uint8Array(await res.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  const doc = state.documents.find((d) => d.path === path);
  return { name: doc?.filename || path.split("/").pop(), type: res.headers.get("content-type") || "", b64: btoa(binary) };
}

const formatSize = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB");
const formatAge = (d) => (d == null ? "" : d === 0 ? "bugün" : `${d} gün önce`);

// ---------- ayarlar & bağlantı ----------

async function loadSettings() {
  const saved = await chrome.storage.local.get(["baseUrl", "token"]);
  state.settings.baseUrl = saved.baseUrl || DEFAULT_URL;
  state.settings.token = saved.token || "";
  $("base-url").value = state.settings.baseUrl;
  $("api-token").value = state.settings.token;
}

async function checkConnection() {
  const msg = $("settings-msg");
  setConn("wait", "Bağlanıyor…");
  try {
    const health = await api("/health");
    const { profile } = await api("/profile");
    const engine = health.llm ? "Gemini" : "Kurallar";
    setConn("ok", `${engine} · profilde ${Object.keys(profile).length} alan`);
    msg.textContent = "Bağlandı.";
    return true;
  } catch (e) {
    setConn("err", "Bağlantı yok");
    msg.textContent = e.message;
    toast(e.message, "err");
    return false;
  }
}

$("settings-toggle").addEventListener("click", () => $("settings").classList.toggle("hidden"));
$("settings-save").addEventListener("click", async () => {
  state.settings.baseUrl = $("base-url").value.trim() || DEFAULT_URL;
  state.settings.token = $("api-token").value.trim();
  await chrome.storage.local.set({ baseUrl: state.settings.baseUrl, token: state.settings.token });
  if (await checkConnection()) $("settings").classList.add("hidden");
});
$("settings-pair").addEventListener("click", async () => {
  state.settings.baseUrl = $("base-url").value.trim() || DEFAULT_URL;
  await chrome.storage.local.set({ baseUrl: state.settings.baseUrl });
  try {
    await pair();
    if (await checkConnection()) $("settings").classList.add("hidden");
  } catch (e) {
    $("settings-msg").textContent = e.message;
  }
});

// ---------- tarama ----------

async function injectAndExtract(tabId) {
  const files = ["content/extractor.js", "content/filler.js", "content/live.js"];
  const extract = () => window.__BA.extract();
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files });
    return await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: extract });
  } catch {
    // Bazı alt frame'lere erişilemiyorsa sadece ana sayfa
    await chrome.scripting.executeScript({ target: { tabId }, files });
    return await chrome.scripting.executeScript({ target: { tabId }, func: extract });
  }
}

/** Etiketten numara/işaret bağımsız anahtar ("6- Yaşadığın İl*" ~ "Yaşadığın il"). */
const labelKey = (label) => (label || "").replace(/^\s*\d{1,3}\s*[-.)]\s*/, "")
  .toLocaleLowerCase("tr").replace(/[^\p{L}\p{N}]+/gu, " ").trim();

/** Önceki taramanın alanlarını sakla: çok sayfalı formda önceki sayfaların cevapları kaybolmasın. */
function carryCurrentItems() {
  for (const item of state.items) {
    const key = labelKey(item.field.label);
    if (key && (item.value.trim() || item.kind !== item.suggested?.kind)) state.carried.set(key, item);
  }
}

async function scan(button, { auto = false } = {}) {
  if (state.scanning) return;
  state.scanning = true;
  setLoading(button, true);
  try {
    const tab = auto ? await chrome.tabs.get(state.tabId) : (await chrome.tabs.query({ active: true, currentWindow: true }))[0];
    if (!tab?.id || !/^(https?|file):/.test(tab.url || "")) throw new Error("Bu sekmede çalışamıyorum; bir başvuru formu aç.");
    const host = new URL(tab.url).host;
    if (host !== state.host) {
      // başka bir siteye/başvuruya geçildi: önceki sayfalardan taşınanları bırak
      state.carried.clear();
      $("ctx-kurum").value = $("ctx-pozisyon").value = "";
      $("ctx-tip").value = "";
    } else {
      carryCurrentItems();
    }
    state.host = host;
    state.tabId = tab.id;

    const frames = (await injectAndExtract(tab.id)).map((r) => r.result).filter(Boolean);
    const top = frames.find((f) => f.isTop) || frames[0];
    const fields = frames.flatMap((f) => f.fields);
    if (!fields.length) {
      if (auto) return;  // ör. gönderim sonrası teşekkür sayfası: sessizce geç
      throw new Error("Bu sayfada form alanı bulunamadı.");
    }
    state.page = { url: top.url, title: top.title, page_text: top.page_text };

    toast(auto ? "Sayfa değişti, yeni alanlar taranıyor…" : `${fields.length} alan bulundu, profilinle eşleniyor…`);
    const res = await api("/modules/application/analyze", { ...state.page, fields });

    state.documents = res.documents || [];
    const byId = new Map(res.suggestions.map((s) => [s.id, s]));
    state.items = fields.map((field) => {
      const s = byId.get(field.id) || { kind: "skip", value: "" };
      const item = {
        field,
        suggested: { kind: s.kind, value: s.value || "", profile_key: s.profile_key || "" },
        source: s.source,
        kind: s.kind,
        value: s.value || "",
        include: !!s.value && s.kind !== "skip",
        remember: !field.options?.length,  // "Evet/Hayır" gibi seçimler yazım örneği değil, hafızaya girmesin
        draft: "",
        hint: "",
        category: "",
        used: [],
        max_chars: s.max_chars ?? field.max_length ?? null,
        max_words: s.max_words ?? null,
        profile_key: s.profile_key,
        status: null,
        writing: false,
      };
      // Aynı soru daha önce bu başvuruda görüldüyse (yeniden tarama / geri dönülen sayfa) onu koru
      const previous = state.carried.get(labelKey(field.label));
      if (previous) {
        Object.assign(item, {
          kind: previous.kind, value: previous.value, include: previous.include, remember: previous.remember,
          draft: previous.draft, hint: previous.hint, category: previous.category, used: previous.used,
        });
        state.carried.delete(labelKey(field.label));
      }
      return item;
    });

    // Bağlam: kullanıcının yazdığını ezme, boşsa doldur
    if (!$("ctx-kurum").value) $("ctx-kurum").value = res.context.kurum || "";
    if (!$("ctx-pozisyon").value) $("ctx-pozisyon").value = res.context.pozisyon || "";
    if (!$("ctx-tip").value && [...$("ctx-tip").options].some((o) => o.value === res.context.tip)) $("ctx-tip").value = res.context.tip;
    $("hero").classList.add("hidden");
    $("context").classList.remove("hidden");
    $("dock").classList.remove("hidden");
    render();

    if (res.warnings.length) toast("⚠ " + res.warnings.join(" "));
    else toast(`${fields.length} alan hazır` + (state.carried.size ? ` · önceki sayfalardan ${carriedAnswers().length} cevap saklanıyor` : ""), "ok");
    await setupLive();

    if (res.llm_used) {
      const pending = state.items.filter((i) => i.kind === "answer" && !i.value);
      if (pending.length) await runPool(pending.map((item) => () => writeAnswer(item)));
    }
  } catch (e) {
    toast(e.message, "err");
  } finally {
    state.scanning = false;
    setLoading(button, false);
  }
}

$("scan").addEventListener("click", () => scan($("scan")));
$("rescan").addEventListener("click", () => scan($("rescan")));

// ---------- sayfa ile canlı bağlantı ----------

const isTextAnswer = (i) => i.kind === "answer" && !i.field.options?.length && ["textarea", "text", ""].includes(i.field.type);
const carriedAnswers = () => [...state.carried.values()].filter((i) => i.kind === "answer" && i.value.trim());

/** Tarama sonrası: cevapları izle, sayfa değişimini dinle, cevap kutularına "✦ Yaz" koy. */
async function setupLive() {
  if (!state.tabId) return;
  const watch = state.items.filter((i) => i.kind === "answer").map((i) => i.field.id);
  const inline = state.items.filter(isTextAnswer).map((i) => i.field.id);
  try {
    await chrome.scripting.executeScript({
      target: { tabId: state.tabId, allFrames: true },
      func: (watchIds, inlineIds) => {
        if (!window.__BA?.watch) return;
        window.__BA.watch(watchIds);
        window.__BA.observe();
        window.__BA.decorate(inlineIds.filter((id) => window.__BA.registry.has(id)));
      },
      args: [watch, inline],
    });
  } catch {}
}

async function setInline(id, inlineState) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId: state.tabId, allFrames: true },
      func: (fieldId, s) => window.__BA?.setInline?.(fieldId, s),
      args: [id, inlineState],
    });
  } catch {}
}

async function fillItems(list) {
  const results = await chrome.scripting.executeScript({
    target: { tabId: state.tabId, allFrames: true },
    func: (items) => window.__BA?.fill(items),
    args: [list],
  });
  const ok = new Set();
  for (const r of results) for (const x of r.result || []) if (x.ok) ok.add(x.id);
  return ok;
}

let autoScanTimer;
function scheduleAutoScan() {
  clearTimeout(autoScanTimer);
  autoScanTimer = setTimeout(() => {
    if (state.items.length && !state.scanning) scan($("rescan"), { auto: true });
  }, 700);
}

chrome.runtime.onMessage.addListener((message, sender) => {
  if (!message?.type?.startsWith("ba:") || sender.tab?.id !== state.tabId) return;
  const item = state.items.find((i) => i.field.id === message.id);

  if (message.type === "ba:value" && item && typeof message.value === "string") {
    // Kullanıcı sayfada düzenledi: panel son hali tutar (sayfa sonra değişse bile kaybolmaz)
    if (message.value === item.value) return;
    item.value = message.value;
    if (item.status === "saved") item.status = null;
    if (!item.node?.contains(document.activeElement)) rerender(item);
  } else if (message.type === "ba:changed") {
    scheduleAutoScan();  // çok adımlı form: İleri'ye basıldı, yeni alanlar geldi
  } else if (message.type === "ba:write") {
    writeInline(message.id);
  }
});

// Tam sayfa yenilenen çok sayfalı formlar
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (tabId === state.tabId && info.status === "complete") scheduleAutoScan();
});

/** Sayfadaki "✦ Yaz" butonu: taslak yaz ve doğrudan o kutuya doldur. */
async function writeInline(id) {
  const item = state.items.find((i) => i.field.id === id);
  if (!item) return setInline(id, "error");
  if (item.kind !== "answer") {
    item.kind = "answer";
    render();
  }
  await writeAnswer(item);
  if (!item.value.trim() || item.status?.startsWith?.("error:")) return setInline(id, "error");
  try {
    const ok = await fillItems([{ id, value: item.value }]);
    item.status = ok.has(id) ? "ok" : "fail";
    item.include = true;
    rerender(item);
    setInline(id, ok.has(id) ? "done" : "error");
  } catch {
    setInline(id, "error");
  }
}

/** Panelde yapılan düzeltmeler (tür değişikliği, elle girilen değer) alan hafızasına öğretilir. */
function learnCorrections() {
  const corrections = state.items.filter((i) => {
    const s = i.suggested;
    if (!s || !i.field.label) return false;
    if (i.kind !== s.kind) return true;
    return (i.kind === "profile" || i.kind === "document") && i.value.trim() && i.value.trim() !== s.value.trim();
  }).map((i) => ({
    label: i.field.label, type: i.field.type, kind: i.kind,
    profile_key: i.kind === "profile" && i.value === i.suggested.value ? i.suggested.profile_key : "",
    value: i.kind === "answer" ? "" : i.value,
  }));
  if (!corrections.length) return;
  api("/modules/application/learn", { items: corrections })
    .then((res) => {
      // aynı düzeltme tekrar öğretilmesin
      for (const i of state.items) i.suggested = { kind: i.kind, value: i.value, profile_key: i.profile_key || "" };
      if (res.learned) toast(`🧠 ${res.learned} düzeltmeni öğrendim; bir dahakine kendim yaparım.`, "ok");
    })
    .catch(() => {});
}

// ---------- çizim ----------

function render() {
  const groups = { profile: [], answer: [], document: [], skip: [] };
  for (const item of state.items) groups[item.kind].push(item);

  $("groups").replaceChildren(
    groups.answer.length ? group("Cevaplar", groups.answer, { stack: true }) : null,
    groups.document.length ? group("Belgeler", groups.document) : null,
    groups.profile.length ? group("Kişisel bilgiler", groups.profile) : null,
    groups.skip.length ? group("Atlananlar", groups.skip, { collapsed: true }) : null,
  );
}

function group(title, items, { stack = false, collapsed = false } = {}) {
  const heading = [title, h("span", { class: "count", text: String(items.length) })];
  const body = stack
    ? h("div", { class: "stack" }, items.map(buildItem))
    : h("div", { class: "list glass" }, items.map(buildItem));
  return collapsed
    ? h("details", { class: "group" }, h("summary", { class: "group-title" }, heading), body)
    : h("section", { class: "group" }, h("div", { class: "group-title" }, heading), body);
}

function buildItem(item) {
  const node = item.kind === "answer" ? answerCard(item) : item.kind === "document" ? documentRow(item) : row(item);
  item.node = node;
  return node;
}

function rerender(item) {
  const old = item.node;
  if (old?.isConnected) old.replaceWith(buildItem(item));
}

function kindSelect(item) {
  return h("select", {
    class: "kind", "aria-label": "Alan türü", title: "Alan türünü değiştir",
    onchange: (e) => {
      item.kind = e.target.value;
      item.include = item.kind !== "skip" && !!item.value.trim();
      render();
    },
  }, Object.entries(item.field.type === "file" ? FILE_KIND_LABELS : KIND_LABELS)
    .map(([value, label]) => h("option", { value, text: label + " ▾", selected: value === item.kind })));
}

// Dosya yükleme alanı: hangi belgenin yükleneceğini seç
function documentRow(item) {
  const node = h("div", { class: "row" + (item.include ? "" : " off") });
  const doc = () => state.documents.find((d) => d.path === item.value);
  const info = h("div", { class: "meta" });
  const updateInfo = () => {
    const d = doc();
    const status = metaFor(item);
    if (status.text && item.status) {
      info.className = `meta ${status.cls}`;
      info.textContent = status.text;
    } else if (!state.documents.length) {
      info.className = "meta warn";
      info.textContent = "Belge yok: dosyalarını vault/Belgeler klasörüne koy.";
    } else if (!d) {
      info.className = "meta warn";
      info.textContent = "Eşleşen belge bulunamadı; listeden seç.";
    } else {
      info.className = `meta ${d.warning ? "warn" : ""}`;
      const typeLabel = d.owner && d.owner !== "ben" ? `${d.type_name} (${d.owner_name})` : d.type_name;
      info.textContent = d.warning || [typeLabel, d.filename.split(".").pop().toUpperCase(), formatSize(d.size), formatAge(d.age_days)].filter(Boolean).join(" · ");
    }
  };
  const select = h("select", { class: "value", "aria-label": item.field.label },
    h("option", { value: "", text: "Belge seçilmedi" }),
    state.documents.map((d) => h("option", { value: d.path, text: d.title })));
  select.value = item.value;
  const sw = switchEl(item.include, (on) => { item.include = on; node.classList.toggle("off", !on); }, "Yüklenecekler arasına al");
  select.addEventListener("change", () => {
    item.value = select.value;
    item.status = null;
    item.include = !!item.value;
    sw.querySelector("input").checked = item.include;
    node.classList.toggle("off", !item.include);
    updateInfo();
  });
  updateInfo();
  node.append(
    h("div", { class: "row-top" }, h("span", { class: "row-label", text: "📎 " + labelText(item.field) }), kindSelect(item)),
    h("div", { class: "row-main" }, select, sw),
    info,
  );
  return node;
}

function switchEl(checked, onChange, label) {
  return h("label", { class: "switch", title: label },
    h("input", { type: "checkbox", checked, "aria-label": label, onchange: (e) => onChange(e.target.checked) }),
    h("span"));
}

function labelText(field) {
  return (field.label || field.name || "(etiketsiz alan)") + (field.required ? " *" : "");
}

function metaFor(item) {
  if (item.status === "saved") return { text: "✓ Son hali hafızaya kaydedildi", cls: "ok" };
  if (item.status === "ok") return { text: "✓ Dolduruldu · sayfada düzenleyip \"Son halini kaydet\"e basabilirsin", cls: "ok" };
  if (item.status === "fail") return { text: "Doldurulamadı, elle gir", cls: "err" };
  if (item.status?.startsWith?.("error:")) return { text: item.status.slice(6), cls: "err" };
  if (item.kind === "profile" && !item.value) return { text: "Profilde yok — Obsidian'da ekleyebilirsin", cls: "warn" };
  if (item.source === "memory") return { text: "🧠 Önceki düzeltmenden hatırlandı", cls: "" };
  return { text: "", cls: "" };
}

function makeEditor(item, onInput, { multiline = false } = {}) {
  const { field } = item;
  let el;
  if (field.type === "combobox") {
    // Özel açılır kutu: liste eksik okunmuş olabilir, serbest yazıya izin ver (doldururken aranır)
    const listId = "dl-" + field.id;
    el = h("input", { class: multiline ? "answer-select" : "value", value: item.value, list: listId, placeholder: "Seç ya da yaz", "aria-label": field.label });
    const datalist = h("datalist", { id: listId }, (field.options || []).map((opt) => h("option", { value: opt })));
    const wrap = h("div", { class: "combo" }, el, datalist);
    el.addEventListener("input", () => { item.value = el.value; item.status = null; onInput(); });
    return wrap;
  } else if (field.options?.length && field.type !== "checkbox") {
    el = h("select", { class: multiline ? "answer-select" : "value" },
      h("option", { value: "", text: "Seçilmedi" }),
      field.options.map((opt) => h("option", { value: opt, text: opt })));
    if (item.value && !field.options.includes(item.value)) el.append(h("option", { value: item.value, text: item.value }));
    el.value = item.value;
  } else if (multiline) {
    el = h("textarea", { rows: 5, value: item.value, "aria-label": field.label });
    const grow = () => { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; };
    el.addEventListener("input", grow);
    requestAnimationFrame(grow);
  } else {
    el = h("input", {
      class: "value", value: item.value, "aria-label": field.label,
      placeholder: field.type === "checkbox" ? (field.options.length > 1 ? "Seçenekleri ; ile ayır" : "evet / hayır") : "Boş",
    });
  }
  el.addEventListener(el.tagName === "SELECT" ? "change" : "input", () => {
    item.value = el.value;
    item.status = null;
    onInput();
  });
  return el;
}

function row(item) {
  const meta = metaFor(item);
  const node = h("div", { class: "row" + (item.include ? "" : " off") });
  const sw = switchEl(item.include, (on) => { item.include = on; node.classList.toggle("off", !on); }, "Doldurulacaklara dahil et");
  const editor = makeEditor(item, () => {
    item.include = item.kind !== "skip" && !!item.value.trim();
    sw.querySelector("input").checked = item.include;
    node.classList.toggle("off", !item.include);
  });
  node.append(
    h("div", { class: "row-top" }, h("span", { class: "row-label", text: labelText(item.field) }), kindSelect(item)),
    h("div", { class: "row-main" }, editor, item.kind === "skip" ? null : sw),
    h("div", { class: `meta ${meta.cls}`, text: meta.text }),
  );
  return node;
}

function answerCard(item) {
  const meta = metaFor(item);
  const counter = h("span", { class: "counter" });
  const updateCounter = () => {
    if (item.field.options?.length) return;
    const words = countWords(item.value);
    const chars = item.value.length;
    const limits = [item.max_words && `${item.max_words} kelime`, item.max_chars && `${item.max_chars} karakter`].filter(Boolean);
    counter.textContent = `${words} kelime · ${chars} karakter` + (limits.length ? `  /  ${limits.join(", ")}` : "");
    counter.classList.toggle("over", Boolean((item.max_words && words > item.max_words) || (item.max_chars && chars > item.max_chars)));
  };
  const includeSwitch = switchEl(item.include, (on) => (item.include = on), "Forma doldur");
  const editor = makeEditor(item, () => {
    item.include = !!item.value.trim();
    includeSwitch.querySelector("input").checked = item.include;
    updateCounter();
  }, { multiline: true });
  updateCounter();

  const hint = h("input", {
    class: "hint", value: item.hint, placeholder: "Yönlendir (ör. T3'ü öne çıkar)",
    oninput: (e) => (item.hint = e.target.value),
    onkeydown: (e) => e.key === "Enter" && writeAnswer(item),
  });
  const writeBtn = h("button", {
    class: "btn tinted small write" + (item.writing ? " loading" : ""), disabled: item.writing,
    text: item.value ? "↻ Yeniden yaz" : "✦ Yaz", onclick: () => writeAnswer(item),
  });

  return h("article", { class: "answer glass" + (item.writing ? " writing" : "") },
    h("div", { class: "row-top" }, h("div", { class: "question", text: labelText(item.field) }), kindSelect(item)),
    item.field.description ? h("div", { class: "secondary small", text: item.field.description }) : null,
    editor,
    h("div", { class: "answer-foot" }, counter, h("span", { class: "refs", text: item.used?.length ? `Referans: ${item.used.length} eski cevap` : "", title: (item.used || []).join("\n") })),
    h("div", { class: "hint-row" }, hint, writeBtn),
    h("div", { class: "toggles" },
      h("label", { class: "toggle" }, includeSwitch, "Forma doldur"),
      item.field.options?.length ? null
        : h("label", { class: "toggle" }, switchEl(item.remember, (on) => (item.remember = on), "Kaydet'e basınca hafızaya ekle"), "Hafızaya ekle")),
    item.field.options?.length ? null : h("div", { class: "save-row" },
      h("button", {
        class: "btn tinted small save-final", title: "Sayfadaki son halini okuyup Obsidian'daki hafızana kaydeder",
        text: "↥ Son halini kaydet", onclick: (e) => saveToMemory([item], e.currentTarget),
      })),
    h("div", { class: `meta ${meta.cls}`, text: meta.text }),
  );
}

// ---------- son haller & hafıza ----------

/** Alanların sayfadaki güncel değerleri (kullanıcı doldurduktan sonra düzenlediyse son hali). */
async function readFromPage(items) {
  if (!state.tabId || !items.length) return {};
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId: state.tabId, allFrames: true },
      func: (ids) => window.__BA?.read?.(ids) || {},
      args: [items.map((i) => i.field.id)],
    });
    return Object.assign({}, ...results.map((r) => r.result || {}));
  } catch {
    return {};  // sekme kapandı / sayfa değişti: paneldeki değer kullanılır
  }
}

/** Sayfadaki son halleri panele alır; kaç cevabın değiştiğini döner. */
async function syncFinals(items) {
  const values = await readFromPage(items);
  let changed = 0;
  for (const item of items) {
    const value = values[item.field.id];
    if (typeof value === "string" && value.trim() && value !== item.value) {
      item.value = value;
      changed++;
    }
  }
  return changed;
}

const toQA = (i) => ({ question: i.field.label, answer: i.value, draft: i.draft || "", category: i.category, save_to_memory: i.remember });

async function saveToMemory(items, button) {
  if (button) setLoading(button, true);
  try {
    const changed = await syncFinals(items);
    const filled = items.filter((i) => i.value.trim());
    if (!filled.length) return toast("Kaydedilecek metin yok.", "err");
    await api("/modules/application/memory", { context: getContext(), items: filled.map(toQA) });
    filled.forEach((i) => (i.status = "saved"));
    toast(changed ? "Sayfadaki son halin hafızaya kaydedildi ✓" : "Hafızaya kaydedildi ✓", "ok");
  } catch (e) {
    toast("Hafızaya kaydedilemedi: " + e.message, "err");
  } finally {
    if (button) setLoading(button, false);
    items.forEach(rerender);
  }
}

async function writeAnswer(item) {
  if (item.writing) return;
  item.writing = true;
  item.status = null;
  rerender(item);
  try {
    const res = await api("/modules/application/answer", {
      question: item.field.label,
      description: item.field.description || "",
      field_type: item.field.type,
      options: item.field.options || [],
      context: getContext(),
      url: state.page.url,
      page_text: state.page.page_text,
      max_chars: item.max_chars,
      max_words: item.max_words,
      hint: item.hint,
      previous: item.value,
    });
    item.value = res.answer;
    item.draft = res.answer;   // AI'ın ilk taslağı: son halle karşılaştırılıp düzeltmelerinden öğrenilir
    item.category = res.category;
    item.used = res.used_answers;
    item.include = !!res.answer;
  } catch (e) {
    item.status = "error:" + e.message;
  } finally {
    item.writing = false;
    rerender(item);
  }
}

// ---------- doldurma & kaydetme ----------

$("fill").addEventListener("click", async () => {
  const button = $("fill");
  const selected = state.items.filter((i) => i.include && i.kind !== "skip" && i.value.trim());
  if (!selected.length) return toast("Doldurulacak seçili alan yok.", "err");
  setLoading(button, true);
  try {
    const items = [];
    for (const i of selected) {
      if (i.kind !== "document") {
        items.push({ id: i.field.id, value: i.value });
        continue;
      }
      try {
        items.push({ id: i.field.id, value: await fetchDocument(i.value) });
      } catch (e) {
        i.status = "error:" + e.message;
      }
    }
    const ok = await fillItems(items);
    learnCorrections();
    for (const item of state.items) {
      if (items.some((x) => x.id === item.field.id)) item.status = ok.has(item.field.id) ? "ok" : "fail";
    }
    state.uploaded = state.items.filter((i) => i.kind === "document" && i.status === "ok")
      .map((i) => state.documents.find((d) => d.path === i.value)?.title).filter(Boolean);
    render();
    if (!ok.size) return toast("Hiçbir alan doldurulamadı. Sayfa değişmiş olabilir; yeniden tara.", "err");
    toast(`${ok.size}/${selected.length} alan dolduruldu. Kontrol et, formu sen gönder.`, "ok");
  } catch (e) {
    toast("Doldurma hatası: " + e.message, "err");
  } finally {
    setLoading(button, false);
  }
});

$("save").addEventListener("click", async () => {
  const button = $("save");
  setLoading(button, true);
  try {
    const current = state.items.filter((i) => i.kind === "answer");
    await syncFinals(current);  // sayfada düzenlediğin son haller kaydedilir, paneldeki taslak değil
    const answers = [...carriedAnswers(), ...current];  // çok sayfalı formda önceki sayfalar da
    const items = answers.filter((i) => i.value.trim()).map(toQA);
    const res = await api("/modules/application/applications", {
      context: getContext(),
      url: state.page.url,
      status: $("ctx-durum").value,
      items,
      documents: state.uploaded || [],
    });
    const extra = res.saved_answers.length ? ` · ${res.saved_answers.length} cevabın son hali hafızada` : "";
    answers.filter((i) => i.remember && i.value.trim()).forEach((i) => (i.status = "saved"));
    render();
    toast(`Kaydedildi: ${res.application_note}${extra}`, "ok");
  } catch (e) {
    toast("Kaydetme hatası: " + e.message, "err");
  } finally {
    setLoading(button, false);
  }
});

// ---------- başlangıç ----------

loadSettings().then(async () => {
  if (!(await checkConnection())) $("settings").classList.remove("hidden");
});
