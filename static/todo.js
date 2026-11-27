// TODO 頁面：資料存在伺服器的資料庫，依登入者分開（見 todo.py 與 docs/adr/0010-todo-in-database.md）。
// 攻略目錄的順序：即時抓取 → 上次的快取 → 內建快照（static/guide-index-snapshot.json）。
(function () {
  var root = document.querySelector("[data-todo-root]");
  if (!root) return;

  var API = root.getAttribute("data-api-url") || "/api/todos";
  var LEGACY_KEY = "maple-royals-todo-v3";  // 舊版存在瀏覽器裡的資料，第一次開頁時搬進資料庫
  var INDEX_CACHE_KEY = "maple-royals-guide-index-v1";
  var GUIDE = root.getAttribute("data-guide-url") || "https://rms-data.fly.dev/";
  var INDEX_URL = GUIDE + "index.json";
  var SNAPSHOT_URL = root.getAttribute("data-snapshot-url");
  var GROUPS = ["level", "quest"];
  var openIds = {};   // 只在目前頁面記住哪些項目展開
  var statusEl = root.querySelector("[data-status]");

  // indexStatus: loading | live | cached | snapshot | unavailable
  var guideIndex = null;
  var indexStatus = "loading";
  var snapshotDate = "";

  var data = { level: [], quest: [] };
  var loaded = false;

  // ---- 狀態列與 API ---------------------------------------------------------

  function say(msg, isError) {
    if (!statusEl) return;
    statusEl.textContent = msg || "";
    statusEl.className = "todo-status" + (isError ? " error" : "");
  }

  function api(method, url, body) {
    var opts = { method: method, credentials: "same-origin", headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    return fetch(url, opts).then(function (r) {
      return r.json().catch(function () { return null; }).then(function (j) {
        if (!r.ok) {
          var err = new Error((j && j.error) || ("HTTP " + r.status));
          err.status = r.status;
          throw err;
        }
        return j;
      });
    });
  }

  function failed(e) {
    if (e && e.status === 401) say("滾去登入 Discord 再來玩 TODO 啦。", true);
    else say("儲存失敗：" + (e && e.message ? e.message : "未知錯誤") + "。畫面已還原。", true);
  }

  // ---- 載入與舊資料搬移 ----------------------------------------------------

  function legacyItems() {
    try {
      var raw = localStorage.getItem(LEGACY_KEY);
      var old = raw ? JSON.parse(raw) : null;
      if (old && GROUPS.every(function (g) { return Array.isArray(old[g]); })) {
        var total = old.level.length + old.quest.length;
        if (total > 0) return old;
      }
    } catch (e) {}
    return null;
  }

  function fetchList() {
    return api("GET", API).then(function (list) {
      data = { level: list.level || [], quest: list.quest || [] };
      loaded = true;
    });
  }

  function load() {
    say("正在載入…");
    fetchList().then(function () {
      var old = legacyItems();
      if (old && data.level.length === 0 && data.quest.length === 0) {
        return api("POST", API + "/import", old).then(function () {
          try { localStorage.removeItem(LEGACY_KEY); } catch (e) {}
          say("已把這個瀏覽器的舊清單搬進資料庫。");
          return fetchList();
        });
      }
    }).then(function () {
      say("");
      render();
    }).catch(function (e) {
      failed(e);
      render();
    });
  }

  // ---- 攻略目錄 -------------------------------------------------------------

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

  // ---- 轉換與工具 -----------------------------------------------------------

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

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function findItem(group, id) {
    return data[group].filter(function (i) { return i.id === id; })[0];
  }

  // 先改畫面，再送出；失敗就還原
  function patch(group, item, fields) {
    var before = {};
    Object.keys(fields).forEach(function (k) { before[k] = item[k]; Object.assign(item, { [k]: fields[k] }); });
    render();
    return api("PATCH", API + "/" + item.id, fields)
      .then(function (saved) {
        Object.keys(saved).forEach(function (k) { item[k] = saved[k]; });
        say("");
        render();
      })
      .catch(function (e) {
        Object.keys(before).forEach(function (k) { item[k] = before[k]; });
        failed(e);
        render();
      });
  }

  // ---- 畫面 -----------------------------------------------------------------

  function render() {
    GROUPS.forEach(function (group) {
      var sec = root.querySelector('[data-group="' + group + '"]');
      var items = data[group];
      var list = sec.querySelector("[data-list]");
      var doneCount = items.filter(function (i) { return i.done; }).length;
      sec.querySelector("[data-count]").textContent = loaded
        ? doneCount + " / " + items.length + " 完成"
        : "";
      list.innerHTML = "";
      if (!loaded) return;
      if (items.length === 0) {
        list.appendChild(el("li", "empty", "空空如也，快打點字啊。"));
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
      patch(group, item, { done: cb.checked });
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
      api("DELETE", API + "/" + item.id).then(function () {
        data[group] = data[group].filter(function (i) { return i.id !== item.id; });
        delete openIds[item.id];
        say("");
        render();
      }).catch(failed);
    });
    row.appendChild(del);

    li.appendChild(row);
    if (isOpen) li.appendChild(renderDetail(group, item));
    return li;
  }

  function renderDetail(group, item) {
    var detail = el("div", "detail");

    var noteLabel = el("label", null, "備註");
    var note = el("textarea");
    note.value = item.note;
    note.placeholder = "例如：需要的道具、進度、要找的 NPC";
    // 備註在離開欄位時才儲存，避免每打一個字就送一次
    note.addEventListener("change", function () {
      if (note.value !== item.note) patch(group, item, { note: note.value });
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
      var none = el("option", null, "（不連結）");
      none.value = "";
      select.appendChild(none);

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
        patch(group, item, { slug: select.value });
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
      warn.textContent = "";
      if (v !== item.link) patch(group, item, { link: v });
    });
    linkLabel.appendChild(linkInput);
    detail.appendChild(linkLabel);
    detail.appendChild(warn);
    return detail;
  }

  // ---- 事件 -----------------------------------------------------------------

  GROUPS.forEach(function (group) {
    var sec = root.querySelector('[data-group="' + group + '"]');
    sec.querySelector("[data-form]").addEventListener("submit", function (e) {
      e.preventDefault();
      var input = this.elements.text;
      var text = input.value.trim();
      if (!text) return;
      api("POST", API, { group: group, text: text }).then(function (item) {
        data[group].push(item);
        input.value = "";
        say("");
        render();
        input.focus();
      }).catch(failed);
    });
    sec.querySelector("[data-clear]").addEventListener("click", function () {
      api("POST", API + "/clear-done", { group: group }).then(function () {
        data[group].filter(function (i) { return i.done; }).forEach(function (i) { delete openIds[i.id]; });
        data[group] = data[group].filter(function (i) { return !i.done; });
        say("");
        render();
      }).catch(failed);
    });
  });

  render();
  load();
  loadIndex();
})();
