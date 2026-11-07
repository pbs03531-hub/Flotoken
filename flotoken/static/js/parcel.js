/* Parcel / kitchen screen. Kitchen staff cook and mark ready; cashiers also take payment, edit, cancel and hand over. */
(() => {
  const A = window.APP, role = A.user.role, isCashier = role === 'owner' || role === 'cashier';
  let orders = [], summary = {}, filter = 'all', first = true, sig = '', known = new Set();
  const open = new Set();
  let sound = true;
  try { sound = localStorage.getItem('pd_sound') !== '0'; } catch (e) { /* ignore */ }

  const FILTERS = [['all', 'All'], ['placed', 'Waiting'], ['preparing', 'Cooking'], ['ready', 'Ready']];
  const STATUS = { placed: ['Waiting', 'warn'], preparing: ['Cooking', 'info'], ready: ['Ready', 'ok'] };

  function payPill(o) {
    if (o.refund > 0) return `<span class="pill warn">Refund ${money(o.refund)} owed</span>`;
    if (o.due > 0 && o.paid === 0) return `<span class="pill bad">Unpaid ${money(o.due)}</span>`;
    if (o.due > 0) return `<span class="pill warn">${money(o.due)} extra due</span>`;
    const ms = [...new Set(o.payments.filter((p) => p.amount > 0).map((p) => p.method))];
    return `<span class="pill ok">Paid · ${ms.join(' + ')}</span>`;
  }

  function card(o) {
    const [stLabel, stKind] = STATUS[o.status];
    const age = minutesAgo(o.created_at), target = (o.eta_min || 20) + 5;
    const late = ['placed', 'preparing'].includes(o.status) && age > target && o.due === 0;
    let b = '';
    if (isCashier && o.due > 0) b += `<button class="btn primary grow" data-act="pay" data-m="Cash" data-id="${o.id}">Cash received ${money(o.due)}</button><button class="btn grow" data-act="pay" data-m="UPI" data-id="${o.id}">UPI received</button>`;
    if (isCashier && o.refund > 0) b += `<button class="btn primary grow" data-act="refund" data-id="${o.id}">Mark refunded ${money(o.refund)}</button>`;
    if (o.status === 'placed') b += `<button class="btn grow" data-act="status" data-to="preparing" data-id="${o.id}" ${o.due > 0 ? 'disabled' : ''}>Start cooking</button>`;
    if (o.status === 'preparing') b += `<button class="btn ok grow" data-act="status" data-to="ready" data-id="${o.id}">Mark ready</button>`;
    if (o.status === 'ready') {
      if (o.phone) b += `<a class="btn grow" data-act="wa" data-id="${o.id}" href="${esc(whatsappUrl(o, A.whatsapp))}" target="_blank" rel="noopener">WhatsApp customer</a>`;
      if (isCashier) b += `<button class="btn ok grow" data-act="status" data-to="collected" data-id="${o.id}" ${o.due > 0 ? 'disabled' : ''}>Handed over</button>`;
    }
    let more = '';
    if (isCashier) more = `<div class="btns" style="margin-top:8px"><button class="btn sm" data-act="edit" data-id="${o.id}">${open.has(o.id) ? 'Close edit' : 'Edit order'}</button><button class="btn sm danger" data-act="cancel" data-id="${o.id}">Cancel order</button></div>`;
    const hint = o.due > 0 && o.status !== 'preparing' ? `<p class="small" style="color:var(--warn);margin-top:8px">${isCashier ? 'Collect payment first. This order cannot be cooked or handed over until paid.' : 'Waiting for the cashier to confirm payment.'}</p>` : '';
    return `<article class="ord ${o.status}">
      <div class="spread"><span class="tok">${o.tok}</span>
        <div class="grow"><div class="row wrap" style="gap:6px"><span class="pill ${o.source === 'app' ? 'info' : ''}">${o.source === 'app' ? 'Phone order' : 'Counter'}</span><span class="pill ${late ? 'bad' : ''}">${age} min${late ? ' · late' : ''}</span></div>
          <div class="muted small" style="margin-top:3px">${o.customer_name ? esc(o.customer_name) + ' · ' : ''}${hm(o.created_at)}${o.source === 'app' && o.eta_min ? ' · promised by ' + hm(o.created_at + o.eta_min * 60000) : ''}</div></div>
        <b class="num" style="font-size:20px">${money(o.total)}</b></div>
      <ul class="lines">${o.items.map((i) => `<li><span class="mono muted">${i.qty} ×</span><span>${esc(i.name)}</span></li>`).join('')}</ul>
      ${o.note ? `<div class="note-box"><b>Note:</b> ${esc(o.note)}</div>` : ''}
      <div class="row wrap" style="gap:6px;margin-bottom:10px">${payPill(o)}<span class="pill ${stKind}">${stLabel}</span></div>
      <div class="btns">${b}</div>${hint}${more}${open.has(o.id) ? editPanel(o) : ''}</article>`;
  }

  function editPanel(o) {
    return `<div class="edit">${o.items.map((i) => `<div class="row" style="padding:4px 0"><span class="grow">${esc(i.name)}</span><div class="stepper"><button data-act="qty" data-d="-1" data-item="${i.id}" data-id="${o.id}" aria-label="Remove one">−</button><span class="q">${i.qty}</span><button data-act="qty" data-d="1" data-item="${i.id}" data-id="${o.id}" aria-label="Add one">+</button></div></div>`).join('')}
      <div class="row" style="margin-top:8px"><select data-add-for="${o.id}" aria-label="Add item"></select><button class="btn sm" data-act="add" data-id="${o.id}">Add</button></div>
      <ul class="loglist" style="margin-top:10px">${o.log.slice(-4).map((l) => `<li><time>${hm(l.at)}</time><span>${esc(l.text)}${l.user ? ' <span class="muted">(' + esc(l.user) + ')</span>' : ''}</span></li>`).join('')}</ul></div>`;
  }

  function fillAddSelects(menuCats) {
    $$('select[data-add-for]').forEach((sel) => {
      sel.innerHTML = menuCats.map((c) => `<optgroup label="${esc(c.name)}">${c.items.filter((i) => i.available).map((i) => `<option value="${i.id}">${esc(i.name)} – ${money(i.price)}</option>`).join('')}</optgroup>`).join('');
    });
  }
  let menuCats = [];

  function draw() {
    const counts = { all: orders.length };
    orders.forEach((o) => { counts[o.status] = (counts[o.status] || 0) + 1; });
    $('#filters').innerHTML = FILTERS.map(([k, n]) => `<button role="tab" data-filter="${k}" aria-selected="${filter === k}">${n} ${counts[k] || 0}</button>`).join('');
    const list = orders.filter((o) => filter === 'all' || o.status === filter);
    $('#list').innerHTML = list.length ? list.map(card).join('') : '<div class="empty" style="grid-column:1/-1"><b>Nothing here</b>New orders appear the moment they are placed.</div>';
    fillAddSelects(menuCats);
    $('#summary').textContent = `${summary.orders || 0} orders today · ${summary.pending || 0} in progress` + (isCashier ? ` · UPI ${money(summary.upi || 0)} · Cash ${money(summary.cash || 0)}` : '');
  }

  async function load() {
    const d = await api('/api/orders');
    const ids = new Set(d.orders.map((o) => o.id));
    if (!first && sound && d.orders.some((o) => !known.has(o.id))) beep(2, 760);
    known = ids; first = false;
    orders = d.orders; summary = d.summary;
    const s = JSON.stringify([orders, summary, filter, [...open], Math.floor(Date.now() / 60000)]);
    const typing = document.activeElement && ['SELECT', 'INPUT'].includes(document.activeElement.tagName);
    if (s !== sig && !typing) { sig = s; draw(); }
  }
  const redraw = () => { sig = ''; return load(); };

  async function loadMenuCats() { try { menuCats = (await api('/api/menu')).categories; sig = ''; } catch (e) { /* ignore */ } }

  /* ---------------- sold-out manager ---------------- */
  async function soldOutDialog() {
    await loadMenuCats();
    const m = modal('');
    const paint = () => {
      m.el.innerHTML = `<h2>Sold-out items</h2><p class="muted small mb">Marked items disappear from the customer page and the counter immediately.</p>` +
        menuCats.map((c) => `<h3 style="margin-top:10px">${esc(c.name)}</h3>` + c.items.map((i) => `<div class="menu-row ${i.available ? '' : 'soldout'}"><div class="grow name">${dietIcon(i.diet)}${esc(i.name)}</div><button class="btn sm ${i.available ? '' : 'primary'}" data-av="${i.id}" data-to="${i.available ? 0 : 1}">${i.available ? 'Mark sold out' : 'Back on'}</button></div>`).join('')).join('') +
        '<div class="btns mt"><button class="btn grow" data-x>Done</button></div>';
    };
    paint();
    m.el.addEventListener('click', async (e) => {
      if (e.target.closest('[data-x]')) { m.close(); return; }
      const b = e.target.closest('[data-av]'); if (!b) return;
      await attempt(async () => { await api(`/api/menu/${b.dataset.av}/available`, 'POST', { available: b.dataset.to === '1' }); await loadMenuCats(); paint(); });
    });
  }

  /* ---------------- events ---------------- */
  $('#list').addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const id = +b.dataset.id, act = b.dataset.act, o = orders.find((x) => x.id === id);
    if (act === 'wa') { api(`/api/orders/${id}/notified`, 'POST').catch(() => {}); return; }   // let the link open
    if (act === 'edit') { open.has(id) ? open.delete(id) : open.add(id); sig = ''; draw(); return; }
    attempt(async () => {
      if (act === 'pay') { await api(`/api/orders/${id}/pay`, 'POST', { method: b.dataset.m }); toast(`${b.dataset.m} recorded for token ${o.tok}`, 'ok'); }
      else if (act === 'refund') { await api(`/api/orders/${id}/refund`, 'POST'); toast('Refund recorded', 'ok'); }
      else if (act === 'status') {
        await api(`/api/orders/${id}/status`, 'POST', { status: b.dataset.to });
        if (b.dataset.to === 'ready') toast(`Token ${o.tok} is on the board` + (o.phone ? '. Tap WhatsApp to tell the customer.' : ''), 'ok');
      }
      else if (act === 'add') { const sel = $(`select[data-add-for="${id}"]`); await api(`/api/orders/${id}/items`, 'POST', { item_id: +sel.value, delta: 1 }); }
      else if (act === 'qty') {
        const body = { item_id: +b.dataset.item, delta: +b.dataset.d };
        try { await api(`/api/orders/${id}/items`, 'POST', body); }
        catch (err) {
          if (err.data && err.data.needsApproval && await confirmBox('Cooking has started. Remove this item?', 'Remove item', true)) await api(`/api/orders/${id}/items`, 'POST', { ...body, approved: true });
          else throw err;
        }
      }
      else if (act === 'cancel') {
        const reason = await askText(`Cancel token ${o.tok}?`, 'Reason (optional)', 'Cancel order');
        if (reason === null) return;
        await api(`/api/orders/${id}/cancel`, 'POST', { reason });
        toast(`Token ${o.tok} cancelled` + (o.paid > 0 ? '. Refund the customer.' : ''), 'ok');
      }
      await redraw();
    });
  });
  $('#filters').addEventListener('click', (e) => { const b = e.target.closest('[data-filter]'); if (b) { filter = b.dataset.filter; sig = ''; draw(); } });
  $('#soldout').addEventListener('click', soldOutDialog);
  const soundBtn = $('#sound');
  const paintSound = () => { soundBtn.textContent = sound ? 'Sound on' : 'Sound off'; soundBtn.setAttribute('aria-pressed', sound); };
  soundBtn.addEventListener('click', () => { sound = !sound; try { localStorage.setItem('pd_sound', sound ? '1' : '0'); } catch (e) { /* ignore */ } paintSound(); if (sound) beep(1); });
  paintSound();

  loadMenuCats();
  poll(load, 2500);
})();
