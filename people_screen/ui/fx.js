'use strict';
/* The light of the room follows the work: the picture on the stage tints the glow behind everything; the controls keep their own colour. */
const Ambient = {on: 'ambA', url: null};
function setAmbient(url) {
  if (url === Ambient.url) return;
  Ambient.url = url;
  const next = Ambient.on === 'ambA' ? 'ambB' : 'ambA';
  const a = $(next), b = $(Ambient.on);
  if (url) {
    const css = `url("${url}")`;
    const probe = new Image();
    probe.onload = () => { a.style.backgroundImage = css; a.classList.add('on'); b.classList.remove('on'); Ambient.on = next; accentFrom(probe); };
    probe.src = url;
  } else { a.classList.remove('on'); b.classList.remove('on'); document.documentElement.style.removeProperty('--piece-h'); }
}
function accentFrom(img) {
  try {
    const c = document.createElement('canvas'); c.width = c.height = 48;
    const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(img, 0, 0, 48, 48);
    const d = g.getImageData(0, 0, 48, 48).data;
    const bins = new Array(36).fill(0);
    for (let i = 0; i < d.length; i += 4) {
      const r = d[i] / 255, gn = d[i + 1] / 255, b = d[i + 2] / 255;
      const mx = Math.max(r, gn, b), mn = Math.min(r, gn, b), sat = mx - mn;
      if (sat < .12 || mx < .18 || mx > .97) continue;
      let h = mx === r ? ((gn - b) / sat) % 6 : mx === gn ? (b - r) / sat + 2 : (r - gn) / sat + 4;
      h = (h * 60 + 360) % 360;
      bins[Math.floor(h / 10)] += sat * sat;
    }
    let best = -1, top = 0;
    bins.forEach((v, i) => { if (v > top) { top = v; best = i; } });
    // The piece's colour goes to the light of the room (the glow and the grain), not to the controls: Generate, the chosen
    // cards and the lane keep one colour, so they do not turn pink after one picture and orange after the next, or follow
    // the person into a lane with nothing open.
    if (best >= 0) document.documentElement.style.setProperty('--piece-h', String(hueToOklch(best * 10 + 5)));
  } catch (e) { /* a picture that cannot be read simply leaves the colors as they are */ }
}
function hueToOklch(h) {
  // sRGB hue and oklch hue differ by a small amount that depends on the hue; this is close enough for an accent.
  return Math.round((h + 28 + 14 * Math.sin((h - 40) * Math.PI / 180) + 360) % 360);
}

/* A layered picture: the main subject sits on its own layer in front of the rest.
   The subject layer is cut by Apple's Vision framework on this machine, so the depth is real, not guessed in the page. */
