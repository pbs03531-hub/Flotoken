/* Flotoken owner dashboard: every restaurant, every customer, usage and plans. */
(() => {
  const root = $('#root');
  let tab = 'overview', data = null;
  const TABS = [['overview', 'Overview'], ['restaurants', 'Restaurants'], ['customers', 'Customers'], ['account', 'Account']];
  const kpi = (l, v, sub) => `<div class="kpi"><small>${esc(l)}</small><b>${v}</b>${sub ? `<span class="muted tiny">${esc(sub)}</span>` : ''}</div>`;
  const plural = (n, a, b) => n + ' ' + (n === 1 ? a : b);
  const ago = (t) => { if (!t) return 'never'; const m = minutesAgo(t); return m < 60 ? plural(m, 'min', 'mins') + ' ago' : m < 1440 ? plural(Math.floor(m / 60), 'hour', 'hours') + ' ago' : dmy(t); };
  const origin = location.origin;

  /* ---------- sign in / first set up ---------- */
  function paintAuth(needsSetup) {
    root.innerHTML = `<div class="auth-card stack" style="margin:8vh auto 0"><div class="row"><span class="brand"><i>F</i></span><div><h1>${needsSetup ? 'Set up Flotoken' : 'Flotoken owner'}</h1><p class="muted small">${needsSetup ? 'Create your owner login. Only you will use it.' : 'Log in to see every restaurant.'}</p></div></div>
      <form class="card stack" id="f"><label class="field">Username<input id="u" autocomplete="username" autocapitalize="none" required></label>
      <label class="field">Password${needsSetup ? ' (at least 6 characters)' : ''}<input id="p" type="password" autocomplete="${needsSetup ? 'new-password' : 'current-password'}" required></label>
      <div class="err" id="err" role="alert"></div><button class="btn primary block">${needsSetup ? 'Create owner login' : 'Log in'}</button></form>
      <p class="muted small center"><a href="/">Back to start</a></p></div>`;
    $('#f').addEventListener('submit', async (e) => {
      e.preventDefault(); $('#err').textContent = '';
      try { await api(needsSetup ? '/api/platform/setup' : '/api/platform/login', 'POST', { username: $('#u').value, password: $('#p').value }); load(); } catch (x) { $('#err').textContent = x.message; }
    });
  }

  /* ---------- shell ---------- */
  function shell(body) {
    root.innerHTML = `<div class="row" style="justify-content:space-between;margin-bottom:12px"><a class="brand" href="/"><i>F</i><span>Flotoken owner</span></a><button class="btn sm ghost" id="out">Sign out</button></div>
      <div class="seg mb" id="tabs" role="tablist">${TABS.map(([k, n]) => `<button role="tab" data-tab="${k}" aria-selected="${tab === k}">${n}</button>`).join('')}</div><div id="view">${body}</div>`;
    $('#tabs').addEventListener('click', (e) => { const b = e.target.closest('[data-tab]'); if (b) { tab = b.dataset.tab; render(); } });
    $('#out').addEventListener('click', async () => { await attempt(() => api('/api/platform/logout', 'POST')); location.href = '/'; });
  }

  const planPill = (r) => r.status === 'suspended' ? '<span class="pill bad">Suspended</span>' : r.expired ? '<span class="pill bad">Expired</span>' : r.expires_soon ? '<span class="pill warn">Ends soon</span>' : `<span class="pill ${r.plan === 'trial' ? 'info' : 'ok'}">${esc(r.plan)}</span>`;

  function overviewHtml() {
    const t = data.totals, tr = data.trend, mx = (k) => Math.max(1, ...tr.map((d) => d[k]));
    const bars = (k) => `<div class="bars" aria-hidden="true">${tr.map((d) => `<div class="${d[k] ? '' : 'zero'}" style="height:${Math.max(2, d[k] / mx(k) * 100)}%" title="${d.day}: ${d[k]}"></div>`).join('')}</div>`;
    return `<div class="kpis" style="grid-template-columns:repeat(auto-fit,minmax(150px,1fr))">
        ${kpi('Restaurants', t.restaurants, `${t.active} active, ${t.suspended} suspended`)}${kpi('Paying', t.paying, `${t.trial} on trial`)}${kpi('Monthly income', money(t.mrr), 'before GST')}${kpi('Plans expired', t.expired)}
        ${kpi('Customers', t.customers, `${t.customers_7d} new in 7 days`)}${kpi('Logged in 7 days', t.customers_active_7d)}${kpi('Orders today', t.orders_today)}${kpi('Orders in 30 days', t.orders_30d, money(t.sales_30d) + ' sales')}${kpi('Orders ever', t.orders)}</div>
      <div class="cards mt" style="grid-template-columns:repeat(auto-fit,minmax(280px,1fr))"><div class="card"><h2>Orders per day</h2>${bars('orders')}</div><div class="card"><h2>New customers per day</h2>${bars('signups')}</div></div>
      <h2 class="mt">Restaurants</h2>${restaurantTable()}`;
  }

  function restaurantTable() {
    const rs = data.restaurants;
    if (!rs.length) return '<div class="empty"><b>No restaurants yet</b>Add the first one in the Restaurants tab.</div>';
    return `<div class="table-wrap"><table><thead><tr><th>Restaurant</th><th>Plan</th><th class="r">Orders 30d</th><th class="r">Sales 30d</th><th class="r">Customers</th><th>Last order</th></tr></thead><tbody>${rs.map((r) => `<tr><td><b>${esc(r.name)}</b><br><span class="muted tiny mono">/r/${esc(r.slug)}</span></td><td>${planPill(r)}</td><td class="r num">${r.orders_30d}</td><td class="r num">${money(r.sales_30d)}</td><td class="r num">${r.customers}</td><td class="small">${ago(r.last_order_at)}</td></tr>`).join('')}</tbody></table></div>`;
  }

  /* ---------- restaurants ---------- */
  function restaurantsHtml() {
    const rs = data.restaurants;
    return `<div class="page-h"><div><h2>Restaurants</h2><p>Add a restaurant, then give the owner the details.</p></div><button class="btn primary" id="add">Add restaurant</button></div>
      <div class="stack">${rs.length ? rs.map((r) => `<div class="card stack"><div class="row" style="justify-content:space-between"><div><b>${esc(r.name)}</b> ${planPill(r)}<br><span class="muted small mono">${esc(origin)}/r/${esc(r.slug)}/</span></div><div class="btns"><button class="btn sm" data-edit="${r.id}">Edit</button><button class="btn sm" data-owner="${r.id}">Reset owner login</button></div></div>
        <div class="muted small">Owner username: <b class="mono">${esc(r.owner || 'none')}</b> · Staff ${r.staff} · Customers ${r.customers} · Paid until ${r.paid_until ? dmy(r.paid_until) : 'not set'}${r.notes ? ' · ' + esc(r.notes) : ''}</div></div>`).join('') : '<div class="empty"><b>No restaurants yet</b></div>'}</div>`;
  }

  function showDetails(name, slug, user, pass) {
    const text = `Flotoken\nRestaurant: ${name}\nLogin page: ${origin}/staff\nUsername: ${user}\nPassword: ${pass}\nCustomers order here: ${origin}/r/${slug}/order`;
    const m = modal(`<h2>Share these details</h2><p class="muted small">Send them to the owner now. The password is not shown again.</p><pre class="card flat mono small" style="white-space:pre-wrap;user-select:all" id="det">${esc(text)}</pre><div class="btns"><button class="btn primary grow" id="cp">Copy</button><a class="btn grow" target="_blank" rel="noopener" href="https://wa.me/?text=${encodeURIComponent(text)}">WhatsApp</a><button class="btn grow" data-close>Done</button></div>`);
    $('#cp', m.el).addEventListener('click', async () => { try { await navigator.clipboard.writeText(text); toast('Copied', 'ok'); } catch (e) { toast('Press and hold the text to copy', ''); } });
    $('[data-close]', m.el).addEventListener('click', m.close);
  }

  function addDialog() {
    const m = modal(`<h2>Add restaurant</h2><form class="stack" id="nf" novalidate>
      <label class="field">Restaurant name<input id="n" maxlength="60" required></label>
      <label class="field">Web address name<input id="s" maxlength="30" placeholder="betty-military-hotel" autocapitalize="none"><span class="muted tiny">Customers see this in the link. Letters, numbers and dashes.</span></label>
      <label class="field">Owner username<input id="ou" autocapitalize="none" required></label>
      <label class="field">Owner password<div class="row"><input id="op" style="flex:1" required><button class="btn sm" type="button" id="gen">Make one</button></div></label>
      <label class="field">Plan<select id="pl"><option value="trial">Free trial (30 days)</option><option value="monthly">Monthly</option><option value="yearly">Yearly</option></select></label>
      <label class="check"><input type="checkbox" id="sm" checked> <span>Add a sample menu to start with</span></label>
      <div class="err" id="err" role="alert"></div><button class="btn primary block">Create restaurant</button></form>`);
    const slugify = (v) => v.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 30);
    let touched = false;
    $('#s', m.el).addEventListener('input', () => { touched = true; });
    $('#n', m.el).addEventListener('input', (e) => { if (!touched) $('#s', m.el).value = slugify(e.target.value); });
    $('#gen', m.el).addEventListener('click', () => { const c = 'abcdefghjkmnpqrstuvwxyz23456789'; $('#op', m.el).value = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => c[b % c.length]).join(''); });
    $('#nf', m.el).addEventListener('submit', async (e) => {
      e.preventDefault(); $('#err', m.el).textContent = '';
      const body = { name: $('#n', m.el).value, slug: $('#s', m.el).value, owner_username: $('#ou', m.el).value, owner_password: $('#op', m.el).value, plan: $('#pl', m.el).value, sample_menu: $('#sm', m.el).checked };
      try { const r = await api('/api/platform/restaurants', 'POST', body); m.close(); await refresh(); showDetails(body.name, r.slug, body.owner_username, body.owner_password); } catch (x) { $('#err', m.el).textContent = x.message; }
    });
  }

  function editDialog(r) {
    const pu = r.paid_until ? new Date(r.paid_until + 5.5 * 3600e3).toISOString().slice(0, 10) : '';
    const m = modal(`<h2>${esc(r.name)}</h2><form class="stack" id="ef"><label class="field">Name<input id="n" maxlength="60" value="${esc(r.name)}"></label>
      <label class="field">Plan<select id="pl">${['trial', 'monthly', 'yearly'].map((p) => `<option ${r.plan === p ? 'selected' : ''}>${p}</option>`).join('')}</select></label>
      <label class="field">Paid until<input id="pu" type="date" value="${pu}"></label>
      <label class="field">Status<select id="st"><option value="active" ${r.status === 'active' ? 'selected' : ''}>Active</option><option value="suspended" ${r.status === 'suspended' ? 'selected' : ''}>Suspended (nobody can use it)</option></select></label>
      <label class="field">Notes<textarea id="no" maxlength="300" rows="2">${esc(r.notes || '')}</textarea></label>
      <div class="err" id="err" role="alert"></div><button class="btn primary block">Save</button></form>`);
    $('#ef', m.el).addEventListener('submit', async (e) => {
      e.preventDefault();
      try { await api('/api/platform/restaurants/' + r.id, 'PUT', { name: $('#n', m.el).value, plan: $('#pl', m.el).value, paid_until: $('#pu', m.el).value, status: $('#st', m.el).value, notes: $('#no', m.el).value }); m.close(); toast('Saved', 'ok'); refresh(); } catch (x) { $('#err', m.el).textContent = x.message; }
    });
  }

  function ownerDialog(r) {
    const m = modal(`<h2>Reset owner login</h2><p class="muted small">For ${esc(r.name)}. Current username: <b class="mono">${esc(r.owner || 'none')}</b>. Leave the username as it is, or type a new one.</p>
      <form class="stack" id="of"><label class="field">Username<input id="ou" value="${esc(r.owner || '')}" autocapitalize="none"></label>
      <label class="field">New password<div class="row"><input id="op" style="flex:1" required><button class="btn sm" type="button" id="gen">Make one</button></div></label>
      <div class="err" id="err" role="alert"></div><button class="btn primary block">Reset</button></form>`);
    $('#gen', m.el).addEventListener('click', () => { const c = 'abcdefghjkmnpqrstuvwxyz23456789'; $('#op', m.el).value = Array.from(crypto.getRandomValues(new Uint8Array(8)), (b) => c[b % c.length]).join(''); });
    $('#of', m.el).addEventListener('submit', async (e) => {
      e.preventDefault();
      try { const pass = $('#op', m.el).value; const x = await api('/api/platform/restaurants/' + r.id + '/owner', 'POST', { username: $('#ou', m.el).value, password: pass }); m.close(); refresh(); showDetails(r.name, r.slug, x.username, pass); } catch (x) { $('#err', m.el).textContent = x.message; }
    });
  }

  /* ---------- customers ---------- */
  async function customersHtml(q = '') {
    const d = await api('/api/platform/customers' + (q ? '?q=' + encodeURIComponent(q) : ''));
    return `<div class="page-h"><div><h2>Customers</h2><p>${d.total} accounts across all restaurants.</p></div></div>
      <input type="search" id="cq" placeholder="Search by name or phone" value="${esc(q)}" aria-label="Search customers" class="mb">
      ${d.customers.length ? `<div class="table-wrap"><table><thead><tr><th>Name</th><th>Phone</th><th class="r">Restaurants</th><th>Joined</th><th>Last login</th><th></th></tr></thead><tbody>${d.customers.map((c) => `<tr><td><b>${esc(c.name)}</b></td><td class="mono">${esc(c.phone)}</td><td class="r num">${c.restaurants}</td><td class="small">${dmy(c.created_at)}</td><td class="small">${ago(c.last_login_at)}</td><td><button class="btn sm" data-reset="${c.id}" data-name="${esc(c.name)}">Reset password</button></td></tr>`).join('')}</tbody></table></div>` : '<div class="empty"><b>No customers found</b></div>'}`;
  }

  function accountHtml() {
    return `<div class="card stack" style="max-width:420px"><h2>Change your password</h2><input type="password" id="pc" placeholder="Current password" autocomplete="current-password"><input type="password" id="pn" placeholder="New password (6+ characters)" autocomplete="new-password"><div class="err" id="err" role="alert"></div><button class="btn primary" id="ps">Change password</button></div>
      <p class="muted small mt">Forgot your own password? Set PLATFORM_USERNAME and PLATFORM_PASSWORD in Render, then redeploy. The password is reset at start-up.</p>`;
  }

  async function render() {
    $$('[data-tab]').forEach((b) => b.setAttribute('aria-selected', b.dataset.tab === tab));
    const view = $('#view');
    if (tab === 'overview') { view.innerHTML = overviewHtml(); return; }
    if (tab === 'restaurants') {
      view.innerHTML = restaurantsHtml();
      $('#add').addEventListener('click', addDialog);
      view.addEventListener('click', (e) => {
        const ed = e.target.closest('[data-edit]'), ow = e.target.closest('[data-owner]');
        if (ed) editDialog(data.restaurants.find((r) => r.id === +ed.dataset.edit));
        if (ow) ownerDialog(data.restaurants.find((r) => r.id === +ow.dataset.owner));
      });
      return;
    }
    if (tab === 'customers') {
      const draw = async (q) => {
        view.innerHTML = await customersHtml(q);
        const box = $('#cq'); box.focus(); box.setSelectionRange(box.value.length, box.value.length);
        let t; box.addEventListener('input', () => { clearTimeout(t); t = setTimeout(() => draw(box.value.trim()), 300); });
        view.onclick = async (e) => {
          const b = e.target.closest('[data-reset]'); if (!b) return;
          if (!(await confirmBox(`Set a new temporary password for ${b.dataset.name}?`, 'Reset'))) return;
          const r = await attempt(() => api('/api/platform/customers/' + b.dataset.reset + '/reset-password', 'POST'));
          if (r) { const m = modal(`<h2>Temporary password</h2><p>Tell ${esc(b.dataset.name)} to log in with this and change it in Account:</p><div class="bigtok mono" style="font-size:34px;text-align:center;margin:12px 0">${esc(r.temporary_password)}</div><button class="btn block" data-close>Done</button>`); $('[data-close]', m.el).addEventListener('click', m.close); }
        };
      };
      await draw(''); return;
    }
    view.innerHTML = accountHtml();
    $('#ps').addEventListener('click', async () => {
      try { await api('/api/platform/password', 'POST', { current: $('#pc').value, new: $('#pn').value }); toast('Password changed', 'ok'); $('#pc').value = $('#pn').value = ''; } catch (e) { $('#err').textContent = e.message; }
    });
  }

  async function refresh() { data = await api('/api/platform/overview'); render(); }

  async function load() {
    let me;
    try { me = await api('/api/platform/me'); } catch (e) { root.innerHTML = `<div class="empty"><b>Cannot load</b>${esc(e.message)}</div>`; return; }
    if (!me.admin) { paintAuth(me.needs_setup); return; }
    try { data = await api('/api/platform/overview'); } catch (e) { if (e.status === 401) { paintAuth(false); return; } throw e; }
    shell(''); render();
  }
  load();
})();
