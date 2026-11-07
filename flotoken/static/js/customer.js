/* Customer home: log in once, pick any restaurant, see your orders everywhere. */
(() => {
  const root = $('#root');
  let me = null, restaurants = [];

  const head = (right) => `<div class="row" style="justify-content:space-between;margin-bottom:12px"><a class="brand" href="/"><i>F</i><span>Flotoken</span></a>${right || ''}</div>`;

  function paintAuth() {
    root.innerHTML = head('') + '<div class="card" id="authbox"></div><p class="muted small center mt"><a href="/">Back</a> · <a href="/staff">Restaurant login</a></p>';
    Account.renderAuth($('#authbox'), { mode: 'signup', brand: 'the restaurants you order from', onDone: async (c) => { me = c; await paintHome(); } });
  }

  const restaurantRows = (list) => list.length
    ? list.map((x) => `<a class="card flat row" style="justify-content:space-between;text-decoration:none;color:inherit" href="/r/${esc(x.slug)}/order" data-slug="${esc(x.slug)}"><b>${esc(x.name)}</b><span class="btn sm primary">Order</span></a>`).join('')
    : '<div class="empty"><b>No match</b>Try another name.</div>';

  async function paintHome() {
    let orders = [];
    try { orders = (await api('/api/customer/orders')).orders; } catch (e) { if (e.status === 401) { me = null; return paintAuth(); } }
    const active = orders.filter((o) => !['collected', 'cancelled'].includes(o.status));
    root.innerHTML = head(`<button class="btn sm" id="acc">${esc(me.name)}</button>`) + `
      <h1>Hello, ${esc(me.name.split(' ')[0])}</h1>
      ${active.length ? `<div class="card stack mb"><h2>Your tokens now</h2>${active.map((o) => `<a class="row" style="justify-content:space-between;text-decoration:none;color:inherit" href="/r/${esc(o.restaurant.slug)}/t/${esc(o.code)}"><span><b>${esc(o.restaurant.name)}</b><br><span class="muted small">Token ${esc(o.tok)} · ${esc(o.status)}</span></span><span class="btn sm">Track</span></a>`).join('')}</div>` : ''}
      <div class="card stack mb"><h2>Choose a restaurant</h2>
        <input type="search" id="q" placeholder="Search restaurants" aria-label="Search restaurants">
        <div class="stack" id="rlist">${restaurantRows(restaurants)}</div></div>
      <div class="card stack"><h2>Past orders</h2>${orders.length ? orders.slice(0, 15).map((o) => `<div class="row" style="justify-content:space-between"><span><b>${esc(o.restaurant.name)}</b><br><span class="muted small">${dmy(o.created_at)} · ${money(o.total)} · ${esc(o.status)}</span></span><span class="btns"><a class="btn sm" href="/r/${esc(o.restaurant.slug)}/t/${esc(o.code)}">View</a><a class="btn sm" href="/r/${esc(o.restaurant.slug)}/order?again=${esc(o.code)}">Order again</a></span></div>`).join('') : '<p class="muted small">No orders yet. Pick a restaurant above.</p>'}</div>`;
    $('#q').addEventListener('input', (e) => { const t = e.target.value.trim().toLowerCase(); $('#rlist').innerHTML = restaurantRows(restaurants.filter((x) => x.name.toLowerCase().includes(t))); });
    $('#acc').addEventListener('click', () => Account.openAccount(me, { onSaved: (c) => { me = c; paintHome(); }, onGone: () => { me = null; paintAuth(); } }));
  }

  (async () => {
    try { restaurants = (await api('/api/public/restaurants')).restaurants; } catch (e) { root.innerHTML = `<div class="empty"><b>Cannot load</b>${esc(e.message)}</div>`; return; }
    try { me = (await api('/api/customer/me')).customer; } catch (e) { me = null; }
    me ? paintHome() : paintAuth();
  })();
})();
