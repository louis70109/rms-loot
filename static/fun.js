// 貓掌：有人把「已付」勾起來時，貓掌從上方打下來，把勾拍掉。
// 再按一次就算數，所以貓只會擋一下，不會把「已付」整個擋死。
// 減少動態效果的設定開啟時不做動畫，但拍掉的邏輯一樣。
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

  function placeAbove(rect, size) {
    var left = rect.left + rect.width / 2 - size / 2;
    var top = rect.top - size + 18;
    if (top < 8) top = rect.bottom + 8; // 靠近畫面上方時改放在下面
    left = Math.max(8, Math.min(left, window.innerWidth - size - 8));
    return { left: left, top: top };
  }

  // 剛被拍掉的勾選框：短時間內再勾就放行
  var SWAT_WINDOW = 4000;
  var IMPACT_MS = 330;          // 貓掌落下、碰到勾選框的時間點
  var swatAt = new WeakMap();   // 勾選框 -> 上次被拍掉的時間
  var pending = new WeakSet();  // 正在等待拍掉的勾選框

  function slap(target) {
    var rect = target.getBoundingClientRect();
    var wrap = document.createElement("div");
    wrap.className = "fun-paw";
    wrap.setAttribute("role", "status");
    wrap.innerHTML = PAW_SVG;

    var bubble = document.createElement("div");
    bubble.className = "fun-bubble";
    bubble.textContent = "不准打勾！再按一次本喵就讓你過喵。";
    wrap.appendChild(bubble);

    var pos = placeAbove(rect, 92);
    // 碰到勾選框的瞬間把勾拿掉；change 事件會讓表格照常存檔
    setTimeout(function () {
      target.checked = false;
      target.dispatchEvent(new Event("change", { bubbles: true }));
      swatAt.set(target, Date.now());
      pending.delete(target);
    }, IMPACT_MS);
    wrap.style.left = pos.left + "px";
    wrap.style.top = pos.top + "px";
    document.body.appendChild(wrap);

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

  document.addEventListener("change", function (e) {
    var t = e.target;
    if (!t || t.tagName !== "INPUT" || t.type !== "checkbox" || t.name !== "paid") return;
    if (!t.checked) return;
    // 程式自己拍掉勾選時觸發的 change，直接放過，避免無限循環
    if (pending.has(t)) return;
    var last = swatAt.get(t);
    if (last && Date.now() - last < SWAT_WINDOW) {
      swatAt.delete(t); // 第二次按，放行
      return;
    }
    pending.add(t);
    slap(t);
  });
})();
