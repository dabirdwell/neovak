'use strict';
/* The timeline is the second view of a project: the same files as the gallery, placed in order. */
const T = {clips: [], sounds: [], shape: 'landscape', z: 34, t: 0, playing: false, sel: null, bin: [], raf: 0, media: new Map(), peaks: new Map(), saveTm: 0, audio: new Map()};
function tlTotal() { return T.clips.reduce((a, c) => a + c.seconds, 0); }
function tlEnd() { return Math.max(tlTotal(), ...T.sounds.map(s => s.start + s.seconds), 6); }
/* The film ends with its last picture, so that, and not the end of the last sound, is its length. */
function tlFilm() { return T.clips.length ? tlTotal() : tlEnd(); }
function tlOverhang() { return T.clips.length ? Math.max(0, ...T.sounds.map(s => s.start + s.seconds - tlTotal())) : 0; }
function tlPaintNote() { const n = $('tlNote'); if (!n) return; const over = tlOverhang(); n.hidden = over < .05; n.textContent = over < .05 ? '' : `A sound runs ${over.toFixed(1)} seconds past the last picture. The film ends with the last picture, so that part of the sound will be cut off.`; }
async function loadMediaInfo(name) {
  if (T.media.has(name)) return T.media.get(name);
  const r = await api('/api/info/' + encodeURIComponent(name));
  const info = r.ok ? r.data : {seconds: null};
  T.media.set(name, info); return info;
}
function kindOf(name) { const s = name.split('.').pop().toLowerCase(); return ['png', 'jpg', 'jpeg', 'webp'].includes(s) ? 'image' : s === 'mp4' ? 'video' : ['wav', 'mp3', 'm4a'].includes(s) ? 'audio' : 'other'; }
async function openTimeline() {
  await refreshProjects();
  const p = currentProject(); if (!p) return;
  T.clips = p.timeline.clips.map(c => ({...c})); T.sounds = p.timeline.sounds.map(s => ({...s})); T.shape = p.timeline.shape || 'landscape';
  T.t = 0; T.sel = null;
  const page = $('page-timeline'); page.replaceChildren();
  const wrap = el('div', 'tl-page');
  const top = el('div', 'tl-top');
  const cell = el('div', 'monitor-cell'); cell.id = 'monitorCell';
  const mon = el('div', 'monitor'); mon.id = 'monitor'; cell.append(mon);
  // the monitor follows its own cell, so the film's line appearing under the bar shrinks it instead of pushing it up under the top bar
  new ResizeObserver(() => fitMonitor()).observe(cell);
  const bin = el('div', 'bin'); bin.id = 'bin';
  top.append(cell, bin);
  const bottom = el('div');
  const bar = el('div', 'tl-bar');
  const play = el('button', 'transport'); play.id = 'tlPlay'; play.setAttribute('aria-label', 'Play'); play.onclick = () => T.playing ? tlPause() : tlPlay();
  const time = el('div', 'tl-time num'); time.id = 'tlTime';
  const note = el('p', 'tl-note'); note.id = 'tlNote'; note.hidden = true;
  const shape = el('div', 'seg');
  shape.setAttribute('aria-label', 'Shape of the film');
  for (const [id, label] of [['landscape', 'Landscape'], ['portrait', 'Portrait'], ['square', 'Square']]) { const b = el('button', T.shape === id ? 'sel' : '', label); b.onclick = () => { T.shape = id; for (const x of shape.children) x.classList.toggle('sel', x === b); fitMonitor(); tlSave(); }; shape.append(b); }
  const zoomOut = el('button', 'chip', 'Zoom in'); zoomOut.onclick = () => { T.z = Math.min(160, T.z * 1.3); paintTracks(); };
  const zoomIn = el('button', 'chip', 'Zoom out'); zoomIn.onclick = () => { T.z = Math.max(8, T.z / 1.3); paintTracks(); };
  const del = el('button', 'chip', 'Remove'); del.id = 'tlDel'; del.onclick = tlRemoveSel;
  const make = el('button', 'primary', 'Make the film'); make.id = 'tlMake'; make.onclick = tlMake;
  const toGal = el('button', 'chip', 'See as a gallery'); toGal.onclick = () => { S.galleryScope = 'project'; go('gallery'); };
  make.classList.add('tl-make');
  const left = el('div', 'tl-group start'); left.append(play, time);
  const mid = el('div', 'tl-group mid'); mid.append(shape, zoomOut, zoomIn, del, toGal);
  bottom.className = 'tl-bottom';  // on a phone this part, the timeline itself, comes first
  const right = el('div', 'tl-group end'); right.append(make);
  bar.append(left, mid, right);
  const tw = el('div', 'tracks-wrap'); tw.id = 'tracksWrap';
  const tracks = el('div', 'tracks'); tracks.id = 'tracks';
  const ruler = el('div', 'ruler'); ruler.id = 'ruler';
  const pic = el('div', 'track'); pic.id = 'trackPic';
  const snd = el('div', 'track sound'); snd.id = 'trackSnd';
  const head = el('div', 'playhead'); head.id = 'playhead';
  tracks.append(ruler, pic, snd, head); tw.append(tracks);
  const filmNote = el('div', 'tl-film'); filmNote.id = 'tlFilm'; filmNote.hidden = true;
  bottom.append(bar, note, filmNote, tw);
  wrap.append(top, bottom); page.append(wrap);
  tlPaintFilm();
  for (const c of T.clips) c.kind = kindOf(c.name);
  ruler.addEventListener('pointerdown', e => { ruler.setPointerCapture(e.pointerId); const seek = ev => { const r = ruler.getBoundingClientRect(); tlSeek((ev.clientX - r.left) / T.z); }; seek(e); ruler.onpointermove = seek; ruler.onpointerup = () => { ruler.onpointermove = null; }; });
  await loadBin();
  fitMonitor();
  // the whole project in view when the page opens: pictures and every sound, none running off the right edge
  const room = tw.clientWidth - 40;
  if (room > 100) T.z = Math.max(8, Math.min(70, room / (tlEnd() + 1)));
  paintTracks(); tlSeek(0);
}
/* The monitor has the shape the film will have, as large as its corner of the page allows. */
function fitMonitor() {
  const cell = $('monitorCell'), mon = $('monitor'); if (!cell || !mon) return;
  const ar = ({landscape: 16 / 9, portrait: 9 / 16, square: 1})[T.shape] || 16 / 9;
  const maxH = innerWidth <= 720 ? Math.min(cell.clientWidth / ar, innerHeight * 0.42) : cell.clientHeight;
  const w = Math.max(120, Math.min(cell.clientWidth, maxH * ar));
  mon.style.width = Math.floor(w) + 'px'; mon.style.height = Math.floor(w / ar) + 'px';
}
new ResizeObserver(() => fitMonitor()).observe($('page-timeline'));
async function loadBin(more) {
  if (!more) { T.bin = []; T.binRead = 0; T.binTotal = 0; }
  const r = await api(`/api/gallery?project=${encodeURIComponent(S.projects.active)}&limit=120&offset=${T.binRead}`);
  if (r.ok) { T.bin = [...T.bin, ...r.data.items.filter(i => i.kind !== 'text')]; T.binRead += r.data.items.length; T.binTotal = r.data.total; }
  const bin = $('bin'); bin.replaceChildren();
  const head = el('div', 'bin-head'); head.append(el('strong', '', currentProject().name), el('span', 'num', r.ok ? T.binTotal + (T.binTotal === 1 ? ' item' : ' items') : ''));  // the Gallery's word for the same count
  bin.append(head);
  const grid = el('div', 'bin-grid');
  for (const item of T.bin) grid.append(binItem(item));
  bin.append(grid);
  const left = T.binTotal - T.binRead;
  if (left > 0) { const b = el('button', 'ghost bin-more', (left <= 120 ? `Show the ${left} older ${left === 1 ? 'item' : 'items'}` : `Show 120 more of the ${left} older items`)); b.onclick = () => loadBin(true); bin.append(b); }
  bin.append(el('p', 'help', T.bin.length ? 'Press to add to the end, or drag to a place on the timeline.' : 'Whatever you make in this project appears here.'));
}
function binItem(item) {
  const d = el('div', 'bin-item'); d.title = item.caption || item.prompt || '';
  if (item.kind === 'image' || item.kind === 'video') { const i = el('img'); i.src = item.thumb; i.alt = ''; i.loading = 'lazy'; d.append(i); }
  else { const wf = el('div', 'wf'); d.append(wf); api('/peaks/' + encodeURIComponent(item.name)).then(r => { if (r.ok) { T.peaks.set(item.name, r.data.peaks); waveBars(wf, r.data.peaks); } }); }
  d.addEventListener('pointerdown', e => binDrag(e, item, d));
  return d;
}
function binDrag(e, item, source) {
  e.preventDefault();
  const start = [e.clientX, e.clientY]; let ghost = null;
  const move = ev => {
    if (!ghost && Math.hypot(ev.clientX - start[0], ev.clientY - start[1]) > 6) { ghost = el('div', 'drag-ghost'); if (item.thumb) { const i = el('img'); i.src = item.thumb; i.alt = ''; ghost.append(i); } document.body.append(ghost); }
    if (ghost) { ghost.style.left = (ev.clientX - 46) + 'px'; ghost.style.top = (ev.clientY - 30) + 'px'; }
  };
  const up = ev => {
    window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up);
    if (!ghost) { addToTimeline(item, null); return; }
    ghost.remove();
    const tr = $('tracks').getBoundingClientRect();
    if (ev.clientX >= tr.left && ev.clientX <= tr.right && ev.clientY >= tr.top - 10 && ev.clientY <= tr.bottom + 20) addToTimeline(item, Math.max(0, (ev.clientX - tr.left) / T.z));
  };
  window.addEventListener('pointermove', move); window.addEventListener('pointerup', up);
}
async function addToTimeline(item, at) {
  if (S.page !== 'timeline') { /* from the studio: add and stay */ }
  if (item.kind === 'text') return;
  const proj = currentProject();
  if (S.page !== 'timeline') { const p = currentProject(); T.clips = p.timeline.clips.map(c => ({...c, kind: kindOf(c.name)})); T.sounds = p.timeline.sounds.map(s => ({...s})); T.shape = p.timeline.shape || 'landscape'; }
  const info = await loadMediaInfo(item.name);
  if (item.kind === 'audio') {
    const seconds = info.seconds || 5;
    const start = at === null || at === undefined ? tlLastSoundEnd() : at;
    T.sounds.push({name: item.name, start, seconds, trim: 0, gain: 1});
  } else {
    const seconds = item.kind === 'image' ? 4 : (info.seconds || 4);
    const c = {name: item.name, seconds, trim: 0, kind: item.kind};
    if (at === null || at === undefined) T.clips.push(c);
    else T.clips.splice(tlIndexAt(at), 0, c);
  }
  await tlSaveNow();
  if (S.page === 'timeline') { paintTracks(); tlSeek(T.t); } else toast('Added to the timeline.');
}
function tlLastSoundEnd() { return Math.max(0, ...T.sounds.map(s => s.start + s.seconds)); }
function tlIndexAt(sec) { let t = 0; for (let i = 0; i < T.clips.length; i++) { if (sec < t + T.clips[i].seconds / 2) return i; t += T.clips[i].seconds; } return T.clips.length; }
function tlSave() { clearTimeout(T.saveTm); T.saveTm = setTimeout(tlSaveNow, 450); }
async function tlSaveNow() {
  const body = {clips: T.clips.map(c => ({name: c.name, seconds: c.seconds, trim: c.trim})), sounds: T.sounds.map(s => ({name: s.name, start: s.start, seconds: s.seconds, trim: s.trim, gain: s.gain})), shape: T.shape};
  const r = await api('/api/projects/' + encodeURIComponent(S.projects.active) + '/timeline', body);
  if (!r.ok) notice(r.data.error || 'The timeline could not be saved.', 'warn');
  const p = currentProject(); if (p) p.timeline = body;
}
function paintTracks() {
  if (!$('tracks')) return;
  const end = tlEnd() + 8;
  const width = Math.max($('tracksWrap').clientWidth - 22, end * T.z);
  $('tracks').style.width = width + 'px';
  const ruler = $('ruler'); ruler.replaceChildren();
  const every = T.z >= 70 ? 1 : T.z >= 30 ? 2 : T.z >= 14 ? 5 : 15;
  for (let s = 0; s * T.z < width; s += every) { const m = el('span', '', s + 's'); m.style.left = (s * T.z) + 'px'; ruler.append(m); }
  const pic = $('trackPic'); pic.replaceChildren();
  let x = 0;
  T.clips.forEach((c, i) => {
    const b = el('div', 'block' + (T.sel && T.sel.kind === 'clip' && T.sel.i === i ? ' sel' : ''));
    b.style.left = (x * T.z) + 'px'; b.style.width = Math.max(14, c.seconds * T.z - 2) + 'px';
    const tiles = el('div', 'tiles');
    if (kindOf(c.name) === 'video') {
      // As many frames as fit the block at their own shape, each taken from its share of the clip (the strip holds ten,
      // evenly spaced), instead of the strip's first frames repeated across a wide block.
      const bw = Math.max(14, c.seconds * T.z - 2), n = Math.max(1, Math.min(10, Math.round(bw / (62 * 16 / 9))));
      tiles.classList.add('frames');
      for (let k = 0; k < n; k++) {
        const f = el('i'); const idx = n === 1 ? 0 : Math.round(k * 9 / (n - 1));
        f.style.backgroundImage = `url("/strip/${encodeURIComponent(c.name)}")`;
        f.style.backgroundPosition = `${idx / 9 * 100}% 0`;
        tiles.append(f);
      }
    } else { tiles.style.backgroundImage = `url("/thumb/${encodeURIComponent(c.name)}")`; tiles.classList.add('still'); }  // one picture, filling its block
    b.append(tiles, el('div', 'lab', c.seconds.toFixed(1) + ' s'));
    const edge = el('div', 'edge'); b.append(edge);
    bindClip(b, edge, i); c._el = b;
    pic.append(b);
    x += c.seconds;
  });
  if (!T.clips.length) pic.append(el('div', 'hint', 'Pictures and clips go here. Add one from the right.'));
  const snd = $('trackSnd'); snd.replaceChildren();
  T.sounds.forEach((s, i) => {
    const b = el('div', 'block snd' + (T.sel && T.sel.kind === 'sound' && T.sel.i === i ? ' sel' : ''));
    b.style.left = (s.start * T.z) + 'px'; b.style.width = Math.max(14, s.seconds * T.z - 2) + 'px';
    const cv = el('canvas'); b.append(cv);
    b.append(el('div', 'lab', s.seconds.toFixed(1) + ' s'));
    const edge = el('div', 'edge'); b.append(edge);
    bindSound(b, edge, i);
    snd.append(b);
    drawPeaks(cv, s);
  });
  if (!T.sounds.length) snd.append(el('div', 'hint', 'Voices and music go here.'));
  tlSeek(T.t);
}
async function drawPeaks(cv, s) {
  let peaks = T.peaks.get(s.name);
  if (!peaks) { const r = await api('/peaks/' + encodeURIComponent(s.name)); if (!r.ok) return; peaks = r.data.peaks; T.peaks.set(s.name, peaks); }
  const w = cv.clientWidth || 100, h = cv.clientHeight || 40;
  cv.width = w * devicePixelRatio; cv.height = h * devicePixelRatio;
  const g = cv.getContext('2d'); g.scale(devicePixelRatio, devicePixelRatio);
  const info = await loadMediaInfo(s.name); const total = info.seconds || s.seconds;
  g.fillStyle = 'rgba(255,255,255,.72)';
  for (let x = 0; x < w; x += 2) {
    const sec = s.trim + (x / w) * s.seconds;
    const p = peaks[Math.min(peaks.length - 1, Math.floor(sec / total * peaks.length))] || 0;
    const bar = Math.max(1, p * (h - 12));
    g.fillRect(x, (h - bar) / 2 + 3, 1.3, bar);
  }
}
function select(sel) { T.sel = sel; for (const b of document.querySelectorAll('.block')) b.classList.remove('sel'); }
function bindClip(b, edge, i) {
  b.onpointerdown = e => {
    if (e.target === edge) return;
    select({kind: 'clip', i}); b.classList.add('sel', 'drag');
    b.setPointerCapture(e.pointerId);
    const startX = e.clientX, origin = T.clips[i], baseLeft = parseFloat(b.style.left);
    let idx = i;
    b.onpointermove = ev => {
      const left = baseLeft + ev.clientX - startX;
      b.style.left = left + 'px';
      // The place is judged by the block's leading edge in the direction it is moving (its left edge going left, its
      // right edge going right), so a long block dropped with its front at the start of the track goes to the start.
      const lead = (ev.clientX < startX ? left : left + b.offsetWidth) / T.z;
      let t = 0, want = 0;
      const others = T.clips.filter(c => c !== origin);
      for (; want < others.length; want++) { if (lead < t + others[want].seconds / 2) break; t += others[want].seconds; }
      if (want !== idx) { idx = want; T.clips = others; T.clips.splice(idx, 0, origin); paintSiblings(b, origin); select({kind: 'clip', i: idx}); }
    };
    b.onpointerup = () => { b.onpointermove = null; b.classList.remove('drag'); paintTracks(); tlSave(); };
  };
  edge.onpointerdown = e => {
    e.stopPropagation(); edge.setPointerCapture(e.pointerId);
    const c = T.clips[i], startX = e.clientX, orig = c.seconds;
    edge.onpointermove = ev => { c.seconds = Math.max(.3, orig + (ev.clientX - startX) / T.z); clipClamp(c); b.style.width = (c.seconds * T.z - 2) + 'px'; };
    edge.onpointerup = () => { edge.onpointermove = null; paintTracks(); tlSave(); };
  };
}
function clipClamp(c) { if (kindOf(c.name) === 'video') { const d = (T.media.get(c.name) || {}).seconds; if (d) c.seconds = Math.min(c.seconds, Math.max(.3, d - c.trim)); } }
function paintSiblings(dragged, origin) { let x = 0; for (const c of T.clips) { if (c !== origin && c._el) c._el.style.left = (x * T.z) + 'px'; x += c.seconds; } }
function bindSound(b, edge, i) {
  b.onpointerdown = e => {
    if (e.target === edge) return;
    select({kind: 'sound', i}); b.classList.add('sel', 'drag'); b.setPointerCapture(e.pointerId);
    const s = T.sounds[i], startX = e.clientX, orig = s.start;
    b.onpointermove = ev => { s.start = Math.max(0, orig + (ev.clientX - startX) / T.z); b.style.left = (s.start * T.z) + 'px'; };
    b.onpointerup = () => { b.onpointermove = null; b.classList.remove('drag'); tlSave(); };
  };
  edge.onpointerdown = e => {
    e.stopPropagation(); edge.setPointerCapture(e.pointerId);
    const s = T.sounds[i], startX = e.clientX, orig = s.seconds;
    edge.onpointermove = ev => { const d = (T.media.get(s.name) || {}).seconds || orig; s.seconds = Math.max(.3, Math.min(d - s.trim, orig + (ev.clientX - startX) / T.z)); b.style.width = (s.seconds * T.z - 2) + 'px'; };
    edge.onpointerup = () => { edge.onpointermove = null; paintTracks(); tlSave(); };
  };
}
function tlRemoveSel() {
  if (!T.sel) { toast('Select something on the timeline first.'); return; }
  if (T.sel.kind === 'clip') T.clips.splice(T.sel.i, 1); else T.sounds.splice(T.sel.i, 1);
  T.sel = null; paintTracks(); tlSave();
}
function clipAt(t) { let x = 0; for (let i = 0; i < T.clips.length; i++) { if (t < x + T.clips[i].seconds) return {clip: T.clips[i], offset: t - x, index: i}; x += T.clips[i].seconds; } return null; }
function tlSeek(sec) {
  T.t = Math.max(0, Math.min(sec, tlEnd()));
  const head = $('playhead'); if (head) head.style.left = (T.t * T.z) + 'px';
  const time = $('tlTime'); if (time) time.textContent = clock(Math.min(T.t, tlFilm())) + ' / ' + clock(tlFilm());
  tlPaintNote();
  showFrame(false);
}
let monitorKey = '';
function showFrame(playing) {
  const mon = $('monitor'); if (!mon) return;
  const at = clipAt(T.t);
  if (!at) { if (monitorKey !== 'empty') { monitorKey = 'empty'; mon.replaceChildren(el('div', 'empty', T.clips.length ? 'End of the film.' : 'Add a picture or clip to begin.')); } return; }
  const kind = kindOf(at.clip.name);
  const key = at.clip.name + ':' + at.index;
  if (monitorKey !== key) {
    monitorKey = key;
    if (kind === 'image') { const i = el('img'); i.src = '/media/' + encodeURIComponent(at.clip.name); i.alt = ''; mon.replaceChildren(i); }
    else { const v = el('video'); v.src = '/media/' + encodeURIComponent(at.clip.name); v.muted = false; v.playsInline = true; mon.replaceChildren(v); }
  }
  const v = mon.querySelector('video');
  if (v) { const want = at.clip.trim + at.offset; if (Math.abs(v.currentTime - want) > .25) v.currentTime = want; if (playing && v.paused) v.play().catch(() => {}); if (!playing && !v.paused) v.pause(); }
}
function audioFor(s) { if (!T.audio.has(s.name)) { const a = el('audio'); a.src = '/media/' + encodeURIComponent(s.name); a.preload = 'auto'; T.audio.set(s.name, a); } return T.audio.get(s.name); }
function syncSounds() {
  for (const s of T.sounds) {
    const a = audioFor(s); const inside = T.playing && T.t >= s.start && T.t < s.start + s.seconds;
    if (inside) { const want = s.trim + (T.t - s.start); if (Math.abs(a.currentTime - want) > .3) a.currentTime = want; a.volume = Math.min(1, s.gain ?? 1); if (a.paused) a.play().catch(() => {}); }
    else if (!a.paused) a.pause();
  }
}
function tlPlay() {
  if (!T.clips.length) { toast('Add a picture or clip first.'); return; }
  if (T.t >= tlFilm() - .05) T.t = 0;
  T.playing = true; $('tlPlay').classList.add('on');
  let last = performance.now();
  const step = now => {
    if (!T.playing) return;
    T.t += (now - last) / 1000; last = now;
    if (T.t >= tlFilm()) { tlSeek(tlFilm()); tlPause(); return; }
    const head = $('playhead'); if (head) head.style.left = (T.t * T.z) + 'px';
    const time = $('tlTime'); if (time) time.textContent = clock(T.t) + ' / ' + clock(tlFilm());
    showFrame(true); syncSounds();
    T.raf = requestAnimationFrame(step);
  };
  T.raf = requestAnimationFrame(step);
}
function tlPause() { T.playing = false; const b = $('tlPlay'); if (b) b.classList.remove('on'); cancelAnimationFrame(T.raf); for (const a of T.audio.values()) a.pause(); const v = $('monitor') && $('monitor').querySelector('video'); if (v) v.pause(); }
async function tlMake() {
  if (!T.clips.length) { toast('Add a picture or clip first.'); return; }
  if (S.sending) return;
  S.sending = true;
  await tlSaveNow();
  const pname = currentProject().name.trim();
  // "Boat film" makes a film called "Boat film", not "Boat film film"
  const r = await api('/api/create', {lane: 'film', name: /\bfilm$/i.test(pname) ? pname : pname + ' film', timeline: {clips: T.clips.map(c => ({name: c.name, seconds: c.seconds, trim: c.trim})), sounds: T.sounds, shape: T.shape}});
  sendFinished(r);
  if (!r.ok) { notice(r.data.error || 'That could not be started.', 'warn'); return; }
  T.filmJob = r.data.id; T.filmDone = null;
  begin(r.data, false);
  tlPaintFilm();
}
/* The film being made, and then the film, on this page: a person who pressed Make the film here should not have to go
   looking for it on the Studio page. */
