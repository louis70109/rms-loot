// TODO 頁面：項目只存在這個瀏覽器的 localStorage，不寫入伺服器。
// 攻略目錄的順序：即時抓取 → 上次的快取 → 內建快照（static/guide-index-snapshot.json）。
(function () {
  var root = document.querySelector("[data-todo-root]");
  if (!root) return;

  var KEY = "maple-royals-todo-v3";
  var INDEX_CACHE_KEY = "maple-royals-guide-index-v1";
  var GUIDE = root.getAttribute("data-guide-url") || "https://rms-data.fly.dev/";
  var INDEX_URL = GUIDE + "index.json";
  var SNAPSHOT_URL = root.getAttribute("data-snapshot-url");
  var GROUPS = ["level", "quest"];
  var openIds = {}; // 只在目前頁面記住哪些項目展開

  // indexStatus: loading | live | cached | snapshot | unavailable
  var guideIndex = null;
  var indexStatus = "loading";
  var snapshotDate = "";

  function emptyData() { return { level: [], quest: [] }; }

  function load() {
    try {
      var raw = localStorage.getItem(KEY);
      var data = raw ? JSON.parse(raw) : null;
      if (data && GROUPS.every(function (g) { return Array.isArray(data[g]); })) {
        GROUPS.forEach(function (g) {
          data[g].forEach(function (i) {
            i.note = i.note || "";
            i.link = i.link || "";
            i.slug = i.slug || "";
          });
        });
        return data;
      }
    } catch (e) {}
    return emptyData();
  }

  function save(data) {
    try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) {}
  }

  function isValidIndex(list) {
    return Array.isArray(list) && list.every(function (x) {
      return x && typeof x.slug === "string" && typeof x.title === "string" && typeof x.cat === "string";
    });
  }

  function fetchJson(url, timeoutMs) {
    var ctrl = typeof AbortController !== "undefined" ? new AbortController() : null;
    var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, timeoutMs) : null;
    return fetch(url, { cache: "no-store", signal: ctrl ? ctrl.signal : undefined })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .finally(function () { if (timer) clearTimeout(timer); });
  }

  function loadIndex() {
    fetchJson(INDEX_URL, 10000)
      .then(function (list) {
        if (!isValidIndex(list)) throw new Error("bad index");
        guideIndex = list;
        indexStatus = "live";
        try { localStorage.setItem(INDEX_CACHE_KEY, JSON.stringify(list)); } catch (e) {}
      })
      .catch(function () {
        var cached = null;
        try { cached = JSON.parse(localStorage.getItem(INDEX_CACHE_KEY) || "null"); } catch (e) {}
        if (isValidIndex(cached)) {
          guideIndex = cached;
          indexStatus = "cached";
          return;
        }
        if (!SNAPSHOT_URL) { indexStatus = "unavailable"; return; }
        return fetchJson(SNAPSHOT_URL, 5000).then(function (snap) {
          if (!snap || !isValidIndex(snap.entries)) throw new Error("bad snapshot");
          guideIndex = snap.entries;
          snapshotDate = snap.date || "";
          indexStatus = "snapshot";
        }).catch(function () {
          guideIndex = null;
          indexStatus = "unavailable";
        });
      })
      .then(function () { render(); });
  }

  // 只接受 http / https 連結，避免 javascript: 之類的網址
  function safeLink(url) {
    return /^https?:\/\/\S+$/i.test(url || "") ? url : "";
  }

  // 有選攻略頁就用 slug 組出連結，否則用手動填的連結
  function targetHref(item) {
    if (item.slug) return GUIDE + "#" + encodeURIComponent(item.slug);
    return safeLink(item.link);
  }

  function findTitle(slug) {
    if (!guideIndex) return null;
    var hit = guideIndex.filter(function (x) { return x.slug === slug; })[0];
    return hit ? hit.title : null;
  }

  var data = load();

  function makeId() {
    return Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function render() {
    GROUPS.forEach(function (group) {
      var sec = root.querySelector('[data-group="' + group + '"]');
      var items = data[group];
      var list = sec.querySelector("[data-list]");
      var doneCount = items.filter(function (i) { return i.done; }).length;
      sec.querySelector("[data-count]").textContent = doneCount + " / " + items.length + " 完成";
      list.innerHTML = "";
      if (items.length === 0) {
        list.appendChild(el("li", "empty", "還沒有項目"));
        return;
      }
      items.forEach(function (item) { list.appendChild(renderItem(group, item)); });
    });
  }

  function renderItem(group, item) {
    var li = el("li", "item" + (item.done ? " done" : ""));
    var row = el("div", "row");

    var cb = el("input");
    cb.type = "checkbox";
    cb.checked = !!item.done;
    cb.id = "todo-cb-" + item.id;
    cb.addEventListener("change", function () {
      item.done = cb.checked;
      save(data);
      render();
    });

    var label = el("label", null, item.text);
    label.htmlFor = cb.id;

    row.appendChild(cb);
    row.appendChild(label);

    var href = targetHref(item);
    if (href) {
      var a = el("a", "ext", "↗");
      a.href = href;
      a.target = "_blank";
      a.rel = "noopener";
      a.title = "攻略連結";
      row.appendChild(a);
    }

    var isOpen = !!openIds[item.id];
    var toggle = el("button", "icon", isOpen ? "▴" : "▾");
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(isOpen));
    toggle.setAttribute("aria-label", "備註與連結");
    toggle.addEventListener("click", function () {
      openIds[item.id] = !openIds[item.id];
      render();
    });
    row.appendChild(toggle);

    var del = el("button", "icon", "×");
    del.type = "button";
    del.setAttribute("aria-label", "刪除");
    del.addEventListener("click", function () {
      data[group] = data[group].filter(function (i) { return i.id !== item.id; });
      delete openIds[item.id];
      save(data);
      render();
    });
    row.appendChild(del);

    li.appendChild(row);
    if (isOpen) li.appendChild(renderDetail(item));
    return li;
  }

  function renderDetail(item) {
    var detail = el("div", "detail");

    var noteLabel = el("label", null, "備註");
    var note = el("textarea");
    note.value = item.note;
    note.placeholder = "例如：需要的道具、進度、要找的 NPC";
    note.addEventListener("input", function () {
      item.note = note.value;
      save(data);
    });
    noteLabel.appendChild(note);
    detail.appendChild(noteLabel);

    if (indexStatus === "loading") {
      detail.appendChild(el("p", "hint", "正在載入攻略頁目錄…"));
    } else if (indexStatus === "unavailable") {
      detail.appendChild(el("p", "hint", "攻略頁目錄暫時無法載入，可以先用下面的手動連結。"));
    } else {
      var titleText = "攻略頁";
      if (indexStatus === "snapshot") titleText += "（內建目錄" + (snapshotDate ? "，更新於 " + snapshotDate : "") + "）";
      if (indexStatus === "cached") titleText += "（快取的目錄）";
      var pickLabel = el("label", null, titleText);
      var select = el("select");
      select.appendChild(el("option", null, "（不連結）"));
      select.firstChild.value = "";

      var byCat = {};
      guideIndex.forEach(function (x) { (byCat[x.cat] = byCat[x.cat] || []).push(x); });
      Object.keys(byCat).forEach(function (cat) {
        var og = el("optgroup");
        og.label = cat;
        byCat[cat].forEach(function (x) {
          var opt = el("option", null, x.title);
          opt.value = x.slug;
          og.appendChild(opt);
        });
        select.appendChild(og);
      });

      // 存的 slug 在目錄裡找不到：顯示「頁面已不存在」，不讓頁面壞掉
      if (item.slug && findTitle(item.slug) === null) {
        var missing = el("option", null, "頁面已不存在（" + item.slug + "）");
        missing.value = item.slug;
        select.appendChild(missing);
      }
      select.value = item.slug;
      select.addEventListener("change", function () {
        item.slug = select.value;
        save(data);
        render();
      });
      pickLabel.appendChild(select);
      detail.appendChild(pickLabel);
    }

    var linkLabel = el("label", null, "手動連結（https://…，選了攻略頁就不會用到）");
    var linkInput = el("input");
    linkInput.type = "url";
    linkInput.value = item.link;
    linkInput.placeholder = "https://rms-data.fly.dev/#…";
    var warn = el("p", "warn");
    warn.setAttribute("role", "status");
    linkInput.addEventListener("change", function () {
      var v = linkInput.value.trim();
      if (v && !safeLink(v)) {
        warn.textContent = "連結需要以 http:// 或 https:// 開頭，沒有儲存。";
        linkInput.value = item.link;
        return;
      }
      item.link = v;
      save(data);
      render();
    });
    linkLabel.appendChild(linkInput);
    detail.appendChild(linkLabel);
    detail.appendChild(warn);
    return detail;
  }

  GROUPS.forEach(function (group) {
    var sec = root.querySelector('[data-group="' + group + '"]');
    sec.querySelector("[data-form]").addEventListener("submit", function (e) {
      e.preventDefault();
      var input = this.elements.text;
      var text = input.value.trim();
      if (!text) return;
      data[group].push({ id: makeId(), text: text, done: false, note: "", link: "", slug: "" });
      input.value = "";
      save(data);
      render();
      input.focus();
    });
    sec.querySelector("[data-clear]").addEventListener("click", function () {
      data[group].filter(function (i) { return i.done; }).forEach(function (i) { delete openIds[i.id]; });
      data[group] = data[group].filter(function (i) { return !i.done; });
      save(data);
      render();
    });
  });

  render();
  loadIndex();
})();