function loadImage(url) { return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url; }); }
function subjectCentroid(img) {
  try {
    const c = document.createElement('canvas'); c.width = c.height = 40;
    const g = c.getContext('2d', {willReadFrequently: true}); g.drawImage(img, 0, 0, 40, 40);
    const d = g.getImageData(0, 0, 40, 40).data;
    let sx = 0, sy = 0, sum = 0;
    for (let y = 0; y < 40; y++) for (let x = 0; x < 40; x++) { const a = d[(y * 40 + x) * 4 + 3]; if (a > 40) { sx += x * a; sy += y * a; sum += a; } }
    return sum ? [sx / sum / 40 * 100, sy / sum / 40 * 100] : [50, 50];
  } catch (e) { return [50, 50]; }
}
function lifted(url, liftUrl, alt) {
  const box = el('div', 'lifted');
  const wrap = el('div', 'base-wrap');
  const bg = el('img', 'bg'); bg.src = url; bg.alt = alt || '';
  const patch = el('img', 'patch'); const fg = el('img', 'fg');
  const gloss = el('div', 'gloss'); const sweep = el('div', 'sweep');
  wrap.append(bg, patch, sweep);
  box.append(wrap, fg, gloss);
  bg.addEventListener('load', () => { box.dataset.ar = bg.naturalWidth / bg.naturalHeight; fitLifted(); }, {once: true});
  box.classList.add('landing');
  setTimeout(() => box.classList.remove('landing'), 1900);
  if (liftUrl) {
    loadImage(liftUrl).then(mask => {
      const [cx, cy] = subjectCentroid(mask);
      fg.src = liftUrl;
      patch.src = url;
      const m = `url("${liftUrl}")`;
      patch.style.webkitMaskImage = m; patch.style.maskImage = m;
      patch.style.webkitMaskSize = '100% 100%'; patch.style.maskSize = '100% 100%';
      patch.style.transformOrigin = fg.style.transformOrigin = `${cx}% ${cy}%`;
      box.classList.add('has-subject');
    }).catch(() => {});
  }
  const R = 13, T = 4;
  let raf = 0, tx = 0, ty = 0, cx = 0, cy = 0, live = false;
  const paint = () => {
    cx += (tx - cx) * .12; cy += (ty - cy) * .12;
    box.style.transform = `rotateY(${(cx * T).toFixed(2)}deg) rotateX(${(-cy * T).toFixed(2)}deg)`;
    bg.style.transform = `translate(${(-cx * R * .55).toFixed(1)}px, ${(-cy * R * .55).toFixed(1)}px) scale(1.018)`;
    patch.style.transform = `scale(1.07) translate(${(-cx * R * .55).toFixed(1)}px, ${(-cy * R * .55).toFixed(1)}px)`;
    fg.style.transform = `translate(${(cx * R).toFixed(1)}px, ${(cy * R).toFixed(1)}px) scale(1.018)`;
    if (live || Math.abs(tx - cx) + Math.abs(ty - cy) > .002) raf = requestAnimationFrame(paint); else raf = 0;
  };
  const kick = () => { if (!raf) raf = requestAnimationFrame(paint); };
  box.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const r = box.getBoundingClientRect();
    tx = (e.clientX - r.left) / r.width * 2 - 1; ty = (e.clientY - r.top) / r.height * 2 - 1;
    box.style.setProperty('--gx', ((tx + 1) * 50) + '%'); box.style.setProperty('--gy', ((ty + 1) * 50) + '%');
    box.classList.add('hot'); live = true; kick();
    if (box.classList.contains('has-subject')) fg.style.filter = 'drop-shadow(0 18px 22px rgba(0,0,0,.45))';
  });
  box.addEventListener('pointerleave', () => { tx = ty = 0; live = false; box.classList.remove('hot'); fg.style.filter = ''; kick(); });
  return box;
}
/* the picture always fits the stage exactly, whatever its shape */
function fitLifted() {
  for (const box of document.querySelectorAll('.lifted[data-ar]')) {
    const host = box.parentElement; const ar = Number(box.dataset.ar);
    if (!host || !ar) continue;
    const w = Math.min(host.clientWidth, host.clientHeight * ar);
    box.style.width = Math.floor(w) + 'px'; box.style.height = Math.floor(w / ar) + 'px';
  }
}
new ResizeObserver(fitLifted).observe($('canvas'));
/* a card in the starter wall: picture, and the subject stepping out of it on hover */
function tile(opts) {
  const b = el('button', 'tile ' + (opts.cls || ''));
  const frame = el('div', 'tile-frame');
  const base = el('div', 'layer-base');
  const im = el('img'); im.src = opts.src; im.alt = opts.title || ''; im.loading = 'lazy'; base.append(im);
  frame.append(base);
  let sub = null;
  if (opts.lift) { const l = el('div', 'layer-sub'); sub = el('img'); sub.src = opts.lift; sub.alt = ''; sub.loading = 'lazy'; l.append(sub); frame.append(l); }
  const gloss = el('div', 'gloss'); frame.append(gloss);
  if (opts.title) { const cap = el('div', 'tile-cap' + (opts.capTop ? ' top' : ''), opts.title); if (opts.sub) cap.append(el('small', '', opts.sub)); frame.append(cap); base.classList.add('captioned'); }
  if (opts.video) {
    const v = el('video'); v.src = opts.video; v.muted = true; v.loop = true; v.playsInline = true; v.preload = 'none'; v.poster = opts.src; v.style.opacity = 0; v.style.transition = 'opacity .3s';
    base.append(v);
    b.addEventListener('pointerenter', e => { if (e.pointerType === 'touch') return; v.style.opacity = 1; v.play().catch(() => {}); });
    b.addEventListener('pointerleave', () => { v.style.opacity = 0; v.pause(); });
    // On a screen with no pointer to hover, a tap plays the sample (one at a time) as well as choosing it.
    b.addEventListener('click', () => {
      if (window.matchMedia && !matchMedia('(hover: none)').matches) return;
      for (const o of document.querySelectorAll('.tile video')) if (o !== v) { o.pause(); o.style.opacity = 0; }
      v.style.opacity = 1; v.play().catch(() => {});
    });
  }
  b.append(frame);
  b.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch') return;
    const r = b.getBoundingClientRect();
    const x = (e.clientX - r.left) / r.width * 2 - 1, y = (e.clientY - r.top) / r.height * 2 - 1;
    frame.style.transform = `perspective(900px) rotateY(${(x * 8).toFixed(2)}deg) rotateX(${(-y * 8).toFixed(2)}deg) translateZ(6px)`;
    im.style.transform = `translate(${(-x * 7).toFixed(1)}px, ${(-y * 7).toFixed(1)}px)`;
    if (sub) sub.style.transform = `translate(${(x * 10).toFixed(1)}px, ${(y * 10 - 6).toFixed(1)}px) scale(1.06)`;
    gloss.style.setProperty('--gx', ((x + 1) * 50) + '%'); gloss.style.setProperty('--gy', ((y + 1) * 50) + '%');
  });
  b.addEventListener('pointerleave', () => { frame.style.transform = ''; im.style.transform = ''; if (sub) sub.style.transform = ''; });
  b.onclick = opts.onclick;
  return b;
}
/* The paper the picture will appear on: a dark sheet under a slow, warm safelight, with a fine, quiet grain, the way an
   unexposed print sits in a darkroom tray. It breathes slowly instead of flickering, and holds still under reduced motion. */
