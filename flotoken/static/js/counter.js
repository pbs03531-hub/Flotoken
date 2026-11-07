/* Counter screen: staff take walk-in orders and payment. */
(() => {
  let cats = [], cart = {}, cat = 'all', query = '', soldMode = false, sheet = null, last = null, menuSig = '';
  let form = { name: '', phone: '', note: '', customer: null };

  /* ---------------- menu ---------------- */
  function visibleCats() {
    const q = query.trim().toLowerCase();
    return cats.filter((c) => cat === 'all' || String(c.id) === cat)
      .map((c) => ({ ...c, items: c.items.filter((i) => !q || i.name.toLowerCase().includes(q)) })).filter((c) => c.items.length);
  }

  function soldRow(m) {
    return `<div class="menu-row ${m.available ? '' : 'soldout'}"><div class="grow"><div class="name">${dietIcon(m.diet)}${esc(m.name)}</div><div class="muted small price">${money(m.price)}</div></div>
      <button class="btn sm ${m.available ? '' : 'primary'}" data-avail="${m.id}" data-to="${m.available ? 0 : 1}">${m.available ? 'Mark sold out' : 'Back on menu'}</button></div>`;
  }

  function drawMenu() {
    $('#chips').innerHTML = [['all', 'All'], ...cats.map((c) => [String(c.id), c.name])]
      .map(([id, n]) => `<button class="chip" data-cat="${id}" aria-pressed="${cat === id}">${esc(n)}</button>`).join('');
    const list = visibleCats();
    $('#menu').innerHTML = list.length ? list.map((c) => `<h3 style="padding-top:8px">${esc(c.name)}</h3>${soldMode ? c.items.map(soldRow).join('') : menuRowsHtml(c.items, cart)}`).join('')
      : `<div class="empty"><b>${cats.length ? 'No match' : 'No menu yet'}</b>${cats.length ? 'Try a different search.' : 'The owner can add items under Admin → Menu.'}</div>`;
  }

  /* ---------------- cart ---------------- */
  function cartPanel() {
    const items = flatItems(cats).filter((m) => cart[m.id]);
    const total = cartTotal(cart, cats), empty = !items.length;
    const lines = items.length ? items.map((m) => `<div class="cart-line"><div class="grow"><div class="name">${dietIcon(m.diet)} ${esc(m.name)}</div><div class="muted small price">${money(m.price)} × ${cart[m.id]} = ${money(m.price * cart[m.id])}</div></div>
      <div class="stepper"><button data-dec="${m.id}" aria-label="Remove one">−</button><span class="q">${cart[m.id]}</span><button data-inc="${m.id}" aria-label="Add one">+</button></div></div>`).join('')
      : '<div class="empty"><b>No items yet</b>Tap Add on a menu item.</div>';
    return `<div class="card-h"><h2>Current order</h2>${empty ? '' : '<button class="btn sm ghost danger" data-act="clear">Clear</button>'}</div>${lines}
      <div class="total-row"><span>Bill total</span><b>${money(total)}</b></div>
      ${form.customer ? `<div class="card flat" style="padding:10px"><div class="spread"><div><div class="muted tiny">Customer account</div><b>${esc(form.customer.name)}</b> <span class="mono small">${esc(form.customer.phone)}</span></div><button class="btn sm ghost" data-act="unfind">Remove</button></div></div>`
      : `<div class="form-grid two">
        <label class="field">Phone (optional)<input type="tel" inputmode="tel" data-f="phone" value="${esc(form.phone)}" placeholder="98450 12345"></label>
        <label class="field">Name (optional)<input type="text" data-f="name" value="${esc(form.name)}" maxlength="40"></label>
      </div><button class="btn sm" data-act="find" style="margin-top:8px">Find registered customer</button>`}
      <label class="field" style="margin-top:10px">Note<input type="text" data-f="note" value="${esc(form.note)}" maxlength="200" placeholder="e.g. no onion"></label>
      <div class="btns mt">
        <button class="btn ok grow" data-act="pay" data-m="Cash" ${empty ? 'disabled' : ''}>Cash received</button>
        <button class="btn primary grow" data-act="pay" data-m="UPI" ${empty ? 'disabled' : ''}>UPI received</button>
      </div>
      <div class="btns" style="margin-top:8px">
        <button class="btn grow" data-act="qr" ${empty ? 'disabled' : ''}>Show UPI QR</button>
        <button class="btn grow" data-act="pay" data-m="" ${empty ? 'disabled' : ''}>Pay later</button>
      </div>
      <p class="muted tiny" style="margin-top:8px">Pay later sends the order unpaid. It cannot be cooked until the cashier marks it paid on the Parcel screen.</p>`;
  }

  function drawCart() {
    $('#cart-desktop').innerHTML = cartPanel();
    if (sheet) { cartCount(cart) ? (sheet.el.innerHTML = cartPanel()) : (sheet.close(), sheet = null); }
    const n = cartCount(cart), bar = $('#cartbar');
    bar.hidden = n === 0;
    $('#viewcart').textContent = `View order · ${n} item${n === 1 ? '' : 's'} · ${money(cartTotal(cart, cats))}`;
  }

  function redraw() { drawMenu(); drawCart(); }

  async function submit(method) {
    const body = { items: cartList(cart), payMethod: method || null, note: form.note, ...(form.customer ? { customer_id: form.customer.id } : { name: form.name, phone: form.phone }) };
    const o = await attempt(() => api('/api/orders', 'POST', body));
    if (!o) return;
    last = o; clearCart(cart); form = { name: '', phone: '', note: '', customer: null };
    if (sheet) { sheet.close(); sheet = null; }
    redraw(); drawLast(); refreshSummary();
    toast(`Token ${o.tok} · ${money(o.total)} · ${method ? method + ' received' : 'unpaid'}`, 'ok');
  }

  function drawLast() {
    const el = $('#last');
    if (!last) { el.hidden = true; return; }
    el.hidden = false;
    el.innerHTML = `<div class="spread wrap"><div><span class="muted small">Last order</span><div><b class="mono" style="font-size:22px">Token ${last.tok}</b> <span class="muted">· ${money(last.total)}</span> ${last.due > 0 ? '<span class="pill warn">Unpaid</span>' : '<span class="pill ok">Paid</span>'}</div></div>
      <a class="btn sm" href="/receipt/${last.id}" target="_blank" rel="noopener">Receipt</a></div>`;
  }

  async function refreshSummary() {
    try {
      const d = await api('/api/orders');
      const s = d.summary;
      $('#summary').textContent = `Today: ${s.orders} orders · UPI ${money(s.upi)} · Cash ${money(s.cash)} · ${s.pending} in progress`;
    } catch (e) { /* offline */ }
  }

  async function loadMenu() {
    const d = await api('/api/menu');
    const sig = JSON.stringify(d.categories);
    if (sig === menuSig) return;
    menuSig = sig; cats = d.categories;
    Object.keys(cart).forEach((id) => { const m = flatItems(cats).find((x) => x.id === +id); if (!m || !m.available) delete cart[id]; });
    redraw();
  }

  /* ---------------- UPI QR ---------------- */
  function showQr() {
    const A = window.APP, total = cartTotal(cart, cats);
    if (!A.upi_vpa) { toast('Add your UPI ID in Admin → Settings first', 'bad'); return; }
    const link = `upi://pay?pa=${encodeURIComponent(A.upi_vpa)}&pn=${encodeURIComponent(A.upi_name)}&am=${total.toFixed(2)}&cu=INR&tn=${encodeURIComponent('Order')}`;
    const m = modal(`<h2>Scan to pay ${money(total)}</h2><div class="center"><div id="qr" style="display:inline-block;padding:12px;background:#fff;border-radius:12px"></div><p class="muted small" style="margin-top:8px">${esc(A.upi_name)} · ${esc(A.upi_vpa)}</p></div><div class="btns mt"><button class="btn grow" data-x>Close</button></div>`);
    $('[data-x]', m.el).addEventListener('click', m.close);
    if (window.QRCode) new QRCode($('#qr', m.el), { text: link, width: 230, height: 230, correctLevel: QRCode.CorrectLevel.M });
    else $('#qr', m.el).innerHTML = `<a href="${esc(link)}">Open UPI link</a><p class="muted small">QR library could not load (no internet).</p>`;
    toast('Check the money arrived in your UPI app, then tap "UPI received".');
  }

  /* ---------------- events ---------------- */
  document.addEventListener('click', (e) => {
    const c = e.target.closest('[data-cat]'); if (c) { cat = c.dataset.cat; drawMenu(); return; }
    const av = e.target.closest('[data-avail]');
    if (av) { attempt(async () => { await api(`/api/menu/${av.dataset.avail}/available`, 'POST', { available: av.dataset.to === '1' }); menuSig = ''; await loadMenu(); }); return; }
    const a = e.target.closest('[data-act]'); if (!a) return;
    if (a.dataset.act === 'pay') submit(a.dataset.m);
    else if (a.dataset.act === 'qr') showQr();
    else if (a.dataset.act === 'clear') { clearCart(cart); redraw(); }
    else if (a.dataset.act === 'find') findCustomer();
    else if (a.dataset.act === 'unfind') { form.customer = null; drawCart(); }
  });

  /* ---------------- find a registered customer ---------------- */
  function findCustomer() {
    const m = modal(`<h2>Find customer</h2><input type="search" id="fq" placeholder="Name or mobile number" autocomplete="off"><div id="fres" style="margin-top:8px"></div><button class="btn block ghost" data-x style="margin-top:8px">Cancel</button>`);
    $('[data-x]', m.el).addEventListener('click', m.close);
    let t = null;
    const run = async () => {
      const q = $('#fq', m.el).value.trim(); if (q.length < 2) { $('#fres', m.el).innerHTML = '<p class="muted small">Type at least 2 letters or digits.</p>'; return; }
      try {
        const d = await api('/api/customers?limit=8&q=' + encodeURIComponent(q));
        $('#fres', m.el).innerHTML = d.customers.length ? d.customers.map((c) => `<button class="btn block" style="text-align:left;margin-bottom:6px" data-pick="${c.id}"><b>${esc(c.name)}</b> <span class="mono small">${esc(c.phone)}</span><br><span class="muted tiny">${c.orders} order${c.orders === 1 ? '' : 's'}</span></button>`).join('')
          : '<p class="muted small">No registered customer found. You can still type a name and phone on the order.</p>';
        $$('[data-pick]', m.el).forEach((b) => b.addEventListener('click', () => { const c = d.customers.find((x) => x.id === +b.dataset.pick); form.customer = { id: c.id, name: c.name, phone: c.phone }; m.close(); drawCart(); }));
      } catch (e) { $('#fres', m.el).innerHTML = `<p class="err">${esc(e.message)}</p>`; }
    };
    $('#fq', m.el).addEventListener('input', () => { clearTimeout(t); t = setTimeout(run, 250); });
    $('#fq', m.el).focus(); run();
  }
  document.addEventListener('input', (e) => { if (e.target.dataset && e.target.dataset.f) form[e.target.dataset.f] = e.target.value; });
  $('#q').addEventListener('input', (e) => { query = e.target.value; drawMenu(); });
  $('#sold').addEventListener('click', (e) => { soldMode = !soldMode; e.currentTarget.setAttribute('aria-pressed', soldMode); e.currentTarget.classList.toggle('primary', soldMode); e.currentTarget.textContent = soldMode ? 'Done' : 'Sold-out mode'; drawMenu(); });
  $('#viewcart').addEventListener('click', () => { sheet = modal(cartPanel()); bindCart(sheet.el, cart, redraw); });
  bindCart($('#menu'), cart, redraw);
  bindCart($('#cart-desktop'), cart, redraw);

  poll(loadMenu, 15000);
  poll(refreshSummary, 10000);
})();
