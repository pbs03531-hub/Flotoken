/* Public token board for a wall TV. Plays a chime and reads out new ready tokens once sound is enabled. */
(() => {
  let sound = false, prevReady = null;
  const fresh = new Map();   // token -> time it became ready (for the highlight)

  const tokens = (list, cls, emptyText) => list.length
    ? list.map((t) => `<div class="token ${cls} ${fresh.has(t) && Date.now() - fresh.get(t) < 8000 ? 'new' : ''}">${t}</div>`).join('')
    : `<p class="muted board-empty">${emptyText}</p>`;

  function announce(newOnes) {
    if (!sound || !newOnes.length) return;
    beep(2, 880);
    if ('speechSynthesis' in window) {
      setTimeout(() => newOnes.forEach((t) => {
        const u = new SpeechSynthesisUtterance(`Token ${t}, your order is ready`);
        u.lang = 'en-IN'; u.rate = 0.9; speechSynthesis.speak(u);
      }), 600);
    }
  }

  async function load() {
    const d = await api('/api/public/board');
    if (d.restaurant) $('#name').textContent = d.restaurant;
    if (prevReady !== null) {
      const newOnes = d.ready.filter((t) => !prevReady.includes(t));
      newOnes.forEach((t) => fresh.set(t, Date.now()));
      announce(newOnes);
    }
    prevReady = d.ready;
    $('#ready').innerHTML = tokens(d.ready, 'ready', 'No orders ready yet');
    $('#prep').innerHTML = tokens(d.preparing, 'prep', 'No orders in the kitchen');
  }

  $('#sound').addEventListener('click', (e) => {
    sound = !sound;
    e.currentTarget.textContent = sound ? 'Sound on' : 'Enable sound';
    e.currentTarget.setAttribute('aria-pressed', sound);
    if (sound) beep(1);          // this tap also unlocks audio in the browser
  });
  $('#full').addEventListener('click', () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => toast('Full screen is not available here'));
  });
  const tick = () => { $('#clock').textContent = new Date().toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }); };
  tick(); setInterval(tick, 15000);
  poll(load, 2000);
})();