const Grain = {on: false, raf: 0, cv: null, ctx: null, step: 0, t0: 0};
function grainStart() {
  Grain.cv = $('grain'); Grain.ctx = Grain.cv.getContext('2d', {alpha: false});
  const W = 240, H = 160;
  Grain.cv.width = W; Grain.cv.height = H; Grain.on = true; Grain.t0 = performance.now();
  const still = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  const paper = Grain.ctx.createImageData(W, H);
  const d = paper.data;
  for (let i = 0; i < d.length; i += 4) { const v = 19 + Math.random() * 7; d[i] = v; d[i + 1] = v + 1; d[i + 2] = v + 4; d[i + 3] = 255; }  // one quiet grain, drawn once
  const hue = () => Number(getComputedStyle(document.documentElement).getPropertyValue('--piece-h')) || Number(getComputedStyle(document.documentElement).getPropertyValue('--accent-h')) || 60;
  const draw = () => {
    if (!Grain.on) return;
    const g = Grain.ctx, t = (performance.now() - Grain.t0) / 1000;
    g.putImageData(paper, 0, 0);
    const x = W * (0.5 + 0.18 * Math.sin(t / 9)), y = H * (0.42 + 0.12 * Math.cos(t / 7));
    const lamp = g.createRadialGradient(x, y, 4, x, y, W * 0.75);
    const h = hue();
    lamp.addColorStop(0, `oklch(0.42 0.06 ${h} / 0.55)`); lamp.addColorStop(0.5, `oklch(0.3 0.04 ${h} / 0.25)`); lamp.addColorStop(1, 'rgba(0,0,0,0)');
    g.fillStyle = lamp; g.fillRect(0, 0, W, H);
    const vignette = g.createRadialGradient(W / 2, H / 2, H * 0.35, W / 2, H / 2, W * 0.72);
    vignette.addColorStop(0, 'rgba(0,0,0,0)'); vignette.addColorStop(1, 'rgba(0,0,0,0.45)');
    g.fillStyle = vignette; g.fillRect(0, 0, W, H);
    if (!still) Grain.raf = requestAnimationFrame(() => setTimeout(draw, 120));
  };
  draw();
}
function grainStop() { Grain.on = false; cancelAnimationFrame(Grain.raf); }
function waveBars(host, peaks, cls) {
  host.replaceChildren();
  if (!peaks || !peaks.length) return;
  const n = Math.min(peaks.length, Math.max(8, Math.round((host.clientWidth || 72) / (cls === 'big' ? 3.2 : 3))));
  for (let i = 0; i < n; i++) {
    const b = el('i'); const p = peaks[Math.floor(i / n * peaks.length)];
    b.style.height = Math.max(6, p * 100).toFixed(0) + '%';
    host.append(b);
  }
}
