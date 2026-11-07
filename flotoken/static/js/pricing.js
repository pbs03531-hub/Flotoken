/* Pricing cards and the one GST formula. Used by /pricing and Admin > Plan. */
const Pricing = (() => {
  const inr = (n) => '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: Number.isInteger(+n) ? 0 : 2, maximumFractionDigits: 2 });
  // GST formula (rate is a percent, e.g. 18):
  //   price excludes GST:  gst = price x rate / 100,   total = price + gst
  //   price includes GST:  base = price / (1 + rate/100),   gst = price - base
  const gst = (price, rate, included) => {
    const r = rate / 100, round = (x) => Math.round(x * 100) / 100;
    return included ? { base: round(price / (1 + r)), gst: round(price - price / (1 + r)), total: price }
      : { base: price, gst: round(price * r), total: round(price * (1 + r)) };
  };
  const FEATURES = ['Token system with customer app, counter, kitchen screen and wall board', 'Customer sign-up and login, order history, reorder and ratings',
    'Owner edits the menu with photos from a phone', 'Roles for owner, cashier and kitchen, with an audit trail', 'Payment record for every order, refunds and daily reports',
    'Customer list, business dashboard and CSV export', 'Installs on phones like an app'];

  async function mount(el) {
    const d = await api('/api/public/pricing');
    const rate = d.plan.gst_percent;
    el.innerHTML = `<div class="plan-grid">
        <div class="plan"><b>Monthly</b><div class="amt">${inr(d.plan.monthly)}<small class="muted" style="font-size:14px"> / month</small></div><p class="muted small">Pay month by month.</p>
          <ul>${FEATURES.map((f) => `<li class="small">${esc(f)}</li>`).join('')}</ul></div>
        <div class="plan best"><span class="pill ok">Best value</span> <b>Yearly</b><div class="amt">${inr(d.plan.yearly)}<small class="muted" style="font-size:14px"> / year</small></div>
          <p class="muted small">Works out to ${inr(d.yearly_per_month)} a month. You save ${inr(d.yearly_saving)} compared with paying monthly for 12 months.</p>
          <ul>${FEATURES.map((f) => `<li class="small">${esc(f)}</li>`).join('')}</ul></div></div>
      <div class="card stack mt"><h2>GST</h2>
        <p class="small">GST is ${rate}%. <b>GST = price × ${rate} ÷ 100</b>, and <b>total = price + GST</b>. If a price already includes GST: <b>price without GST = price ÷ ${(1 + rate / 100).toFixed(2)}</b>.</p>
        <div class="tablewrap"><table><thead><tr><th>Plan</th><th>Price</th><th>GST ${rate}%</th><th>Total with GST</th></tr></thead><tbody>
          <tr><td>Monthly</td><td>${inr(d.gst.monthly.price)}</td><td>${inr(d.gst.monthly.add_gst)}</td><td><b>${inr(d.gst.monthly.add_total)}</b></td></tr>
          <tr><td>Yearly</td><td>${inr(d.gst.yearly.price)}</td><td>${inr(d.gst.yearly.add_gst)}</td><td><b>${inr(d.gst.yearly.add_total)}</b></td></tr></tbody></table></div>
        <h3 style="margin-top:8px">GST calculator</h3>
        <div class="form-grid two"><label class="field">Amount (₹)<input type="number" id="g-amt" min="0" step="any" value="${d.plan.monthly}" inputmode="decimal"></label>
          <label class="field">This amount<select id="g-mode"><option value="ex">does not include GST</option><option value="in">already includes GST</option></select></label></div>
        <div class="kv"><span class="muted">Price without GST</span><b id="g-base"></b></div><div class="kv"><span class="muted">GST ${rate}%</span><b id="g-gst"></b></div><div class="kv"><span class="muted">Total to pay</span><b id="g-total"></b></div>
        <p class="muted tiny">This is only a calculator. Whether GST applies to a bill depends on the seller's registration. Ask your accountant.</p></div>
      <div class="card mt"><h3>Coming soon</h3><p class="small muted">Online payments through Razorpay, and OTP verification at sign-up.</p></div>`;
    const calc = () => {
      const amt = parseFloat($('#g-amt', el).value) || 0, r = gst(amt, rate, $('#g-mode', el).value === 'in');
      $('#g-base', el).textContent = inr(r.base); $('#g-gst', el).textContent = inr(r.gst); $('#g-total', el).textContent = inr(r.total);
    };
    $('#g-amt', el).addEventListener('input', calc); $('#g-mode', el).addEventListener('change', calc); calc();
  }
  return { mount, gst, inr };
})();
