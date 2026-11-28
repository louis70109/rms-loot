// 圖片燈箱：點縮圖在頁面內放大，有關閉按鈕；按 Esc、點外面或按關閉都可以關掉。
// 不用 target="_blank"，因為手機的主畫面 App 開新頁後沒有關閉的地方。
(function () {
  var dialog = null;
  var img = null;

  function build() {
    dialog = document.createElement("dialog");
    dialog.className = "lightbox";
    dialog.setAttribute("aria-label", "圖片放大");

    var close = document.createElement("button");
    close.type = "button";
    close.className = "lightbox-close";
    close.textContent = "✕ 關閉";
    close.addEventListener("click", function () { dialog.close(); });

    img = document.createElement("img");
    img.alt = "";

    dialog.appendChild(close);
    dialog.appendChild(img);
    document.body.appendChild(dialog);

    // 點到對話框本身（不是圖片或按鈕）就關閉
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", function () {
      img.removeAttribute("src");
    });
  }

  document.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest("a[data-lightbox]");
    if (!link) return;
    e.preventDefault();
    if (!dialog) build();
    img.src = link.getAttribute("href");
    img.alt = link.getAttribute("data-alt") || "";
    if (typeof dialog.showModal === "function") dialog.showModal();
    else window.open(link.getAttribute("href"), "_blank", "noopener");
  });
})();
