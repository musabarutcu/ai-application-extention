// Sayfadaki canlı işler (extractor.js ve filler.js'ten sonra yüklenir):
//  1) Değer takibi: kullanıcının cevap kutularında yaptığı düzenlemeleri yan panele iletir.
//  2) Sayfa değişimi: çok adımlı formlarda (İleri / Geri) yeni alanlar belirince paneli uyarır.
//  3) Sayfa içi butonlar: cevap kutularının yanında "✦ Yaz" butonu.
(() => {
  const BA = (window.__BA = window.__BA || {});
  if (BA.live) return;
  BA.live = true;
  const { isShown } = BA.util;
  const send = (message) => {
    try {
      chrome.runtime.sendMessage(message).catch(() => {});  // panel kapalıysa sessizce geç
    } catch {}
  };
  const CONTROLS = 'input:not([type="hidden"]), textarea, select, [role="combobox"], [role="radiogroup"], [role="listbox"]';
  const visibleControls = () => [...document.querySelectorAll(CONTROLS)].filter(isShown);

  // Kendi işlemlerimiz (tarama sırasında açılıp kapanan menüler, doldurma) sayfa değişimi sayılmasın
  BA.busy = 0;
  let seen = new WeakSet();
  const refreshSeen = () => (seen = new WeakSet(visibleControls()));
  for (const name of ["extract", "fill"]) {
    const original = BA[name];
    BA[name] = async (...args) => {
      BA.busy++;
      try {
        return await original(...args);
      } finally {
        setTimeout(() => {
          BA.busy--;
          refreshSeen();
        }, 400);
      }
    };
  }

  // ---------- 1) değer takibi ----------
  const timers = new Map();
  BA.watch = (ids) => {
    for (const id of ids) {
      const entry = BA.registry?.get(id);
      if (!entry || entry.watched) continue;
      entry.watched = true;
      const elements = entry.el ? [entry.el] : (entry.options || []).map((o) => o.el);
      const report = () => {
        clearTimeout(timers.get(id));
        timers.set(id, setTimeout(() => {
          const value = BA.read([id])[id];
          if (value !== undefined) send({ type: "ba:value", id, value });
        }, 400));
      };
      for (const el of elements) {
        el.addEventListener("input", report);
        el.addEventListener("change", report);
      }
    }
  };

  // ---------- 2) sayfa değişimi ----------
  let changeTimer;
  BA.observe = () => {
    refreshSeen();
    if (BA.observer) return;
    BA.observer = new MutationObserver(() => {
      clearTimeout(changeTimer);
      changeTimer = setTimeout(() => {
        if (BA.busy) return;
        const fresh = visibleControls().some((el) => !seen.has(el));
        const gone = [...(BA.registry?.values() || [])].some((e) => e.el && !e.el.isConnected);
        if (fresh || gone) {
          refreshSeen();
          send({ type: "ba:changed", url: location.href });
        }
      }, 900);
    });
    BA.observer.observe(document.body, { childList: true, subtree: true });
  };

  // ---------- 3) sayfa içi "✦ Yaz" butonları ----------
  let overlay = null;
  const buttons = new Map(); // id -> { btn, el }

  function ensureOverlay() {
    if (overlay?.host.isConnected) return overlay;
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;inset:0;pointer-events:none;z-index:2147483646;";
    const root = host.attachShadow({ mode: "closed" });
    root.innerHTML = `<style>
      button{position:fixed;pointer-events:auto;border:0;border-radius:999px;padding:5px 11px;cursor:pointer;
        font:600 12px/1.2 -apple-system,"Segoe UI Variable","Segoe UI",system-ui,sans-serif;color:#fff;
        background:#007AFF;box-shadow:0 2px 10px rgba(0,122,255,.35);transition:transform .12s,opacity .15s}
      button:hover{transform:translateY(-1px)} button:active{transform:scale(.96)}
      button[data-state=busy]{background:#5AC8FA;cursor:progress} button[data-state=done]{background:#34C759}
      button[data-state=error]{background:#FF3B30}
    </style>`;
    document.documentElement.append(host);
    overlay = { host, root };
    const place = () => {
      for (const { btn, el } of buttons.values()) {
        const r = el.getBoundingClientRect();
        const visible = el.isConnected && isShown(el) && r.bottom > 0 && r.top < innerHeight;
        btn.style.display = visible ? "" : "none";
        if (visible) {
          btn.style.top = Math.max(4, r.top - 14) + "px";
          // kutunun sağ üst köşesi; buton genişliği yazıya göre değişir ("✦ Yaz" / "↻ Yeniden yaz")
          btn.style.left = Math.max(4, Math.min(innerWidth - btn.offsetWidth - 8, r.right - btn.offsetWidth - 6)) + "px";
        }
      }
    };
    addEventListener("scroll", place, true);
    addEventListener("resize", place);
    overlay.place = place;
    setInterval(place, 800);  // düzen değişimleri (açılır bölümler vb.)
    return overlay;
  }

  const LABELS = { idle: "✦ Yaz", busy: "Yazılıyor…", done: "✓ Yazıldı", error: "Hata — tekrar" };

  BA.decorate = (ids) => {
    const { root, place } = ensureOverlay();
    for (const { btn } of buttons.values()) btn.remove();
    buttons.clear();
    for (const id of ids) {
      const el = BA.registry?.get(id)?.el;
      if (!el) continue;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = LABELS.idle;
      btn.title = "Başvuru Asistanı: bu soruya taslak yaz ve kutuya doldur";
      btn.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        if (btn.dataset.state === "busy") return;
        BA.setInline(id, "busy");
        send({ type: "ba:write", id });
      });
      root.append(btn);
      buttons.set(id, { btn, el });
    }
    place();
  };

  BA.setInline = (id, state) => {
    const item = buttons.get(id);
    if (!item) return;
    item.btn.dataset.state = state;
    item.btn.textContent = state === "done" ? LABELS.done : LABELS[state] || LABELS.idle;
    if (state === "done") setTimeout(() => {
      if (item.btn.dataset.state === "done") {
        item.btn.dataset.state = "idle";
        item.btn.textContent = "↻ Yeniden yaz";
      }
    }, 2500);
  };
})();
