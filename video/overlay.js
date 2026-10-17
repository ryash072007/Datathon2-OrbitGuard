// Injected into the live OrbitGuard app while recording: side helper panels in the page margins,
// a chapter label, a visible cursor with click ripples, highlight rings and eased scrolling.
(() => {
  const css = `
  #vo-root { position: fixed; inset: 0; pointer-events: none; z-index: 2147483000; font-family: 'IBM Plex Sans', system-ui, sans-serif; }
  .vo-side { position: absolute; width: 272px; padding: 20px 22px 22px; background: rgba(22,24,28,.94); border: 1px solid #34342f; border-left: 3px solid var(--vo-accent, #3987e5); border-radius: 10px; color: #f0efec; box-shadow: 0 18px 50px rgba(0,0,0,.35); opacity: 0; transition: opacity .55s ease, transform .7s cubic-bezier(.2,.8,.2,1); }
  .vo-side.left { left: 36px; transform: translateX(-30px); } .vo-side.right { right: 36px; transform: translateX(30px); }
  .vo-side.in { opacity: 1; transform: none; }
  .vo-side .k { font-size: 14px; color: #9a998f; font-weight: 500; margin-bottom: 6px; }
  .vo-side .t { font-size: 23px; font-weight: 600; line-height: 1.22; }
  .vo-side .b { font-size: 16px; line-height: 1.5; color: #c3c2b7; margin-top: 10px; }
  .vo-chapter { position: absolute; left: 36px; top: 84px; display: flex; align-items: center; gap: 10px; font-size: 15px; color: #c3c2b7; opacity: 0; transform: translateY(-8px); transition: opacity .5s, transform .6s; }
  .vo-chapter.in { opacity: 1; transform: none; }
  .vo-chapter b { font-family: 'IBM Plex Mono', monospace; font-weight: 500; color: #f0efec; }
  .vo-cursor { position: absolute; left: 0; top: 0; width: 26px; height: 26px; transform: translate(-3px, -2px); transition: opacity .3s; filter: drop-shadow(0 2px 4px rgba(0,0,0,.5)); }
  .vo-ripple { position: absolute; width: 16px; height: 16px; margin: -8px 0 0 -8px; border-radius: 50%; border: 2px solid #86b6ef; animation: vo-ripple .6s ease-out forwards; }
  @keyframes vo-ripple { to { transform: scale(3.2); opacity: 0; } }
  .vo-ring { position: absolute; border: 2px solid #86b6ef; border-radius: 10px; box-shadow: 0 0 0 4px rgba(57,135,229,.18); opacity: 0; transform: scale(1.03); transition: opacity .35s ease, transform .5s cubic-bezier(.2,.8,.2,1); }
  .vo-ring.in { opacity: 1; transform: none; }
  `;
  const ready = fn => document.readyState === 'loading' ? document.addEventListener('DOMContentLoaded', fn) : fn();
  ready(() => {
    const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
    const root = document.createElement('div'); root.id = 'vo-root'; document.body.appendChild(root);
    const cursor = document.createElement('div'); cursor.className = 'vo-cursor';
    cursor.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M4 2 L4 19 L8.6 14.8 L11.6 21.4 L14.3 20.2 L11.4 13.8 L17.6 13.6 Z" fill="#fff" stroke="#111" stroke-width="1.3" stroke-linejoin="round"/></svg>';
    cursor.style.left = '960px'; cursor.style.top = '1200px';
    root.appendChild(cursor);
    document.addEventListener('mousemove', e => {cursor.style.left = e.clientX + 'px'; cursor.style.top = e.clientY + 'px';}, true);
    document.addEventListener('mousedown', e => {const r = document.createElement('div'); r.className = 'vo-ripple'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px'; root.appendChild(r); setTimeout(() => r.remove(), 700);}, true);
    const panels = {};
    const chapter = document.createElement('div'); chapter.className = 'vo-chapter'; root.appendChild(chapter);
    const ease = k => k < .5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
    window.__vo = {
      side(side, {kicker = '', title = '', body = '', accent = '#3987e5', top = 300} = {}) {
        const old = panels[side];
        if (old) {old.classList.remove('in'); setTimeout(() => old.remove(), 600);}
        const el = document.createElement('div');
        el.className = `vo-side ${side}`; el.style.top = top + 'px'; el.style.setProperty('--vo-accent', accent);
        el.innerHTML = `<div class="k">${kicker}</div><div class="t">${title}</div>${body ? `<div class="b">${body}</div>` : ''}`;
        root.appendChild(el); panels[side] = el;
        setTimeout(() => el.classList.add('in'), old ? 250 : 30);
      },
      clear(side) {const el = panels[side]; if (el) {el.classList.remove('in'); setTimeout(() => el.remove(), 600); delete panels[side];}},
      chapter(number, label) {chapter.classList.remove('in'); setTimeout(() => {chapter.innerHTML = `<b>${number}</b><span>${label}</span>`; chapter.classList.add('in');}, 200);},
      ring(el, ms = 2500, pad = 8) {
        if (!el) return;
        const ring = document.createElement('div'); ring.className = 'vo-ring'; root.appendChild(ring);
        let alive = true;
        const place = () => {if (!alive) return; const r = el.getBoundingClientRect(); Object.assign(ring.style, {left: r.left - pad + 'px', top: r.top - pad + 'px', width: r.width + pad * 2 + 'px', height: r.height + pad * 2 + 'px'}); requestAnimationFrame(place);};
        place(); requestAnimationFrame(() => ring.classList.add('in'));
        setTimeout(() => {ring.classList.remove('in'); setTimeout(() => {alive = false; ring.remove();}, 400);}, ms);
      },
      scrollToEl(el, offset = 80, ms = 1000) {
        const from = window.scrollY;
        const target = el ? Math.max(0, Math.min(el.getBoundingClientRect().top + from - offset, document.documentElement.scrollHeight - innerHeight)) : 0;
        return new Promise(resolve => {const t0 = performance.now(); const step = now => {const k = Math.min(1, (now - t0) / ms); window.scrollTo(0, from + (target - from) * ease(k)); if (k < 1) requestAnimationFrame(step); else resolve();}; requestAnimationFrame(step);});
      },
    };
  });
})();
