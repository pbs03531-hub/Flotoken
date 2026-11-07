/* History: search past orders and open the full payment and change record (settles "I already paid" disputes). */
(() => {
  let orders = [], timer;
  $('#date').value = todayIST();

  const STATUS = { placed: ['Waiting', 'warn'], preparing: ['Cooking', 'info'], ready: ['Ready', 'ok'], collected: ['Collected', 'ok'], cancelled: ['Cancelled', 'bad'] };

  function payPill(o) {
    if (o.status === 'cancelled') return o.refund > 0 ? `<span class="pill warn">Refund ${money(o.refund)} owed</span>` : (o.paid > 0 ? '<span class="pill">Refunded</span>' : '<span class="pill">No payment</span>');
    if (o.refund > 0) return `<span class="pill warn">Refund ${money(o.refund)} owed</span>`;
    if (o.due > 0) return `<span class="pill bad">${o.paid ? money(o.due) + ' due' : 'Unpaid ' + money(o.due)}</span>`;
    const ms = [...new Set(o.payments.filter((p) => p.amount > 0).map((p) => p.method))];
    return `<span class="pill ok">Paid · ${ms.join(' + ')}</span>`;
  }

  async function load() {
    const p = new URLSearchParams({ scope: 'history', date: $('#date').value || todayIST(), q: $('#q').value, status: $('#status').value });
    const d = await attempt(() => api('/api/orders?' + p));
    if (!d) return;
    orders = d.orders;
    const s = d.summary;
    $('#summary').textContent = `${s.orders} orders · ${s.cancelled} cancelled · UPI ${money(s.upi)} · Cash ${money(s.cash)} on ${d.day}`;
    $('#rows').innerHTML = orders.length ? orders.map((o) => {
      const [label, kind] = STATUS[o.status];
      return `<tr><td class="num"><b>${o.tok}</b></td><td class="num">${hm(o.created_at)}</td><td>${o.source === 'app' ? 'Phone' : 'Counter'}</td>
        <td>${esc(o.customer_name) || '<span class="muted">-</span>'}<div class="muted small">${esc(o.phone)}</div></td>
        <td>${o.items.map((i) => `${i.qty} × ${esc(i.name)}`).join('<br>')}</td><td class="num">${o.status === 'cancelled' ? '<s>' + money(o.total) + '</s>' : money(o.total)}</td>
        <td>${payPill(o)}</td><td><span class="pill ${kind}">${label}</span></td>
        <td><button class="btn sm" data-id="${o.id}">Details</button></td></tr>`;
    }).join('') : '<tr><td colspan="9"><div class="empty"><b>No orders found</b>Try another date or clear the search.</div></td></tr>';
  }

  async function details(id) {
    const o = await attempt(() => api('/api/orders/' + id));
    if (!o) return;
    const [label, kind] = STATUS[o.status];
    const m = modal(`<div class="spread"><h2>Token ${o.tok}</h2><span class="pill ${kind}">${label}</span></div>
      <p class="muted small">${dmy(o.created_at)}, ${hm(o.created_at)} · ${o.source === 'app' ? 'Phone order' : 'Counter order'}${o.customer_name ? ' · ' + esc(o.customer_name) : ''}${o.phone ? ' · ' + esc(o.phone) : ''}</p>
      ${o.note ? `<p class="small" style="margin-top:6px"><b>Note:</b> ${esc(o.note)}</p>` : ''}
      ${o.cancel_reason ? `<p class="small" style="margin-top:6px"><b>Cancelled:</b> ${esc(o.cancel_reason)}</p>` : ''}
      <h3 style="margin-top:14px">Items</h3>
      ${o.items.map((i) => `<div class="kv"><span>${i.qty} × ${esc(i.name)}</span><span class="price">${money(i.qty * i.price)}</span></div>`).join('')}
      <div class="kv" style="border-top:1px solid var(--line)"><b>Total</b><b class="price">${money(o.total)}</b></div>
      <h3 style="margin-top:14px">Payments</h3>
      ${o.payments.length ? o.payments.map((p) => `<div class="kv small"><span>${p.amount < 0 ? 'Refund' : p.method} · ${hm(p.at)}${p.staff ? ' · by ' + esc(p.staff) : p.ref === 'demo' ? ' · demo' : ''}</span><span class="price">${p.amount < 0 ? '−' : ''}${money(Math.abs(p.amount))}</span></div>`).join('') : '<p class="muted small">No payment recorded.</p>'}
      <h3 style="margin-top:14px">Activity</h3>
      <ul class="loglist">${o.log.map((l) => `<li><time>${hm(l.at)}</time><span>${esc(l.text)}${l.user ? ' <span class="muted">(' + esc(l.user) + ')</span>' : ''}</span></li>`).join('')}</ul>
      <div class="btns mt"><a class="btn grow" href="${U('/receipt/' + o.id)}" target="_blank" rel="noopener">Receipt</a><button class="btn grow primary" data-x>Close</button></div>`);
    $('[data-x]', m.el).addEventListener('click', m.close);
  }

  $('#rows').addEventListener('click', (e) => { const b = e.target.closest('[data-id]'); if (b) details(+b.dataset.id); });
  $('#date').addEventListener('change', load);
  $('#status').addEventListener('change', load);
  $('#q').addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(load, 300); });
  load();
})();
