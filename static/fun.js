// 貓掌與貓咪互動。三種：
// 1. 勾選框（已付、已歸還、TODO）：貓掌打下來把勾拍掉，再按一次就放行。
// 2. 會跳確認框的按鈕（刪除、付款）：貓掌先掃過去，等它落下才跳出確認。
// 3. 空白頁的睡貓：點一下叫醒，再點一下又睡回去。
// 減少動態效果的設定開啟時不做動畫，但邏輯一樣。
(function () {
  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var PAW_SVG =
    '<svg viewBox="0 0 100 100" aria-hidden="true">' +
      '<g stroke="#111" stroke-width="3" stroke-linejoin="round">' +
        '<ellipse cx="22" cy="44" rx="11" ry="14" fill="#ff9bbd" transform="rotate(-20 22 44)"/>' +
        '<ellipse cx="40" cy="26" rx="11" ry="14" fill="#ff9bbd" transform="rotate(-6 40 26)"/>' +
        '<ellipse cx="60" cy="26" rx="11" ry="14" fill="#ff9bbd" transform="rotate(6 60 26)"/>' +
        '<ellipse cx="78" cy="44" rx="11" ry="14" fill="#ff9bbd" transform="rotate(20 78 44)"/>' +
        '<path d="M50 52 C34 52 24 66 26 78 C28 92 42 94 50 90 C58 94 72 92 74 78 C76 66 66 52 50 52 Z" fill="#ff9bbd"/>' +
      '</g>' +
    '</svg>';

  var SWAT_WINDOW = 4000;     // 被拍掉後，這段時間內再勾就放行
  var IMPACT_MS = 330;        // 貓掌落下、碰到勾選框的時間點
  var GUARD_MS = 700;         // 確認框出現前，貓掌先停留的時間
  var swatAt = new WeakMap();
  var pending = new WeakSet();

  function placeAbove(rect, size) {
    var left = rect.left + rect.width / 2 - size / 2;
    var top = rect.top - size + 18;
    if (top < 8) top = rect.bottom + 8; // 靠近畫面上方時改放在下面
    left = Math.max(8, Math.min(left, window.innerWidth - size - 8));
    return { left: left, top: top };
  }

  // 生出一隻貓掌；onImpact 在貓掌落下的瞬間執行
  function spawnPaw(target, message, onImpact) {
    var rect = target.getBoundingClientRect();
    var wrap = document.createElement("div");
    wrap.className = "fun-paw";
    wrap.setAttribute("role", "status");
    wrap.innerHTML = PAW_SVG;

    var bubble = document.createElement("div");
    bubble.className = "fun-bubble";
    bubble.textContent = message;
    wrap.appendChild(bubble);

    var pos = placeAbove(rect, 92);
    wrap.style.left = pos.left + "px";
    wrap.style.top = pos.top + "px";
    document.body.appendChild(wrap);

    if (onImpact) setTimeout(onImpact, IMPACT_MS);

    if (!reduceMotion) {
      document.body.classList.remove("fun-shake");
      void document.body.offsetWidth; // 重新觸發動畫
      document.body.classList.add("fun-shake");
    }
    setTimeout(function () {
      if (wrap.parentNode) wrap.parentNode.removeChild(wrap);
      document.body.classList.remove("fun-shake");
    }, reduceMotion ? 1200 : 1000);
  }

  // ---- 1. 勾選框：拍掉勾，再按一次放行 ----------------------------------

  function swatMessage(t) {
    if (t.getAttribute("data-paw-msg")) return t.getAttribute("data-paw-msg");
    if (t.name === "returned") return "還沒還回來就想勾？再按一次本喵才放你過喵。";
    return "不准打勾！再按一次本喵就讓你過喵。";
  }

  function isSwatTarget(t) {
    return t && t.tagName === "INPUT" && t.type === "checkbox" &&
      (t.name === "paid" || t.name === "returned" || t.hasAttribute("data-paw-msg"));
  }

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!isSwatTarget(t) || !t.checked) return;
    // 程式自己拍掉勾選時觸發的 change 會是「未勾」，這裡不會進來；pending 是防止連點
    if (pending.has(t)) return;
    var last = swatAt.get(t);
    if (last && Date.now() - last < SWAT_WINDOW) {
      swatAt.delete(t); // 第二次按，放行
      return;
    }
    pending.add(t);
    spawnPaw(t, swatMessage(t), function () {
      t.checked = false;
      t.dispatchEvent(new Event("change", { bubbles: true })); // 讓表格或 TODO 照常存檔
      swatAt.set(t, Date.now());
      pending.delete(t);
    });
  });

  // ---- 2. 會跳確認框的表單：先讓貓掌掃過，再跳確認 --------------------------

  var guardDone = new WeakSet();

  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (!form || !form.getAttribute || !/confirm\(/.test(form.getAttribute("onsubmit") || "")) return;
    if (guardDone.has(form)) { // 我們自己補送出的那一次，放行讓確認框跳出
      guardDone.delete(form);
      return;
    }
    e.preventDefault();
    e.stopImmediatePropagation();
    var msg = form.getAttribute("data-paw-msg") || "喵！這件事本喵要先拍一下再說。";
    var button = form.querySelector("button") || form;
    spawnPaw(button, msg, null);
    setTimeout(function () {
      guardDone.add(form);
      if (typeof form.requestSubmit === "function") form.requestSubmit();
      else form.submit();
    }, GUARD_MS);
  }, true);

  // ---- 3. 睡貓：點一下叫醒，再點一下又睡 --------------------------------------

  function catSay(cat, text) {
    var say = cat.querySelector(".fun-cat-say");
    if (!say) return;
    say.textContent = text;
    say.hidden = false;
    clearTimeout(cat._sayTimer);
    cat._sayTimer = setTimeout(function () { say.hidden = true; }, 1800);
  }

  function toggleCat(cat) {
    var awake = cat.classList.toggle("awake");
    cat.setAttribute("aria-label", awake ? "讓貓咪睡回去" : "叫醒貓咪");
    catSay(cat, awake ? "喵？幹嘛吵本喵睡覺。" : "哼，這次放過你喵。");
  }

  document.addEventListener("click", function (e) {
    var cat = e.target.closest && e.target.closest(".fun-cat");
    if (cat) toggleCat(cat);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var cat = e.target.closest && e.target.closest(".fun-cat");
    if (cat) { e.preventDefault(); toggleCat(cat); }
  });
})();
