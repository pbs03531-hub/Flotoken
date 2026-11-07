/* Customer app: browse the menu, sign up / log in (required to order), pay, track the token, reorder, rate. */
(() => {
  const KEY = 'pd_order_code_' + SLUG;
  const root = $('#root');
  let menu = null, me = null, cart = {}, cat = 'all', code = null, order = null, timer = null, form = { note: '' }, sheet = null;

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  const heroHtml = () => `<div class="card flat" style="margin-bottom:12px"><div class="spread"><div><h1>${esc(menu.restaurant)}</h1><p class="muted small">${me ? 'Hi ' + esc(me.name.split(' ')[0]) + '! ' : ''}Order here, pay, and collect with your token. No waiting in line.</p></div>${menu.accepting ? `<span class="pill warn">~${menu.eta_min} min</span>` : '<span class="pill bad">Closed</span>'}</div>
    <div class="btns" style="margin-top:10px">${me ? '<button class="btn sm" id="myorders">My orders</button><button class="btn sm ghost" id="account">Account</button>' : '<button class="btn sm primary" id="login">Sign up / Log in</button>'}<a class="btn sm ghost" href="/customer">All restaurants</a><button class="btn sm" data-install hidden>Install app</button></div></div>`;

  function bindHero() {
    const on = (id, fn) => { const b = $(id); if (b) b.addEventListener('click', fn); };
    on('#login', () => openAuth());
    on('#myorders', showOrders);
    on('#account', openAccount);
  }

  /* ---------------- sign up / log in (shared with the customer portal: account.js) ---------------- */
  function openAuth(next, mode = 'signup') {
    Account.openAuth({ mode, brand: menu.restaurant, onDone: (c, up) => {
      me = c; toast(up ? 'Account created' : 'Logged in', 'ok');
      if (next) next(); else if (!code) showMenu(); else showTrack();
    } });
  }
  const openAccount = () => Account.openAccount(me, { onSaved: (c) => { me = c; redraw(); }, onGone: () => { me = null; startOver(); } });

  const redraw = () => (code && order ? showTrack() : showMenu());

  /* ---------------- menu ---------------- */
  function showMenu() {
    document.title = menu.restaurant + ' · Order for pickup';
    root.innerHTML = heroHtml() +
      (menu.accepting ? '' : '<div class="banner warn mb">We are not taking phone orders right now. Please order at the counter.</div>') +
      '<div class="chips" id="chips" role="group" aria-label="Menu sections"></div><div class="card" id="menu"></div>' +
      '<div class="cartbar" id="cartbar" hidden><button class="btn primary block" id="viewcart"></button></div>';
    bindCart($('#menu'), cart, onCartChange);
    $('#chips').addEventListener('click', (e) => { const b = e.target.closest('[data-cat]'); if (b) { cat = b.dataset.cat; drawMenu(); } });
    $('#viewcart').addEventListener('click', openCheckout);
    bindHero(); drawMenu(); drawBar();
  }

  function drawMenu() {
    const chips = [['all', 'All'], ...menu.categories.map((c) => [String(c.id), c.name])];
    $('#chips').innerHTML = chips.map(([id, name]) => `<button class="chip" data-cat="${id}" aria-pressed="${cat === id}">${esc(name)}</button>`).join('');
    const cats = menu.categories.filter((c) => cat === 'all' || String(c.id) === cat);
    $('#menu').innerHTML = cats.length ? cats.map((c) => `<h3 style="padding-top:8px">${esc(c.name)}</h3>${menuRowsHtml(c.items, menu.accepting ? cart : {}, { photos: true })}`).join('')
      : '<div class="empty"><b>Menu coming soon</b>The restaurant has not added any items yet.</div>';
    if (!menu.accepting) $$('#menu [data-inc]').forEach((b) => (b.disabled = true));
  }

  function drawBar() {
    const n = cartCount(cart), bar = $('#cartbar');
    if (!bar) return;
    bar.hidden = n === 0;
    $('#viewcart').textContent = `View order · ${n} item${n === 1 ? '' : 's'} · ${money(cartTotal(cart, menu.categories))}`;
  }

  function onCartChange() { drawMenu(); drawBar(); if (sheet) { cartCount(cart) ? paintCheckout() : (sheet.close(), sheet = null); } }

  /* ---------------- checkout ---------------- */
  function openCheckout() {
    if (!me) { openAuth(openCheckout); return; }     // an account is required to order
    sheet = modal(''); paintCheckout(); bindCart(sheet.el, cart, onCartChange);
  }

  function paintCheckout() {
    const items = flatItems(menu.categories), total = cartTotal(cart, menu.categories);
    const lines = items.filter((m) => cart[m.id]).map((m) => `<div class="cart-line"><div class="grow"><div class="name">${dietIcon(m.diet)} ${esc(m.name)}</div><div class="muted small price">${money(m.price)} each</div></div>
      <div class="stepper"><button data-dec="${m.id}" aria-label="Remove one">−</button><span class="q">${cart[m.id]}</span><button data-inc="${m.id}" aria-label="Add one">+</button></div></div>`).join('');
    const mode = menu.payment_mode, demo = mode === 'demo';
    if (mode === 'both' && !form.method) form.method = 'upi';
    const payBlock = mode === 'both' ? `<div class="stack"><b class="small">How will you pay?</b>
        <label class="check"><input type="radio" name="method" value="upi" ${form.method === 'upi' ? 'checked' : ''}><span>Pay by UPI now<br><span class="muted small" style="font-weight:400">Opens your UPI app on the next screen.</span></span></label>
        <label class="check"><input type="radio" name="method" value="counter" ${form.method === 'counter' ? 'checked' : ''}><span>Pay at the counter<br><span class="muted small" style="font-weight:400">Pay cash or scan the shop's UPI QR when you collect.</span></span></label></div>` : '';
    const label = demo ? `Pay ${money(total)} with UPI` : mode === 'counter' || (mode === 'both' && form.method === 'counter') ? 'Place order, pay at counter' : mode === 'upi_manual' || mode === 'both' ? 'Place order, pay by UPI' : 'Place order';
    const hint = demo ? 'Demo mode: payment is simulated.' : mode === 'counter' || (mode === 'both' && form.method === 'counter') ? 'You pay at the counter. Cooking starts once the cashier confirms your payment, so please come soon.' : 'You will pay by UPI on the next screen. Cooking starts once the restaurant confirms your payment.';
    sheet.el.innerHTML = `<h2>Your order</h2>${lines}
      <div class="total-row"><span>Total</span><b>${money(total)}</b></div>
      <div class="stack">
        <div class="kv small"><span class="muted">Ordering as</span><b>${esc(me.name)} · ${esc(me.phone)}</b></div>
        <label class="field">Note for the kitchen (optional)<input type="text" data-f="note" value="${esc(form.note)}" maxlength="200" placeholder="e.g. less spicy"></label>
        ${payBlock}
        <div class="err" id="err" role="alert"></div>
        <button class="btn primary block" id="place">${label}</button>
        <p class="muted tiny center">${hint}</p>
        <button class="btn block ghost" data-close>Keep browsing</button>
      </div>`;
    $$('input[name=method]', sheet.el).forEach((r) => r.addEventListener('change', () => { form.method = r.value; paintCheckout(); bindCart(sheet.el, cart, onCartChange); }));
    $('#place', sheet.el).addEventListener('click', place);
    $('[data-close]', sheet.el).addEventListener('click', () => { sheet.close(); sheet = null; });
  }

  document.addEventListener('input', (e) => {
    const f = e.target.dataset && e.target.dataset.f;
    if (f) form[f] = e.target.value;
  });

  async function place() {
    const btn = $('#place', sheet.el), err = $('#err', sheet.el);
    err.textContent = ''; btn.disabled = true;
    try {
      order = await api('/api/public/orders', 'POST', { items: cartList(cart), note: form.note, method: form.method });
      code = order.code; store.set(KEY, code); clearCart(cart);
      sheet.close(); sheet = null;
      history.replaceState(null, '', U('/t/' + code));
      showTrack(); startPolling();
    } catch (e) {
      err.textContent = e.message; btn.disabled = false;
      if (e.status === 401) { me = null; sheet.close(); sheet = null; openAuth(openCheckout, 'login'); return; }
      if (e.status === 409 || e.status === 400) { try { menu = await api('/api/public/menu'); Object.keys(cart).forEach((id) => { const m = flatItems(menu.categories).find((x) => x.id === +id); if (!m || !m.available) delete cart[id]; }); drawMenu(); drawBar(); } catch (x) { /* ignore */ } }
    }
  }

  /* ---------------- tracking ---------------- */
  const STEPS = [['placed', 'Order received'], ['preparing', 'Being prepared'], ['ready', 'Ready to collect'], ['collected', 'Collected']];

  function showTrack() {
    const o = order, idx = STEPS.findIndex((s) => s[0] === o.status), unpaid = o.due > 0 && o.status !== 'cancelled';
    document.title = (o.status === 'ready' ? '✅ Ready · ' : '') + 'Token ' + o.tok + ' · ' + o.restaurant;
    const headline = o.status === 'cancelled' ? '<span class="pill bad">Cancelled</span>'
      : o.status === 'ready' ? '<span class="pill ok">Ready. Please collect it now</span>'
        : o.status === 'collected' ? '<span class="pill ok">Collected. Thank you!</span>'
          : unpaid ? '<span class="pill warn">Waiting for payment</span>' : '<span class="pill info">We are on it</span>';
    const steps = o.status === 'cancelled' ? `<div class="banner bad">${o.cancel_reason ? esc(o.cancel_reason) : 'This order was cancelled.'}${o.paid > 0 ? ' Your payment will be refunded at the counter.' : ''}</div>`
      : `<ol class="steps">${STEPS.map((s, i) => `<li class="${i < idx || o.status === 'collected' ? 'done' : i === idx ? 'now' : ''}"><i></i>${s[1]}</li>`).join('')}</ol>`;
    const upi = unpaid && o.upi ? `<div class="card stack" style="margin-top:12px"><h2>Pay ${money(o.upi.amount)}</h2>
        <a class="btn primary block" href="${esc(o.upi.link)}">Open UPI app and pay</a>
        <div class="spread small"><span class="muted">UPI ID</span><span><b class="mono">${esc(o.upi.vpa)}</b> <button class="btn sm" id="copy">Copy</button></span></div>
        <p class="muted small">Use token <b>${o.tok}</b> as the payment note. The restaurant confirms your payment and starts cooking.</p></div>` : '';
    const atCounter = unpaid && o.pay_pref === 'counter' ? `<div class="card stack" style="margin-top:12px"><h2>Pay ${money(o.due)} at the counter</h2>
        <p>Show token <b>${o.tok}</b> to the cashier and pay by cash or by scanning the shop's UPI QR. Cooking starts as soon as the cashier confirms.</p></div>` : '';
    root.innerHTML = `<div class="card center"><p class="muted small">Your token at ${esc(o.restaurant)}</p><div class="bigtok">${o.tok}</div>${headline}
        ${o.ready_by && ['placed', 'preparing'].includes(o.status) && !unpaid ? `<p class="muted small" style="margin-top:8px">Estimated ready by ${hm(o.ready_by)}</p>` : ''}</div>
      <div class="card" style="margin-top:12px">${steps}</div>${upi}${atCounter}
      <div class="card" style="margin-top:12px"><h3 style="margin-bottom:6px">Your order</h3>
        ${o.items.map((i) => `<div class="kv"><span>${i.qty} × ${esc(i.name)}</span><span class="price">${money(i.qty * i.price)}</span></div>`).join('')}
        <div class="kv" style="border-top:1px solid var(--line);margin-top:6px;padding-top:8px"><b>Total</b><b class="price">${money(o.total)}</b></div>
        <div class="kv muted small"><span>Paid</span><span class="price">${money(o.paid)}</span></div>
        ${o.due > 0 && o.status !== 'cancelled' ? `<div class="kv small"><b>Still to pay</b><b class="price">${money(o.due)}</b></div>` : ''}</div>
      ${ratingHtml(o)}
      <div class="btns" style="margin-top:12px"><button class="btn grow" id="more">Order something else</button>${me ? '<button class="btn grow" id="myorders">My orders</button>' : ''}</div>
      <div class="btns" style="margin-top:8px"><button class="btn grow" data-install hidden>Install app to track your order</button></div>
      <p class="muted tiny center" style="margin-top:12px">Keep this page open. It updates by itself. Bookmark it to check later.</p>`;
    const copy = $('#copy');
    if (copy) copy.addEventListener('click', async () => { try { await navigator.clipboard.writeText(o.upi.vpa); toast('UPI ID copied', 'ok'); } catch (e) { toast('Select and copy: ' + o.upi.vpa); } });
    $('#more').addEventListener('click', startOver);
    const mo = $('#myorders'); if (mo) mo.addEventListener('click', showOrders);
    bindRating(o.code, () => refreshOrder(true));
  }

  /* ---------------- rating ---------------- */
  const stars = (n) => '★'.repeat(n) + '☆'.repeat(5 - n);
  function ratingHtml(o) {
    if (o.status !== 'collected' || !o.mine) return '';
    if (o.rating) return `<div class="card center" style="margin-top:12px"><p class="muted small">Your rating</p><div class="starsline" aria-label="${o.rating} out of 5">${stars(o.rating)}</div><p class="muted small">Thank you for the feedback!</p></div>`;
    return `<div class="card center" style="margin-top:12px" id="rate"><h3>How was your order?</h3><div class="stars" role="group" aria-label="Rate your order">${[1, 2, 3, 4, 5].map((n) => `<button class="star" data-star="${n}" aria-label="${n} star${n > 1 ? 's' : ''}">☆</button>`).join('')}</div>
      <input type="text" id="rnote" maxlength="200" placeholder="Anything to tell us? (optional)" style="margin-top:8px"><div class="err" id="rerr" role="alert"></div></div>`;
  }
  function bindRating(orderCode, done) {
    const box = $('#rate'); if (!box) return;
    $$('[data-star]', box).forEach((b) => {
      b.addEventListener('mouseenter', () => paintStars(box, +b.dataset.star));
      b.addEventListener('click', async () => {
        paintStars(box, +b.dataset.star);
        try { await api('/api/public/orders/' + orderCode + '/rating', 'POST', { rating: +b.dataset.star, note: $('#rnote', box).value }); toast('Thanks for rating!', 'ok'); done(); }
        catch (e) { $('#rerr', box).textContent = e.message; }
      });
    });
    box.addEventListener('mouseleave', () => paintStars(box, 0));
  }
  const paintStars = (box, n) => $$('[data-star]', box).forEach((b) => { b.textContent = +b.dataset.star <= n ? '★' : '☆'; });

  /* ---------------- my orders + reorder ---------------- */
  async function showOrders() {
    clearInterval(timer);
    root.innerHTML = heroHtml() + '<div class="card" id="olist"><div class="empty">Loading your orders…</div></div>';
    bindHero();
    let list = [];
    try { list = (await api('/api/customer/orders?r=' + SLUG)).orders; } catch (e) { if (e.status === 401) { me = null; startOver(); return; } $('#olist').innerHTML = `<div class="empty">${esc(e.message)}</div>`; return; }
    const pill = (st) => ({ placed: ['info', 'Received'], preparing: ['info', 'Preparing'], ready: ['ok', 'Ready'], collected: ['ok', 'Collected'], cancelled: ['bad', 'Cancelled'] }[st]);
    $('#olist').innerHTML = `<div class="spread"><h2>My orders</h2><button class="btn sm" id="back">Back to menu</button></div>` + (list.length ? list.map((o) => {
      const [kind, label] = pill(o.status), active = ['placed', 'preparing', 'ready'].includes(o.status);
      return `<div class="order-card" style="border-top:1px solid var(--line);padding:12px 0">
        <div class="spread"><b>Token ${o.tok} <span class="muted small">· ${dmy(new Date(o.created_at))} ${hm(o.created_at)}</span></b><span class="pill ${kind}">${label}</span></div>
        <div class="muted small" style="margin:4px 0">${o.items.map((i) => `${i.qty} × ${esc(i.name)}`).join(', ')}</div>
        <div class="spread"><b class="price">${money(o.total)}</b><span class="btns">${o.rating ? `<span class="starsline small">${stars(o.rating)}</span>` : ''}
          ${active ? `<button class="btn sm primary" data-track="${esc(o.code)}">Track</button>` : `<button class="btn sm" data-track="${esc(o.code)}">View</button>`}
          ${o.status !== 'cancelled' ? `<button class="btn sm primary" data-again="${o.code}">Order again</button>` : ''}</span></div></div>`;
    }).join('') : '<div class="empty"><b>No orders yet</b>Your orders will show here so you can reorder in one tap.</div>');
    $('#back').addEventListener('click', startOver);
    $('#olist').addEventListener('click', async (e) => {
      const t = e.target.closest('[data-track]'), a = e.target.closest('[data-again]');
      if (t) { code = t.dataset.track; store.set(KEY, code); history.replaceState(null, '', U('/t/' + code)); order = null; if (await refreshOrder(true) === 'ok') startPolling(); }
      if (a) reorder(list.find((o) => o.code === a.dataset.again));
    });
  }

  async function reorder(o) {
    try { menu = await api('/api/public/menu'); } catch (e) { toast(e.message, 'bad'); return; }
    const live = new Map(flatItems(menu.categories).map((m) => [m.id, m])), skipped = [];
    clearCart(cart);
    o.items.forEach((i) => { const m = live.get(i.id); if (m && m.available) cart[i.id] = i.qty; else skipped.push(i.name); });
    code = null; order = null; store.set(KEY, null); history.replaceState(null, '', U('/order'));
    showMenu();
    if (skipped.length) toast('Not available now: ' + skipped.join(', '), 'bad');
    if (cartCount(cart)) { drawMenu(); drawBar(); openCheckout(); }
  }

  async function startOver() {
    clearInterval(timer); store.set(KEY, null); code = null; order = null; clearCart(cart);
    history.replaceState(null, '', U('/order'));
    try { menu = await api('/api/public/menu'); } catch (e) { toast(e.message, 'bad'); }
    showMenu();
  }

  async function refreshOrder(force) {
    try {
      const next = await api('/api/public/orders/' + code);
      const was = order && order.status;
      const changed = force || !order || ['status', 'due', 'paid', 'total', 'eta_min', 'rating'].some((k) => order[k] !== next[k]) || order.items.length !== next.items.length;
      order = next;
      if (changed) {
        showTrack();
        if (was && was !== 'ready' && next.status === 'ready') { beep(3); if (navigator.vibrate) navigator.vibrate([250, 120, 250, 120, 250]); }
      }
      if (['collected', 'cancelled'].includes(next.status)) clearInterval(timer);
      return 'ok';
    } catch (e) { return e.status === 404 ? 'gone' : 'error'; }
  }

  function startPolling() { clearInterval(timer); timer = setInterval(() => { if (!document.hidden) refreshOrder(); }, 3000); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden && code && order) refreshOrder(); });

  /* ---------------- start ---------------- */
  (async function init() {
    try { menu = await api('/api/public/menu'); } catch (e) { root.innerHTML = `<div class="empty"><b>Cannot load the menu</b>${esc(e.message)}<div class="mt"><button class="btn primary" onclick="location.reload()">Try again</button></div></div>`; return; }
    try { me = (await api('/api/customer/me')).customer; } catch (e) { me = null; }
    const again = new URLSearchParams(location.search).get('again');
    if (again && me) {                                   // "Order again" from the customer page
      try {
        const o = (await api('/api/customer/orders?r=' + SLUG)).orders.find((x) => x.code === again);
        history.replaceState(null, '', U('/order'));
        if (o) { await reorder(o); return; }
      } catch (e) { /* fall through to the normal page */ }
    }
    code = window.TRACK_CODE || store.get(KEY);
    if (code) {
      const r = await refreshOrder();
      if (r === 'ok') { store.set(KEY, code); startPolling(); return; }
      if (r === 'error') { root.innerHTML = '<div class="empty"><b>Cannot reach the restaurant</b>Check your connection.<div class="mt"><button class="btn primary" onclick="location.reload()">Try again</button></div></div>'; return; }
      store.set(KEY, null); code = null; history.replaceState(null, '', U('/order'));   // link no longer valid
    }
    showMenu();
  })();
})();