function tlPaintFilm() {
  const box = $('tlFilm'); if (!box) return;
  const job = T.filmJob ? S.jobs.find(j => j.id === T.filmJob) : null;
  const done = T.filmDone;
  if (!job && !done) { box.hidden = true; return; }
  box.hidden = false;
  if (job && job.state === 'running') {
    const t = Craft.read(job);
    if (box.dataset.state !== 'running') { box.dataset.state = 'running'; box.replaceChildren(); const c = Craft.make('film', 'mini'); box.append(c.el, el('b', '', 'Making your film'), el('span', 'num', '')); box.craft = c; const stop = el('button', 'ghost', 'Stop'); stop.onclick = () => stopJob(job.id); box.append(stop); }
    box.craft.update(t);
    box.querySelector('span').textContent = Craft.words(t);
    return;
  }
  if (job && job.state !== 'done' && !done) {
    box.dataset.state = job.state; box.replaceChildren(el('b', '', job.state === 'cancelled' ? 'Stopped. No film was made.' : 'The film could not be made.'), el('span', '', job.message || ''));
    return;
  }
  const item = done || (job && itemFromJob(job));
  if (!item) { box.hidden = true; return; }
  if (box.dataset.state === 'done:' + item.name) return;
  box.dataset.state = 'done:' + item.name; box.replaceChildren();
  if (S.page === 'timeline' && $('bin')) loadBin();  // the new film is one more item in this project, and the bin says so at once
  if (item.thumb) { const img = el('img'); img.src = item.thumb; img.alt = ''; box.append(img); }
  const facts = [item.seconds ? `${Math.round(item.seconds * 10) / 10} seconds` : '', item.dimensions || ''].filter(Boolean).join(', ');
  box.append(el('b', '', 'Your film is ready'), el('span', 'num', facts + '. It is in the gallery too.'));
  const open = el('button', 'primary', 'Watch it'); open.onclick = () => { go('studio'); openItem(item); };
  const dl = el('a', 'chip', 'Download'); dl.href = item.url; dl.setAttribute('download', item.name || '');
  box.append(open, dl);
}
