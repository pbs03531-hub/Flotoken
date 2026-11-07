/* Customer sign-up, log-in and account settings. Used inside a restaurant page (as a pop-up) and on /customer (inline).
   One Flotoken account works at every restaurant. */
const Account = (() => {
  const consent = (brand) => `I agree that ${esc(brand)} and Flotoken keep my name, mobile number and order history to serve my orders. I can delete my account any time.`;

  /** Paint the sign-up / log-in form into `box`. onDone(customer, justSignedUp) runs after success. */
  function renderAuth(box, { mode = 'signup', brand = 'this restaurant', onDone }) {
    const up = mode === 'signup';
    box.innerHTML = `<h2>${up ? 'Create your account' : 'Welcome back'}</h2>
      <p class="muted small">${up ? 'One account for every restaurant on Flotoken: track tokens, reorder in one tap, and never lose a receipt.' : 'Log in with your mobile number.'}</p>
      <div class="chips" style="margin:10px 0"><button class="chip" type="button" data-mode="signup" aria-pressed="${up}">Sign up</button><button class="chip" type="button" data-mode="login" aria-pressed="${!up}">Log in</button></div>
      <form class="stack" id="af" novalidate>
        ${up ? '<label class="field">Your name<input type="text" name="name" maxlength="40" autocomplete="name" required></label>' : ''}
        <label class="field">Mobile number<input type="tel" name="phone" inputmode="numeric" placeholder="98450 12345" autocomplete="tel" required></label>
        <label class="field">Password${up ? ' (at least 6 characters)' : ''}<input type="password" name="password" autocomplete="${up ? 'new-password' : 'current-password'}" required></label>
        ${up ? `<label class="check"><input type="checkbox" name="consent"> <span class="small">${consent(brand)}</span></label>` : '<p class="muted tiny">Forgot your password? Contact Flotoken support and we will give you a temporary one.</p>'}
        <div class="err" id="aerr" role="alert"></div>
        <button class="btn primary block" id="asubmit" type="submit">${up ? 'Create account' : 'Log in'}</button>
      </form>`;
    $$('[data-mode]', box).forEach((b) => b.addEventListener('click', () => renderAuth(box, { mode: b.dataset.mode, brand, onDone })));
    $('#af', box).addEventListener('submit', async (e) => {
      e.preventDefault();
      const f = e.target, btn = $('#asubmit', box), err = $('#aerr', box);
      err.textContent = ''; btn.disabled = true;
      try {
        const body = { phone: f.phone.value, password: f.password.value };
        if (up) { body.name = f.name.value; body.consent = f.consent.checked; }
        const r = await api(up ? '/api/customer/signup' : '/api/customer/login', 'POST', body);
        onDone(r.customer, up);
      } catch (x) { err.textContent = x.message; btn.disabled = false; }
    });
  }

  function openAuth({ mode = 'signup', brand, onDone }) {
    const m = modal('');
    renderAuth(m.el, { mode, brand, onDone: (c, up) => { m.close(); onDone(c, up); } });
    const first = $('input', m.el); if (first) first.focus();
    return m;
  }

  function openAccount(me, { onSaved, onGone }) {
    const m = modal(`<h2>Your account</h2>
      <div class="stack">
        <label class="field">Name<input type="text" id="aname" maxlength="40" value="${esc(me.name)}"></label>
        <div class="kv"><span class="muted">Mobile</span><b class="mono">${esc(me.phone)}</b></div>
        <button class="btn primary block" id="asave">Save name</button>
        <details><summary class="small">Change password</summary><div class="stack" style="margin-top:8px">
          <input type="password" id="pcur" placeholder="Current password" autocomplete="current-password">
          <input type="password" id="pnew" placeholder="New password (6+ characters)" autocomplete="new-password">
          <button class="btn block" id="psave">Change password</button></div></details>
        <details><summary class="small bad-text">Delete my account</summary><div class="stack" style="margin-top:8px">
          <p class="muted small">Your name and number are removed from your past bills at every restaurant. This cannot be undone.</p>
          <input type="password" id="pdel" placeholder="Enter your password" autocomplete="current-password">
          <button class="btn danger block" id="adel">Delete account</button></div></details>
        <div class="err" id="aerr" role="alert"></div>
        <button class="btn block" id="alogout">Log out</button>
      </div>`);
    const err = (e) => { $('#aerr', m.el).textContent = e.message; };
    $('#asave', m.el).addEventListener('click', async () => { try { const r = await api('/api/customer/me', 'PUT', { name: $('#aname', m.el).value }); toast('Saved', 'ok'); m.close(); onSaved(r.customer); } catch (e) { err(e); } });
    $('#psave', m.el).addEventListener('click', async () => { try { await api('/api/customer/password', 'POST', { current: $('#pcur', m.el).value, new: $('#pnew', m.el).value }); toast('Password changed', 'ok'); m.close(); } catch (e) { err(e); } });
    $('#adel', m.el).addEventListener('click', async () => { try { await api('/api/customer/me', 'DELETE', { password: $('#pdel', m.el).value }); m.close(); toast('Account deleted', 'ok'); onGone(); } catch (e) { err(e); } });
    $('#alogout', m.el).addEventListener('click', async () => { await attempt(() => api('/api/customer/logout', 'POST')); m.close(); onGone(); });
  }

  return { renderAuth, openAuth, openAccount };
})();
