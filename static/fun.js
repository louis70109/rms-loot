// 貓掌：有人把「已付」勾起來時，貓掌從上方打下來，並提醒「還沒還錢就想打勾？」。
// 只是提醒，不會擋住勾選。減少動態效果的設定開啟時只顯示文字，不做動畫。
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

  function slap(target) {
    var rect = target.getBoundingClientRect();
    var wrap = document.createElement("div");
    wrap.className = "fun-paw";
    wrap.setAttribute("role", "status");
    wrap.innerHTML = PAW_SVG;

    var bubble = document.createElement("div");
    bubble.className = "fun-bubble";
    bubble.textContent = "還沒還錢就想打勾？喵！";
    wrap.appendChild(bubble);

    var pos = placeAbove(rect, 92);
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
    if (t.checked) slap(t);
  });
})();
