/* Shared helpers used by every screen. */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const money = (n) => '₹' + Number(n || 0).toLocaleString('en-IN');
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const hm = (t) => new Date(t).toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit', hour12: true });
const dmy = (t) => new Date(t).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
const todayIST = () => new Date(Date.now() + 5.5 * 3600e3).toISOString().slice(0, 10);
const minutesAgo = (t) => Math.max(0, Math.floor((Date.now() - t) / 60000));

/** JSON fetch. Throws Error(message) with .status and .data on failure. Sends the user to /login on 401. */
async function api(url, method = 'GET', body) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (method !== 'GET') { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body || {}); }
  let res;
  try { res = await fetch(url, opts); } catch (e) { const err = new Error('No connection to the server. Check Wi-Fi and try again.'); err.offline = true; throw err; }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (res.status === 401 && !url.startsWith('/api/auth/') && !url.startsWith('/api/public/') && !url.startsWith('/api/customer/')) {   // customers have their own login, handled in order.js
      location.href = '/login?next=' + encodeURIComponent(location.pathname);
    }
    const err = new Error(data.error || 'Something went wrong');
    err.status = res.status; err.data = data; throw err;
  }
  return data;
}

/** Run an async action and show any error as a toast. Returns the result or undefined. */
async function attempt(fn) {
  try { return await fn(); } catch (e) { toast(e.message, 'bad'); }
}

function toast(text, kind = '') {
  let box = $('#toasts');
  if (!box) { box = document.createElement('div'); box.id = 'toasts'; box.setAttribute('role', 'status'); box.setAttribute('aria-live', 'polite'); document.body.appendChild(box); }
  const el = document.createElement('div');
  el.className = 'toast ' + kind; el.textContent = text; box.appendChild(el);
  setTimeout(() => el.remove(), kind === 'bad' ? 5000 : 3200);
}

/** Open a modal with HTML content. Returns { el, close }. Closes on backdrop tap or Escape. */
function modal(html) {
  const back = document.createElement('div');
  back.className = 'modal-back';
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true">${html}</div>`;
  const close = () => { back.remove(); document.removeEventListener('keydown', onKey); };
  const onKey = (e) => { if (e.key === 'Escape') close(); };
  back.addEventListener('click', (e) => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey);
  document.body.appendChild(back);
  const first = $('input,textarea,select,button', back); if (first && first.tagName !== 'BUTTON') first.focus();
  return { el: back.firstElementChild, close };
}

/** Promise-based yes/no dialog (the browser's confirm() is easy to miss on phones). */
function confirmBox(message, okLabel = 'Confirm', danger = false) {
  return new Promise((resolve) => {
    const m = modal(`<h2>${esc(message)}</h2><div class="btns mt"><button class="btn grow" data-r="0">Cancel</button><button class="btn grow ${danger ? 'danger solid' : 'primary'}" data-r="1">${esc(okLabel)}</button></div>`);
    m.el.addEventListener('click', (e) => { const b = e.target.closest('[data-r]'); if (b) { m.close(); resolve(b.dataset.r === '1'); } });
  });
}

/** Ask for a line of text (e.g. cancel reason). Resolves to the string, or null if cancelled. */
function askText(title, placeholder = '', okLabel = 'OK') {
  return new Promise((resolve) => {
    const m = modal(`<h2>${esc(title)}</h2><input type="text" id="ask-input" maxlength="80" placeholder="${esc(placeholder)}"><div class="btns mt"><button class="btn grow" data-r="0">Back</button><button class="btn grow primary" data-r="1">${esc(okLabel)}</button></div>`);
    const input = $('#ask-input', m.el);
    const done = (ok) => { m.close(); resolve(ok ? input.value.trim() : null); };
    m.el.addEventListener('click', (e) => { const b = e.target.closest('[data-r]'); if (b) done(b.dataset.r === '1'); });
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') done(true); });
  });
}

/** Call fn now and then every `ms`. Pauses while the tab is hidden and refreshes when it becomes visible. */
function poll(fn, ms = 2500) {
  let busy = false;
  const run = async () => { if (busy || document.hidden) return; busy = true; try { await fn(); } catch (e) { /* offline: try again next tick */ } busy = false; };
  run(); setInterval(run, ms);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) run(); });
  return run;
}

/** Short beep (needs one earlier tap on the page, which the browser requires). */
let audioCtx;
function beep(times = 1, freq = 880) {
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    for (let i = 0; i < times; i++) {
      const o = audioCtx.createOscillator(), g = audioCtx.createGain();
      o.frequency.value = freq; o.connect(g); g.connect(audioCtx.destination);
      const t = audioCtx.currentTime + i * 0.28;
      g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.35, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.22);
      o.start(t); o.stop(t + 0.24);
    }
  } catch (e) { /* sound not available */ }
}

function dietIcon(d) { return d ? `<span class="diet ${d}" title="${d === 'veg' ? 'Vegetarian' : 'Non-vegetarian'}"></span>` : ''; }

