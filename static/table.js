// 表格 Excel 式操作：背景儲存、方向鍵/Enter 移動、Ctrl+D 沿用上一列。
(function () {
  const table = document.querySelector('table.grid');
  const toast = document.getElementById('toast');
  if (!table) return;

  function say(msg, kind) {
    if (!toast) return;
    toast.textContent = msg;
    toast.className = 'toast show ' + (kind || '');
    clearTimeout(say.timer);
    say.timer = setTimeout(() => { toast.className = 'toast'; }, kind === 'error' ? 6000 : 1200);
  }

  // 把這一列（同一個 form）背景送出儲存
  async function save(input) {
    const form = input.form;
    if (!form) return;
    const row = input.closest('tr');
    try {
      const resp = await fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        headers: { Accept: 'application/json' },
      });
      const data = await resp.json().catch(() => ({ ok: false, errors: ['儲存失敗'] }));
      row.classList.toggle('has-error', !data.ok);
      if (data.ok) say('已儲存', 'ok');
      else say((data.errors || ['儲存失敗']).join('；'), 'error');
    } catch (err) {
      row.classList.add('has-error');
      say('網路錯誤，這次沒有儲存', 'error');
    }
  }

  function dataRows() {
    return Array.from(table.tBodies[0].rows).filter((r) => r.querySelector('input[form]'));
  }

  function focusAt(tr, col) {
    const td = tr && tr.cells[col];
    const el = td && td.querySelector('input');
    if (!el) return;
    el.focus();
    if (el.type !== 'checkbox' && el.select) el.select();
  }

  // Ctrl+D：整列換成上一列的內容，然後儲存
  function fillFromAbove(tr) {
    const rows = dataRows();
    const idx = rows.indexOf(tr);
    if (idx <= 0) { say('上面沒有可以沿用的列', 'error'); return; }
    const srcs = Array.from(rows[idx - 1].querySelectorAll('input[name]')).filter((i) => i.form);
    const dsts = Array.from(tr.querySelectorAll('input[name]')).filter((i) => i.form);
    for (const s of srcs) {
      const d = dsts.find((x) => x.name === s.name);
      if (!d) continue;
      if (d.type === 'checkbox') d.checked = s.checked;
      else d.value = s.value;
    }
    refreshStatus(tr);
    if (dsts[0]) save(dsts[0]);
  }

  // 付款狀態標籤：已付 / 未付 / 未完成（缺賣出價或賣出日），跟著格子內容即時更新
  function refreshStatus(tr) {
    const badge = tr.querySelector('.status');
    if (!badge) return;
    const paid = tr.querySelector('input[name="paid"]');
    const isPaid = !!(paid && paid.checked);
    const sale = (tr.querySelector('input[name="sale_price"]') || {}).value || '';
    const sold = (tr.querySelector('input[name="sold_date"]') || {}).value || '';
    let kind, text;
    if (isPaid) { kind = 'paid'; text = '✅ 已付'; }
    else if (!sale.trim() || !sold.trim()) { kind = 'incomplete'; text = '⚠️ 未完成'; }
    else { kind = 'unpaid'; text = '⏳ 未付'; }
    badge.className = 'status ' + kind;
    badge.textContent = text;
    tr.classList.toggle('row-paid', isPaid);
  }

  table.addEventListener('change', (e) => {
    const el = e.target;
    if (el instanceof HTMLInputElement && el.form && el.name) {
      refreshStatus(el.closest('tr'));
      save(el);
    }
  });

  table.addEventListener('keydown', (e) => {
    const el = e.target;
    if (!(el instanceof HTMLInputElement) || !el.form || !el.form.id) return;
    const tr = el.closest('tr');
    const col = el.closest('td').cellIndex;

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'd') {
      e.preventDefault();
      fillFromAbove(tr);
      return;
    }
    if (e.key === 'Enter' || e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const rows = dataRows();
      const idx = rows.indexOf(tr);
      const up = e.key === 'ArrowUp' || (e.key === 'Enter' && e.shiftKey);
      const target = rows[idx + (up ? -1 : 1)];
      if (target) focusAt(target, col);
    }
  });
})();
