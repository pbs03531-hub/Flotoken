/* Admin: reports, menu, staff, settings, QR codes. Owner only. */
(() => {
  const TABS = [['dashboard', 'Dashboard'], ['reports', 'Reports'], ['customers', 'Customers'], ['menu', 'Menu'], ['staff', 'Staff'], ['settings', 'Settings'], ['qr', 'QR codes'], ['plan', 'Plan']];
  const view = $('#view');
  let tab = 'dashboard';

  const addDays = (iso, n) => { const d = new Date(iso + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
  const paintTabs = () => { $('#tabs').innerHTML = TABS.map(([k, n]) => `<button role="tab" data-tab="${k}" aria-selected="${tab === k}">${n}</button>`).join(''); };
  function show(t) {
    tab = t; try { history.replaceState(null, '', '#' + t); } catch (e) { /* ignore */ }
    paintTabs(); view.innerHTML = '<div class="empty">Loading…</div>';
    attempt(() => ({ dashboard, reports, customers, menu, staff, settings, qr, plan }[t])());
  }
  window.addEventListener('hashchange', () => { const t = location.hash.slice(1); if (t !== tab && TABS.some((x) => x[0] === t)) show(t); });
  $('#tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) show(b.dataset.tab); });

  /* ======================= REPORTS ======================= */
  const range = { preset: 'today', from: todayIST(), to: todayIST() };

  function presetRange(p) {
    const t = todayIST();
    if (p === 'today') return [t, t];
    if (p === 'yesterday') return [addDays(t, -1), addDays(t, -1)];
    if (p === '7d') return [addDays(t, -6), t];
    if (p === 'month') return [t.slice(0, 8) + '01', t];
    return [range.from, range.to];
  }

  async function reports() {
    view.innerHTML = `<div class="card flat mb"><div class="chips" id="presets">${[['today', 'Today'], ['yesterday', 'Yesterday'], ['7d', 'Last 7 days'], ['month', 'This month'], ['custom', 'Custom']].map(([k, n]) => `<button class="chip" data-preset="${k}">${n}</button>`).join('')}</div>
      <div class="form-grid two" id="custom" hidden><label class="field">From<input type="date" id="from"></label><label class="field">To<input type="date" id="to"></label></div></div><div id="rep"></div>`;
    const sync = () => {
      $$('#presets .chip').forEach((c) => c.setAttribute('aria-pressed', c.dataset.preset === range.preset));
      $('#custom').hidden = range.preset !== 'custom'; $('#from').value = range.from; $('#to').value = range.to;
    };
    $('#presets').addEventListener('click', (e) => {
      const b = e.target.closest('[data-preset]'); if (!b) return;
      range.preset = b.dataset.preset; [range.from, range.to] = presetRange(range.preset); sync(); loadReport();
    });
    $('#from').addEventListener('change', (e) => { range.from = e.target.value; loadReport(); });
    $('#to').addEventListener('change', (e) => { range.to = e.target.value; loadReport(); });
    sync(); await loadReport();
  }

  async function loadReport() {
    const d = await attempt(() => api(`/api/admin/reports?from=${range.from}&to=${range.to}`));
    if (!d || !$('#rep')) return;
    const kpi = (label, value, extra = '') => `<div class="kpi"><small>${label}</small><b ${extra}>${value}</b></div>`;
    const hours = d.by_hour; const nz = hours.map((v, i) => (v ? i : -1)).filter((i) => i >= 0);
    let chart = '<p class="muted small">No orders in this period.</p>';
    if (nz.length) {
      const lo = Math.min(nz[0], 8), hi = Math.max(nz[nz.length - 1], 20), slice = hours.slice(lo, hi + 1), max = Math.max(...slice, 1);
      const lab = (h) => (h % 12 || 12) + (h < 12 ? 'a' : 'p');
      chart = `<div class="bars" role="img" aria-label="Orders per hour">${slice.map((v, i) => `<div class="${v ? '' : 'zero'}" style="height:${Math.max(2, v / max * 100)}%" title="${lab(lo + i)}: ${v} orders"></div>`).join('')}</div>
        <div class="bar-labels">${slice.map((v, i) => `<span>${(lo + i) % 2 === 0 ? lab(lo + i) : ''}</span>`).join('')}</div>`;
    }
    const topMax = Math.max(...d.top_items.map((i) => i.qty), 1);
    $('#rep').innerHTML = `<div class="spread mb"><h2>${d.start === d.end ? dmy(d.start) : dmy(d.start) + ' to ' + dmy(d.end)}</h2><a class="btn sm" href="${U('/api/admin/reports/export.csv')}?from=${d.start}&to=${d.end}">Download CSV</a></div>
      <div class="kpis">${kpi('Sales', money(d.sales))}${kpi('Orders', d.orders)}${kpi('Average bill', money(d.avg_ticket))}${kpi('UPI received', money(d.upi))}${kpi('Cash received', money(d.cash))}${kpi('Unpaid', money(d.unpaid), d.unpaid ? 'style="color:var(--bad)"' : '')}${kpi('Cancelled', d.cancelled)}${kpi('Avg time to ready', d.avg_prep_min == null ? '-' : d.avg_prep_min + ' min')}${kpi('Avg wait at counter', d.avg_pickup_wait_min == null ? '-' : d.avg_pickup_wait_min + ' min')}</div>
      <div class="form-grid two mt" style="align-items:start">
        <div class="card"><h3 class="mb">Orders by hour</h3>${chart}<p class="muted small" style="margin-top:10px">Counter ${d.by_source.counter} · Phone ${d.by_source.app}</p></div>
        <div class="card"><h3 class="mb">Top items</h3>${d.top_items.length ? d.top_items.map((i) => `<div class="hbar"><span>${esc(i.name)}</span><div class="track"><div class="fill" style="width:${i.qty / topMax * 100}%"></div></div><b class="num">${i.qty}</b></div>`).join('') : '<p class="muted small">Nothing sold yet.</p>'}</div>
      </div>
      ${d.by_day.length > 1 ? `<div class="table-wrap mt"><table><thead><tr><th>Date</th><th class="num">Orders</th><th class="num">Sales</th></tr></thead><tbody>${d.by_day.map((r) => `<tr><td>${dmy(r.day)}</td><td class="num">${r.orders}</td><td class="num">${money(r.sales)}</td></tr>`).join('')}</tbody></table></div>` : ''}
      <p class="muted small mt">Sales count every order that was not cancelled. UPI and Cash show money actually recorded, after refunds.</p>`;
  }

  /* ======================= MENU ======================= */
  let cats = [];
  async function menu() { cats = (await api('/api/menu')).categories; paintMenu(); }
  const findItem = (id) => cats.flatMap((c) => c.items).find((i) => i.id === id);
  const thumb = (i) => i.image_v ? `<img class="thumb sm" src="${U('/img/' + i.id)}?v=${i.image_v}" alt="" width="52" height="52" loading="lazy">` : `<span class="thumb sm ph" aria-hidden="true">${esc(i.name.slice(0, 1).toUpperCase())}</span>`;

  function paintMenu() {
    view.innerHTML = `<div class="stack mb"><p class="muted small">Tap an item to change its name, price, photo or description. The switch marks it sold out. Customers see changes straight away. Old bills never change.</p>
      <div class="btns"><button class="btn" data-act="add-cat">Add category</button><button class="btn primary" data-act="item-add" data-id="0" ${cats.length ? '' : 'disabled'}>Add item</button></div></div>` +
      (cats.length ? cats.map((c) => `<section class="card mb"><div class="card-h"><h2>${esc(c.name)}</h2><button class="btn sm" data-act="cat-edit" data-id="${c.id}">Edit category</button></div>
        ${c.items.length ? c.items.map((i) => `<div class="menu-row ${i.available ? '' : 'soldout'}">
          <button class="row-main" data-act="item-edit" data-id="${i.id}" aria-label="Edit ${esc(i.name)}">${thumb(i)}<span class="grow"><span class="name">${dietIcon(i.diet)}${esc(i.name)}</span><span class="price muted small" style="display:block">${money(i.price)}${i.available ? '' : ' · sold out'}</span></span></button>
          <label class="switch" title="Available"><input type="checkbox" data-act="item-avail" data-id="${i.id}" ${i.available ? 'checked' : ''} aria-label="${esc(i.name)} available"><i></i></label></div>`).join('') : '<p class="muted small">No items in this category yet.</p>'}
        <div class="mt"><button class="btn block" data-act="item-add" data-id="${c.id}">Add item to ${esc(c.name)}</button></div></section>`).join('')
        : '<div class="empty card"><b>Your menu is empty</b>Add a category (for example Biryani), then add items with photos and prices.</div>');
  }

  function categoryDialog(c) {
    const idx = cats.findIndex((x) => x.id === c.id);
    const m = modal(`<h2>Edit category</h2><form class="stack" id="cform">
      <label class="field">Category name<input type="text" id="c-name" maxlength="40" value="${esc(c.name)}" required></label>
      <div class="err" id="c-err" role="alert"></div>
      <div class="btns"><button type="button" class="btn grow" data-x>Cancel</button><button class="btn primary grow">Save name</button></div>
      <div class="btns"><button type="button" class="btn grow" data-mv="-1" ${idx === 0 ? 'disabled' : ''}>Move up ↑</button><button type="button" class="btn grow" data-mv="1" ${idx === cats.length - 1 ? 'disabled' : ''}>Move down ↓</button></div>
      <button type="button" class="btn danger block" data-del>Delete category</button></form>`);
    $('[data-x]', m.el).addEventListener('click', m.close);
    $('#cform', m.el).addEventListener('submit', async (e) => {
      e.preventDefault();
      try { await api('/api/admin/categories/' + c.id, 'PUT', { name: $('#c-name', m.el).value }); m.close(); toast('Saved', 'ok'); await menu(); }
      catch (err) { $('#c-err', m.el).textContent = err.message; }
    });
    m.el.addEventListener('click', async (e) => {
      const mv = e.target.closest('[data-mv]');
      if (mv) { await attempt(async () => { await api(`/api/admin/categories/${c.id}/move`, 'POST', { dir: +mv.dataset.mv }); m.close(); await menu(); }); }
      if (e.target.closest('[data-del]')) {
        if (!(await confirmBox(`Delete ${c.name}?`, 'Delete', true))) return;
        try { await api('/api/admin/categories/' + c.id, 'DELETE'); m.close(); toast('Category deleted', 'ok'); await menu(); } catch (err) { $('#c-err', m.el).textContent = err.message; }
      }
    });
  }

  function itemDialog(item, categoryId) {
    const isEdit = !!item.id;
    let image;                         // undefined = keep, '' = remove, 'data:...' = new photo
    const m = modal(`<h2>${isEdit ? 'Edit item' : 'New item'}</h2><form class="stack" id="itemform">
      <div class="photo-pick"><div class="preview" id="i-preview">${item.image_v ? `<img src="${U('/img/' + item.id)}?v=${item.image_v}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:14px">` : 'No photo'}</div>
        <div class="stack" style="gap:8px"><label class="btn sm" for="i-file" style="cursor:pointer">Choose photo</label><input type="file" id="i-file" accept="image/*" class="sr"><button type="button" class="btn sm ghost danger" id="i-rmphoto" ${item.image_v ? '' : 'hidden'}>Remove photo</button></div></div>
      <label class="field">Name<input type="text" id="i-name" maxlength="60" value="${esc(item.name || '')}" required></label>
      <div class="form-grid two"><label class="field">Price (₹)<input type="number" id="i-price" min="0" max="100000" step="1" inputmode="numeric" value="${item.price ?? ''}" required></label>
      <label class="field">Type<select id="i-diet"><option value="">Not marked</option><option value="veg" ${item.diet === 'veg' ? 'selected' : ''}>Vegetarian</option><option value="nonveg" ${item.diet === 'nonveg' ? 'selected' : ''}>Non-vegetarian</option></select></label></div>
      <label class="field">Category<select id="i-cat">${cats.map((c) => `<option value="${c.id}" ${c.id === categoryId ? 'selected' : ''}>${esc(c.name)}</option>`).join('')}</select></label>
      <label class="field">Short description (optional)<input type="text" id="i-desc" maxlength="160" value="${esc(item.description || '')}" placeholder="e.g. Served with raita and gravy"></label>
      <div class="err" id="i-err" role="alert"></div>
      <div class="btns"><button type="button" class="btn grow" data-x>Cancel</button><button class="btn primary grow" id="i-save">Save</button></div>
      ${isEdit ? `<div class="btns"><button type="button" class="btn grow" data-mv="-1">Move up ↑</button><button type="button" class="btn grow" data-mv="1">Move down ↓</button></div><button type="button" class="btn danger block" data-del>Delete item</button>` : ''}</form>`);
    const err = (t) => { $('#i-err', m.el).textContent = t; };
    $('[data-x]', m.el).addEventListener('click', m.close);
    $('#i-file', m.el).addEventListener('change', async (e) => {
      const f = e.target.files[0]; if (!f) return;
      err(''); $('#i-preview', m.el).textContent = 'Preparing…';
      try {
        image = await compressImage(f);
        $('#i-preview', m.el).innerHTML = `<img src="${image}" alt="" style="width:100%;height:100%;object-fit:cover;border-radius:14px">`;
        $('#i-rmphoto', m.el).hidden = false;
      } catch (ex) { image = undefined; $('#i-preview', m.el).textContent = item.image_v ? 'Photo kept' : 'No photo'; err(ex.message); }
    });
    $('#i-rmphoto', m.el).addEventListener('click', () => { image = ''; $('#i-preview', m.el).textContent = 'Photo removed'; $('#i-rmphoto', m.el).hidden = true; });
    $('#itemform', m.el).addEventListener('submit', async (e) => {
      e.preventDefault(); $('#i-save', m.el).disabled = true;
      const body = { name: $('#i-name', m.el).value, price: $('#i-price', m.el).value, diet: $('#i-diet', m.el).value, category_id: +$('#i-cat', m.el).value, description: $('#i-desc', m.el).value };
      if (image !== undefined) body.image = image;
      try { await (isEdit ? api('/api/admin/items/' + item.id, 'PUT', body) : api('/api/admin/items', 'POST', body)); m.close(); toast('Saved', 'ok'); await menu(); }
      catch (ex) { err(ex.message); $('#i-save', m.el).disabled = false; }
    });
    m.el.addEventListener('click', async (e) => {
      const mv = e.target.closest('[data-mv]');
      if (mv) { await attempt(async () => { await api(`/api/admin/items/${item.id}/move`, 'POST', { dir: +mv.dataset.mv }); toast('Moved', 'ok'); await menu(); }); }
      if (e.target.closest('[data-del]')) {
        if (!(await confirmBox(`Delete ${item.name}?`, 'Delete', true))) return;
        try { await api('/api/admin/items/' + item.id, 'DELETE'); m.close(); toast('Item deleted', 'ok'); await menu(); } catch (ex) { err(ex.message); }
      }
    });
  }

  view.addEventListener('click', (e) => {
    const b = e.target.closest('[data-act]'); if (!b || tab !== 'menu') return;
    const id = +b.dataset.id, act = b.dataset.act;
    if (act === 'item-avail') {
      attempt(async () => { try { await api(`/api/menu/${id}/available`, 'POST', { available: b.checked }); } finally { await menu(); } });
      return;
    }
    attempt(async () => {
      if (act === 'add-cat') { const n = await askText('New category', 'e.g. Biryani', 'Add'); if (n) { await api('/api/admin/categories', 'POST', { name: n }); await menu(); } }
      else if (act === 'cat-edit') categoryDialog(cats.find((x) => x.id === id));
      else if (act === 'item-edit') { const i = findItem(id); itemDialog(i, i.category_id); }
      else if (act === 'item-add') itemDialog({}, id || (cats[0] && cats[0].id));
    });
  });

  /* ======================= STAFF ======================= */
  const ROLE_LABEL = { owner: 'Owner (everything)', cashier: 'Cashier (counter, payments, hand over)', kitchen: 'Kitchen (cook and mark ready)' };
  let users = [], me = 0;

  async function staff() { const d = await api('/api/admin/users'); users = d.users; me = d.me; paintStaff(); }

  function paintStaff() {
    view.innerHTML = `<div class="spread mb"><p class="muted small">Give each person their own login so every payment and change shows who did it.</p><button class="btn primary" data-sact="add">Add staff</button></div>
      <div class="table-wrap"><table><thead><tr><th>Username</th><th>Role</th><th>Status</th><th></th></tr></thead><tbody>${users.map((u) => `<tr><td><b>${esc(u.username)}</b>${u.id === me ? ' <span class="pill">You</span>' : ''}</td><td>${u.role}</td><td>${u.active ? '<span class="pill ok">Active</span>' : '<span class="pill">Disabled</span>'}</td><td class="right"><button class="btn sm" data-sact="edit" data-id="${u.id}">Edit</button></td></tr>`).join('')}</tbody></table></div>`;
  }

  function userDialog(u) {
    const isEdit = !!u, self = isEdit && u.id === me;
    const m = modal(`<h2>${isEdit ? 'Edit ' + esc(u.username) : 'Add staff'}</h2><form class="stack" id="uform">
      ${isEdit ? '' : '<label class="field">Username<input type="text" id="u-name" maxlength="30" autocapitalize="none" required></label>'}
      <label class="field">Role<select id="u-role" ${self ? 'disabled' : ''}>${Object.entries(ROLE_LABEL).map(([k, v]) => `<option value="${k}" ${u && u.role === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
      <label class="field">${isEdit ? 'New password (leave empty to keep)' : 'Password (at least 6 characters)'}<input type="password" id="u-pass" autocomplete="new-password" ${isEdit ? '' : 'required'}></label>
      ${isEdit ? `<label class="check"><input type="checkbox" id="u-active" ${u.active ? 'checked' : ''} ${self ? 'disabled' : ''}> Can sign in</label>` : ''}
      <div class="err" id="u-err" role="alert"></div>
      <div class="btns"><button type="button" class="btn grow" data-x>Cancel</button><button class="btn primary grow">Save</button></div></form>`);
    $('[data-x]', m.el).addEventListener('click', m.close);
    $('#uform', m.el).addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        if (isEdit) {
          const body = { role: $('#u-role', m.el).value, active: $('#u-active', m.el).checked };
          if ($('#u-pass', m.el).value) body.password = $('#u-pass', m.el).value;
          await api('/api/admin/users/' + u.id, 'PUT', body);
        } else await api('/api/admin/users', 'POST', { username: $('#u-name', m.el).value, role: $('#u-role', m.el).value, password: $('#u-pass', m.el).value });
        m.close(); toast('Saved', 'ok'); await staff();
      } catch (err) { $('#u-err', m.el).textContent = err.message; }
    });
  }

  view.addEventListener('click', (e) => {
    const b = e.target.closest('[data-sact]'); if (!b || tab !== 'staff') return;
    if (b.dataset.sact === 'add') userDialog(null);
    else userDialog(users.find((x) => x.id === +b.dataset.id));
  });

  /* ======================= SETTINGS ======================= */
  async function settings() {
    const s = (await api('/api/admin/settings')).settings;
    const f = (key, label, attrs = '', hint = '') => `<label class="field">${label}<input type="text" data-s="${key}" value="${esc(s[key])}" ${attrs}>${hint ? `<span class="muted tiny" style="font-weight:400">${hint}</span>` : ''}</label>`;
    view.innerHTML = `<form id="sform" class="stack">
      <section class="card stack"><h2>Restaurant</h2>${f('restaurant_name', 'Restaurant name', 'maxlength="60"')}
        <label class="check"><input type="checkbox" data-s="accepting_orders" ${s.accepting_orders === '1' ? 'checked' : ''}> Accept phone orders (turn off when you are closed or too busy)</label></section>
      <section class="card stack"><h2>Payments</h2>
        <label class="check"><input type="radio" name="pm" value="demo" ${s.payment_mode === 'demo' ? 'checked' : ''}><span>Demo mode<br><span class="muted small" style="font-weight:400">Phone orders are marked paid instantly. For testing and showing the app only. No real money moves.</span></span></label>
        <label class="check"><input type="radio" name="pm" value="upi_manual" ${s.payment_mode === 'upi_manual' ? 'checked' : ''}><span>UPI to your account<br><span class="muted small" style="font-weight:400">Customer pays your UPI ID from their UPI app. Cashier confirms the money arrived, then cooking starts.</span></span></label>
        <div class="form-grid two">${f('upi_vpa', 'Your UPI ID', 'placeholder="name@bank" autocapitalize="none"')}${f('upi_name', 'Name shown on UPI', 'maxlength="40"')}</div></section>
      <section class="card stack"><h2>Waiting time</h2><p class="muted small">Shown to phone customers: base minutes plus extra minutes for each order already in the kitchen.</p>
        <div class="form-grid two"><label class="field">Base minutes<input type="number" data-s="eta_base" min="0" max="120" value="${esc(s.eta_base)}"></label><label class="field">Extra minutes per waiting order<input type="number" data-s="eta_per_order" min="0" max="30" value="${esc(s.eta_per_order)}"></label></div></section>
      <section class="card stack"><h2>WhatsApp message</h2><label class="field">Message sent when an order is ready<textarea data-s="whatsapp_template" maxlength="300">${esc(s.whatsapp_template)}</textarea><span class="muted tiny" style="font-weight:400">You can use {name}, {tok} and {restaurant}. Staff tap a button to open WhatsApp with this message ready to send.</span></label></section>
      <section class="card stack"><h2>Receipt</h2>${f('receipt_address', 'Address', 'maxlength="160"')}${f('receipt_phone', 'Phone number', 'maxlength="30"')}${f('receipt_footer', 'Footer line', 'maxlength="120"')}</section>
      <div class="err" id="s-err" role="alert"></div><button class="btn primary block" id="s-save">Save settings</button></form>
      <section class="card stack mt"><h2>Your password</h2><div class="form-grid two"><label class="field">Current password<input type="password" id="pw-cur" autocomplete="current-password"></label><label class="field">New password<input type="password" id="pw-new" autocomplete="new-password"></label></div><button class="btn" id="pw-save">Change password</button></section>
      <section class="card stack mt"><h2>Backup</h2><p class="muted small">Download all your orders, menu and staff as one file. Keep a copy somewhere safe every week.</p><a class="btn" href="${U('/api/admin/backup')}">Download backup</a></section>`;
    $('#sform').addEventListener('submit', async (e) => {
      e.preventDefault(); $('#s-err').textContent = '';
      const body = {};
      $$('[data-s]').forEach((el) => { body[el.dataset.s] = el.type === 'checkbox' ? el.checked : el.value; });
      body.payment_mode = $('input[name=pm]:checked').value;
      try { await api('/api/admin/settings', 'PUT', body); toast('Settings saved', 'ok'); } catch (err) { $('#s-err').textContent = err.message; }
    });
    $('#pw-save').addEventListener('click', () => attempt(async () => { await api('/api/auth/password', 'POST', { current: $('#pw-cur').value, new: $('#pw-new').value }); $('#pw-cur').value = $('#pw-new').value = ''; toast('Password changed', 'ok'); }));
  }

  /* ======================= QR CODES ======================= */
  async function qr() {
    const origin = location.origin + BASE;       // the restaurant's own address, e.g. https://site/r/betty
    view.innerHTML = `<div class="card stack"><h2>Address of this computer</h2>
      <p class="muted small">Phones and TVs must open this address. On your laptop it usually looks like <b>http://192.168.1.10:5000</b> (run <b>ipconfig</b> and read "IPv4 Address"). If you see 127.0.0.1 or localhost below, replace it with that address.</p>
      <input type="text" id="base" value="${esc(origin)}" aria-label="Address"></div>
      <div class="form-grid two mt" style="align-items:start" id="qrs"></div>`;
    const draw = () => {
      const base = $('#base').value.trim().replace(/\/+$/, '');
      const items = [['Customer ordering', base + '/order', 'Put this on the wall and on every table or counter. Customers scan, order and pay.'], ['Token board', base + '/board', 'Open this on the TV near the parcel counter.']];
      $('#qrs').innerHTML = items.map(([t, url, help], i) => `<div class="card center stack"><h2>${t}</h2><div id="qr${i}" style="display:inline-block;margin:0 auto;padding:12px;background:#fff;border-radius:12px"></div><p class="mono small" style="word-break:break-all">${esc(url)}</p><p class="muted small">${help}</p><button class="btn no-print" onclick="window.print()">Print this page</button></div>`).join('');
      items.forEach(([t, url], i) => {
        const el = $('#qr' + i);
        if (window.QRCode) new QRCode(el, { text: url, width: 220, height: 220, correctLevel: QRCode.CorrectLevel.M });
        else el.innerHTML = '<p class="small">QR library could not load. Connect to the internet once, or type the address above into the phone.</p>';
      });
    };
    $('#base').addEventListener('input', draw);
    if (window.QRCode) draw(); else { draw(); window.addEventListener('load', draw, { once: true }); }
  }


  /* ======================= DASHBOARD (who uses the app) ======================= */
  async function dashboard() {
    const d = await api('/api/admin/business'), c = d.customers, o = d.orders, r = d.ratings;
    const kpi = (label, value, sub = '') => `<div class="kpi"><small>${label}</small><b>${value}</b>${sub ? `<div class="muted tiny">${sub}</div>` : ''}</div>`;
    const bars = (key, label) => {
      const max = Math.max(...d.trend.map((t) => t[key]), 1);
      return `<div class="card"><h3>${label}</h3><div style="display:flex;align-items:flex-end;gap:3px;height:90px;margin-top:8px" role="img" aria-label="${label}, last 14 days">${d.trend.map((t) =>
        `<div style="flex:1;background:var(--brand);border-radius:3px 3px 0 0;height:${Math.max(3, t[key] / max * 100)}%;opacity:${t[key] ? 1 : .25}" title="${dmy(t.day)}: ${t[key]}"></div>`).join('')}</div>
        <div class="spread muted tiny" style="margin-top:4px"><span>${dmy(d.trend[0].day)}</span><span>Total ${d.trend.reduce((s, t) => s + t[key], 0)}</span><span>Today</span></div></div>`;
    };
    const dist = [5, 4, 3, 2, 1].map((n) => { const v = r.distribution[n], pct = r.count ? v / r.count * 100 : 0;
      return `<div class="spread small" style="gap:8px"><span style="width:30px">${n} ★</span><div class="hbar grow"><div class="fill" style="width:${pct}%"></div></div><span style="width:28px;text-align:right">${v}</span></div>`; }).join('');
    view.innerHTML = `<div class="kpis">
        ${kpi('Customers', c.total, `${c.new_7d} new this week`)}${kpi('Ordered in 7 days', c.active_7d, `${c.new_30d} new in 30 days`)}
        ${kpi('Repeat customers', c.repeat_percent + '%', `${c.repeat} of ${c.total} customers`)}${kpi('Rating', r.avg ? r.avg + ' ★' : 'n/a', `${r.count} rating${r.count === 1 ? '' : 's'}`)}
        ${kpi('Orders (all time)', o.total, `${o.app} app · ${o.counter} counter`)}${kpi('Orders with an account', o.linked_percent + '%', `${o.linked} of ${o.total}`)}
        ${kpi('Average order', money(o.average), `${money(o.revenue)} sold in total`)}${kpi('Staff logins', Object.values(d.staff).reduce((a, b) => a + b, 0), Object.entries(d.staff).map(([k, v]) => `${v} ${k}`).join(', '))}</div>
      <div class="form-grid two mt" style="align-items:start">${bars('signups', 'New customers per day (first order)')}${bars('orders', 'Orders per day')}</div>
      <div class="form-grid two mt" style="align-items:start"><div class="card"><h3>Ratings</h3><div class="stack" style="margin-top:8px">${r.count ? dist : '<p class="muted small">No ratings yet. Customers can rate an order after pickup.</p>'}</div></div>
        <div class="card"><div class="spread"><h3>Best customers</h3><button class="btn sm" data-go="customers">All customers</button></div>${d.top_customers.length ? d.top_customers.map((t, i) =>
          `<div class="kv"><span>${i + 1}. ${esc(t.name)} <span class="muted small">· ${t.orders} order${t.orders === 1 ? '' : 's'}</span></span><b class="price">${money(t.spent)}</b></div>`).join('') : '<p class="muted small">Your best customers appear here after the first orders.</p>'}</div></div>
      <p class="muted small mt">Customers here are people with a Flotoken account who ordered from you. Walk-in orders without an account appear in Reports.</p>`;
    view.onclick = (e) => { const b = e.target.closest('[data-go]'); if (b) show(b.dataset.go); };
  }

  /* ======================= CUSTOMERS ======================= */
  let cq = '', csort = 'recent', ctimer = null;
  async function customers() {
    view.innerHTML = `<div class="card flat mb"><div class="form-grid two"><label class="field">Search name or mobile<input type="search" id="cq" value="${esc(cq)}" placeholder="e.g. Ravi or 98450"></label>
        <label class="field">Sort by<select id="csort">${[['recent', 'Latest activity'], ['spent', 'Most spent'], ['orders', 'Most orders'], ['joined', 'Newest']].map(([k, n]) => `<option value="${k}" ${csort === k ? 'selected' : ''}>${n}</option>`).join('')}</select></label></div>
        <div class="spread" style="margin-top:8px"><span class="muted small" id="ccount"></span><a class="btn sm" href="${U('/api/customers.csv')}" download>Download CSV</a></div></div>
      <div class="card" style="padding:0"><div class="tablewrap" id="clist"></div></div>`;
    const load = async () => {
      const d = await attempt(() => api(`/api/customers?q=${encodeURIComponent(cq)}&sort=${csort}`)); if (!d || !$('#clist')) return;
      $('#ccount').textContent = `${d.customers.length} shown · ${d.total} total`;
      $('#clist').innerHTML = d.customers.length ? `<table><thead><tr><th>Name</th><th>Mobile</th><th>Orders</th><th>Spent</th><th>Last order</th></tr></thead><tbody>${d.customers.map((c) =>
        `<tr data-cid="${c.id}" style="cursor:pointer"><td><b>${esc(c.name)}</b></td><td class="mono">${esc(c.phone)}</td><td>${c.orders}</td><td class="price">${money(c.spent)}</td><td>${c.last_order_at ? dmy(c.last_order_at) : '<span class="muted">none</span>'}</td></tr>`).join('')}</tbody></table>`
        : `<div class="empty"><b>${cq ? 'No match' : 'No customers yet'}</b>${cq ? 'Try fewer letters or digits.' : 'Customers appear here when they sign up in the app.'}</div>`;
    };
    $('#cq').addEventListener('input', (e) => { cq = e.target.value; clearTimeout(ctimer); ctimer = setTimeout(load, 250); });
    $('#csort').addEventListener('change', (e) => { csort = e.target.value; load(); });
    $('#clist').addEventListener('click', (e) => { const r = e.target.closest('[data-cid]'); if (r) customerDialog(+r.dataset.cid); });
    await load();
  }

  async function customerDialog(id) {
    const d = await attempt(() => api('/api/customers/' + id)); if (!d) return;
    const c = d.customer, stars = (n) => '★'.repeat(n) + '☆'.repeat(5 - n);
    const m = modal(`<h2>${esc(c.name)}</h2>
      <div class="kv"><span class="muted">Mobile</span><b class="mono">${esc(c.phone)}</b></div>
      <div class="kv"><span class="muted">First order</span><span>${dmy(c.first_order_at)}</span></div>
      <div class="kv"><span class="muted">Last order</span><span>${dmy(c.last_order_at)}</span></div>
      <div class="kv"><span class="muted">Orders · spent</span><b>${c.orders} · ${money(c.spent)}</b></div>
      ${d.avg_rating ? `<div class="kv"><span class="muted">Average rating</span><span>${d.avg_rating} ★</span></div>` : ''}
      ${d.favourites.length ? `<div class="kv"><span class="muted">Favourites</span><span>${d.favourites.map((f) => esc(f.name)).join(', ')}</span></div>` : ''}
      <h3 style="margin-top:10px">Recent orders</h3>
      <div style="max-height:220px;overflow:auto">${d.orders.length ? d.orders.map((o) => `<div class="kv small" style="border-top:1px solid var(--line)"><span>${dmy(o.created_at)} · Token ${o.tok}<br><span class="muted">${o.items.map((i) => `${i.qty}× ${esc(i.name)}`).join(', ')}</span>${o.rating ? `<br><span style="color:#E2A100">${stars(o.rating)}</span> ${esc(o.rating_note || '')}` : ''}</span><b class="price">${o.status === 'cancelled' ? 'cancelled' : money(o.total)}</b></div>`).join('') : '<p class="muted small">No orders yet.</p>'}</div>
      <div class="btns" style="margin-top:12px"><button class="btn grow primary" data-close>Close</button></div>`);
    $('[data-close]', m.el).addEventListener('click', () => m.close());
  }

  /* ======================= PLAN ======================= */
  async function plan() { view.innerHTML = '<div id="plans"></div><p class="muted small mt">Public page: <a href="/pricing">/pricing</a></p>'; await Pricing.mount($('#plans')); }

  show((location.hash || '').slice(1) && TABS.some((t) => t[0] === location.hash.slice(1)) ? location.hash.slice(1) : 'dashboard');
})();