/** Menu rows with Add / stepper controls. cart = { itemId: qty }. */
function menuRowsHtml(items, cart, opts = {}) {
  return items.map((m) => {
    const q = cart[m.id] || 0;
    const control = !m.available ? '<span class="pill bad">Sold out</span>'
      : q ? `<div class="stepper"><button data-dec="${m.id}" aria-label="Remove one ${esc(m.name)}">−</button><span class="q">${q}</span><button data-inc="${m.id}" aria-label="Add one ${esc(m.name)}">+</button></div>`
        : `<button class="btn sm add-btn" data-inc="${m.id}">Add</button>`;
    const photo = opts.photos && m.image_v ? `<img class="thumb" src="/img/${m.id}?v=${m.image_v}" alt="" width="64" height="64" loading="lazy">` : '';
    const desc = opts.photos && m.description ? `<div class="desc muted small">${esc(m.description)}</div>` : '';
    return `<div class="menu-row ${m.available ? '' : 'soldout'}">${photo}<div class="grow"><div class="name">${dietIcon(m.diet)}${esc(m.name)}</div><div class="price muted small">${money(m.price)}</div>${desc}</div>${control}</div>`;
  }).join('');
}

/** Wire +/- taps inside root to the cart object, then call onChange(). */
function bindCart(root, cart, onChange) {
  root.addEventListener('click', (e) => {
    const inc = e.target.closest('[data-inc]'), dec = e.target.closest('[data-dec]');
    if (inc) { const id = inc.dataset.inc; cart[id] = Math.min(50, (cart[id] || 0) + 1); }
    else if (dec) { const id = dec.dataset.dec; cart[id] = Math.max(0, (cart[id] || 0) - 1); if (!cart[id]) delete cart[id]; }
    else return;
    onChange();
  });
}
/** Empty the cart in place (click handlers hold a reference to this object, so never reassign it). */
const clearCart = (cart) => Object.keys(cart).forEach((k) => delete cart[k]);
const cartList = (cart) => Object.keys(cart).filter((k) => cart[k] > 0).map((k) => ({ id: +k, q: cart[k] }));
function flatItems(categories) { return categories.flatMap((c) => c.items); }
function cartTotal(cart, categories) { return flatItems(categories).reduce((s, m) => s + (cart[m.id] || 0) * m.price, 0); }
function cartCount(cart) { return Object.values(cart).reduce((s, q) => s + q, 0); }

/** Opens WhatsApp with the ready message prefilled (works on phones and WhatsApp Web, no API needed). */
function whatsappUrl(order, template) {
  let digits = String(order.phone || '').replace(/\D/g, '');
  if (digits.length === 10) digits = '91' + digits;
  const text = (template || '').replace('{name}', order.customer_name || 'there').replace('{tok}', order.tok)
    .replace('{restaurant}', (window.APP && window.APP.restaurant) || '');
  return `https://wa.me/${digits}?text=${encodeURIComponent(text)}`;
}

async function logout() { await attempt(() => api('/api/auth/logout', 'POST')); location.href = '/login'; }
document.addEventListener('click', (e) => { if (e.target.closest('[data-logout]')) logout(); });

/** Offline banner so staff notice a dropped connection immediately. */
window.addEventListener('offline', () => toast('You are offline. Changes will not save.', 'bad'));
window.addEventListener('online', () => toast('Back online', 'ok'));

/** Shrink a photo chosen on the phone to a small JPEG data URL (about 30-120 KB) before uploading. */
async function compressImage(file, maxSide = 640, maxBytes = 150 * 1024) {
  if (!file || !file.type.startsWith('image/')) throw new Error('Please choose an image file');
  let bmp;
  try { bmp = await createImageBitmap(file); }
  catch (e) {
    bmp = await new Promise((resolve, reject) => { const img = new Image(); img.onload = () => resolve(img); img.onerror = () => reject(new Error('This photo could not be opened')); img.src = URL.createObjectURL(file); });
  }
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bmp.width * scale)); canvas.height = Math.max(1, Math.round(bmp.height * scale));
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
  for (let q = 0.85; q >= 0.4; q -= 0.1) {
    const url = canvas.toDataURL('image/jpeg', q);
    if (url.length * 0.75 <= maxBytes) return url;
  }
  throw new Error('This photo is too detailed. Try another one.');
}

/* ---------- installable app ---------- */
let deferredInstall = null;
const isStandalone = () => matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const isIOS = () => /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
function paintInstall() {
  const show = !isStandalone() && (deferredInstall || isIOS());
  $$('[data-install]').forEach((b) => { b.hidden = !show; });
}
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); deferredInstall = e; paintInstall(); });
window.addEventListener('appinstalled', () => { deferredInstall = null; paintInstall(); toast('App installed', 'ok'); });
document.addEventListener('click', async (e) => {
  if (!e.target.closest('[data-install]')) return;
  if (deferredInstall) {
    const ev = deferredInstall; deferredInstall = null; paintInstall();
    ev.prompt(); try { await ev.userChoice; } catch (x) { /* ignore */ }
  } else if (isIOS()) {
    const m = modal('<h2>Install this app</h2><p>On iPhone or iPad: tap the <b>Share</b> button in Safari, then choose <b>Add to Home Screen</b>.</p><div class="btns mt"><button class="btn primary grow" data-x>Got it</button></div>');
    $('[data-x]', m.el).addEventListener('click', m.close);
  }
});
let installQueued = false;
new MutationObserver(() => { if (!installQueued) { installQueued = true; requestAnimationFrame(() => { installQueued = false; paintInstall(); }); } })
  .observe(document.body, { childList: true, subtree: true });
paintInstall();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js').catch(() => { /* needs https or localhost */ }); });
}
