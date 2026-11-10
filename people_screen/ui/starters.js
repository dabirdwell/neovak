'use strict';
const HERO = {
  image: ['What shall we make?', 'Pick a starting point, or type your own idea below. Everything is made on this machine.'],
  video: ['A few seconds of something.', 'Describe a scene, or start from one of your pictures. Picture and sound are made together. A clip takes several minutes.'],
  voice: ['Give it a voice.', 'Type the words and pick who says them. Press a play button to hear each voice first.'],
  music: ['Name a mood.', 'Describe the feeling and the instruments. A short piece takes a few minutes.'],
  animation: ['Words, set in motion.', 'A title, a name, a slow move over a picture. A still appears as you type.'],
  text: ['Start with a sentence.', 'Say what you need. A writer on this machine drafts it. The first one after a rest can take a few minutes.'],
  edit: ['Fix it, grow it, cut it out.', 'Choose a picture, then change it, enlarge it, remove its background or repair its faces. The original is always kept.'],
  recipe: ['', ''],
};
const WRITING = [
  ['A one minute explainer', 'A one minute script explaining how a lighthouse stays lit through a storm', 'script'],
  ['A warm welcome', 'A thirty second welcome for visitors to a small town library', 'script'],
  ['A product story', 'A short, plain story about the handmade bread from a neighborhood bakery', 'script'],
  ['Captions for a family album', 'Warm and short captions for a family album', 'caption'],
  ['Clearer words for a picture', 'a cat in space, make it good', 'rewrite'],
];
const VOICE_LINES = [
  ['A friendly hello', 'Hello there. It is good to finally hear what I sound like.'],
  ['Opening of a story', 'The last train out of the valley left at nine, and she had decided not to be on it.'],
  ['Calm and clear', 'Take a slow breath in. Hold it for a moment. And let it go.'],
  ['For a video', 'Every great idea begins the same way: with someone saying, what if?'],
];
function paintWall() {
  const w = $('wall'); w.replaceChildren();
  const m = S.starters, lane = S.lane;
  if (!m) return;
  const [title, sub] = HERO[lane] || HERO.image;
  if (title) { const h = el('div', 'wall-head'); const t = el('div'); t.append(el('h1', '', title), el('p', '', sub)); h.append(t); w.append(h); }
  // An idea tile fills in the words and the shape. The quality stays the one in the Quality row (Quick to begin with), so
  // the first press makes a picture in about half a minute; Polished and the rest are one press away.
  const useText = (text, more) => { const extra = {...(more || {})}; delete extra.model; Object.assign(S, extra); const t = $('prompt'); t.value = text; updateComposer(); renderPanel(); t.focus(); t.style.height = 'auto'; t.style.height = Math.min(180, Math.max(42, t.scrollHeight)) + 'px'; const at = text.indexOf('[your subject]'); if (at >= 0) t.setSelectionRange(at, at + 14); };
  if (lane === 'image') {
    paintQualityPick(w);
    if (m.images.length) {
      w.append(sectionTitle('Ideas', 'Press one to fill in the words. Change anything you like.'));
      const grid = el('div', 'mosaic');
      m.images.forEach(s => grid.append(aspectTile(tile({src: '/starters/' + s.file, lift: s.lift ? '/starters/' + s.lift : null, title: s.title, onclick: () => useText(s.prompt, {size: s.size, model: s.model, style: 'none', seed: null})}), s.width / s.height)));
      w.append(grid);
    }
    if (m.looks.length) {
      w.append(sectionTitle('Looks', 'The same fox, drawn ten ways. Pick one and describe your own subject.'));
      const grid = el('div', 'looks');
      m.looks.forEach(s => grid.append(tile({src: '/starters/' + s.file, lift: s.lift ? '/starters/' + s.lift : null, title: s.title, onclick: () => useText(`[your subject], ${s.tail}`, {size: s.size, model: s.model, style: 'none', seed: null})})));
      w.append(grid);
    }
  } else if (lane === 'video') {
    w.append(sectionTitle('Ideas', 'Each one is a real clip made from these words. Press one to start from it, and to see it play.'));
    const grid = el('div', 'mosaic');
    m.video.forEach(s => grid.append(aspectTile(tile({src: '/starters/' + s.poster, video: '/starters/' + s.file, title: s.title, onclick: () => useText(s.prompt)}), 16 / 9.6)));
    w.append(grid);
  } else if (lane === 'voice') {
    // On a desktop the Settings panel beside the wall lists the same five voices, each with its sample to play, so the
    // wall leaves them out there (hear-voices) and keeps the lines to say; a phone, whose panel is a sheet, keeps both.
    const hearHead = sectionTitle('Hear each voice', 'A real recording from each one, made on this machine.'); hearHead.classList.add('hear-voices');
    w.append(hearHead);
    const rows = el('div', 'rows hear-voices');
    // In the same order as the Settings panel, each with its own description rather than the one sentence every sample reads.
    const voices = (S.catalog || {}).voices || [];
    const order = s => { const i = voices.findIndex(v => v.id === s.id); return i < 0 ? 99 : i; };
    [...m.voices].sort((a, b) => order(a) - order(b)).forEach(s => { const v = voices.find(x => x.id === s.id); rows.append(voiceCard({...s, note: v && v.note ? v.note : ''})); });
    for (const v of voices.filter(v => !m.voices.some(s => s.id === v.id))) rows.append(voiceCard({id: v.id, title: v.label, text: 'No sample recorded yet. Choose it in Settings and press Generate to hear it.', note: v.note || '', file: null}));
    w.append(rows);
    w.append(sectionTitle('Something to say', ''));
    const lines = el('div', 'rows');
    VOICE_LINES.forEach(([t, text]) => { const c = el('button', 'card-row'); const tx = el('div', 't'); tx.append(el('b', '', t), el('span', '', text)); c.append(tx); c.onclick = () => useText(text); lines.append(c); });
    w.append(lines);
  } else if (lane === 'music') {
    w.append(sectionTitle('Moods', 'Short pieces made from these words on this machine.'));
    const rows = el('div', 'rows');
    m.music.forEach(s => rows.append(musicCard(s, () => useText(s.prompt))));
    w.append(rows);
  } else if (lane === 'animation') {
    w.append(sectionTitle('Kinds of animation', 'Press one to start from it, and to see it move.'));
    const grid = el('div', 'mosaic');
    // in the same order as the kinds above the words box, so the two lists on one screen read alike
    const kinds = (((S.catalog || {}).animation || {}).templates || []).map(t => t.id);
    const at = s => { const i = kinds.indexOf(s.template); return i < 0 ? 99 : i; };
    [...m.animation].sort((a, b) => at(a) - at(b)).forEach(s => grid.append(aspectTile(tile({src: '/starters/' + s.poster, video: '/starters/' + s.file, title: s.title, capTop: true, onclick: () => { S.template = s.template; if (s.look) S.look = s.look; if (s.font) S.animFont = s.font; if (s.direction) S.direction = s.direction; paintTemplates(); useText(s.text); }}), 16 / 9)));
    w.append(grid);
  } else if (lane === 'text') {
    w.append(sectionTitle('Starting points', ''));
    const rows = el('div', 'rows');
    WRITING.forEach(([t, text, task]) => { const c = el('button', 'card-row'); const tx = el('div', 't'); tx.append(el('b', '', t), el('span', '', text)); c.append(tx); c.onclick = () => { S.textTask = task; paintTemplates(); useText(text); }; rows.append(c); });
    w.append(rows);
  } else if (lane === 'edit') {
    w.append(sectionTitle('What these tools do', 'Slide across a picture to compare before and after. Then choose one of your own.'));
    const grid = el('div', 'rows'); grid.dataset.least = '200';  // the four samples side by side on a desktop, so none is cut by the composer
    m.edit.forEach(s => {
      const c = el('button', 'split');
      const a = el('img'); a.src = '/starters/' + s.before; a.alt = 'Before'; const b = el('img', 'after'); b.src = '/starters/' + s.after; b.alt = 'After';
      const bar = el('div', 'bar');
      c.append(a, b, bar); c.style.setProperty('--cut', '50%');
      const cap = el('div', 'tile-cap', s.title); c.append(cap);
      c.addEventListener('pointermove', e => { const r = c.getBoundingClientRect(); c.style.setProperty('--cut', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%'); });
      c.onclick = () => { S.tool = s.id === 'change' ? 'change' : s.id; renderPanel(); pickFromGallery('Choose a picture to edit'); };
      grid.append(c);
    });
    w.append(grid);
    const pick = el('button', 'primary', 'Choose a picture'); pick.style.marginTop = '18px'; pick.onclick = () => pickFromGallery('Choose a picture to edit'); w.append(pick);
  }
  if (['voice', 'music', 'text', 'edit'].includes(lane)) recentRow(w, lane);
  requestAnimationFrame(justifyAll);
}
/* The lanes whose ideas are a few lines of words also show the last pieces made in them, in this project, so the stage
   above the composer holds the person's own work and not an empty band. Pressing one opens it. */
const RECENT_TITLE = {voice: 'Your recent recordings', music: 'Your recent music', text: 'Your recent writing', edit: 'Your recent edits'};
function recentRow(w, lane) {
  const mine = (S.film || []).filter(x => !x.hidden && (lane === 'text' ? x.kind === 'text' : lane === 'edit' ? x.lane === 'edit' : x.lane === lane)).slice(0, 3);
  if (!mine.length) return;
  w.append(sectionTitle(RECENT_TITLE[lane], 'From this project. Press one to open it.'));
  const rows = el('div', 'rows recent');
  for (const it of mine) {
    const c = el('button', 'card-row recent-card');
    if (it.thumb) { const im = el('img', 'recent-thumb'); im.src = it.thumb; im.alt = ''; c.append(im); }
    else if (it.kind === 'text') c.append(el('div', 'recent-page', (it.excerpt || '').slice(0, 90)));
    else { const wf = el('div', 'wavebar recent-wave'); c.append(wf); api('/peaks/' + encodeURIComponent(it.name)).then(r => { if (r.ok) waveBars(wf, r.data.peaks.slice(0, 40)); }); }
    const tx = el('div', 't');
    const facts = [it.model, it.seconds ? `${Math.round(it.seconds)} seconds long` : '', it.time ? when(it.time) : ''].filter(Boolean).join(', ');
    tx.append(el('b', '', shortWords(it.caption || it.prompt || 'Untitled', 70)), el('span', '', facts));
    c.append(tx);
    c.onclick = () => openItem(it);
    rows.append(c);
  }
  w.append(rows);
}
/* The one choice that decides how long the first picture takes, in plain sight on the wall: a quick picture in about
   half a minute, or the polished one in about a minute and a half. Pressing one keeps it for every idea on the wall;
   the full list of eight is in Settings. The times come from the server, for the settings as they stand. */
const QUICK_PICK = ['flux2-klein-4b', 'z-image-turbo'];
function paintQualityPick(w) {
  const c = S.catalog; if (!c) return;
  const rows = QUICK_PICK.map(id => realAsk(c.image_models.find(x => x.id === id))).filter(Boolean);
  if (rows.length < 2) return;
  const box = el('div', 'quality-pick'); box.setAttribute('role', 'group'); box.setAttribute('aria-label', 'Quality of the next picture');
  box.append(el('span', 'lbl', 'Quality'));
  for (const r of rows) {
    const watched = !!(r.live && S.live && !r.liveOff);
    const secs = (!watched && plainTimeFor(r.id)) || timeFor(r.id) || r.seconds;
    const b = el('button', 'qp' + (S.model === r.id ? ' sel' : ''));
    b.disabled = !r.runnable;
    // a few words on the wall; the whole reason is on hover, on the card in Settings and in the line under Generate. A time
    // that includes watching the picture arrive says so, as the card in Settings does.
    b.append(el('b', '', r.label), el('small', '', !r.runnable ? 'Will not fit right now' : secs ? `about ${aboutTime(secs)}${watched ? ', watching' : r.live && S.live && r.liveOff ? ', without watching' : ''}` : ''));
    b.title = r.runnable ? `${r.note || ''} ${r.badge_text || ''}`.trim() : (r.reason || r.badge_text);
    b.onclick = () => { S.model = r.id; S.modelChosen = true; S.wanted = null; S.steps = null; renderPanel(); updateComposer(); };  // updateComposer repaints this row
    box.append(b);
  }
  const other = c.image_models.find(x => x.id === S.model && !QUICK_PICK.includes(x.id));
  // a model the screen settled on by itself is not said to have been chosen by the person
  if (other) box.append(el('span', 'qp-note', S.wanted && !S.modelChosen ? `${other.label} is used for now, because it fits.` : `${other.label} is chosen in Settings.`));
  const old = w.querySelector('.quality-pick');
  if (old) old.replaceWith(box); else w.append(box);
}
/* The wall's quality row follows a choice made in Settings, and the server's time figures when they arrive. */
function refreshQualityPick() { const w = $('wall'); if (S.lane === 'image' && w.querySelector('.quality-pick')) paintQualityPick(w); }
function aspectTile(node, a) { node.dataset.a = a; return node; }
/* rows of pictures, each row exactly the width of the wall, like a contact sheet.
   Widths are whole pixels and the last tile in a row takes whatever is left, so a row can never be a fraction too wide
   and wrap. The gap is set here too, so the sum always matches what the browser lays out. */
function justifyAll() {
  for (const host of document.querySelectorAll('.mosaic')) {
    host.style.maxWidth = '';  // measured at the wall's full width, whatever the last layout narrowed it to
    const W = host.clientWidth; if (!W) continue;
    const base = W < 600 ? 150 : W < 1000 ? 210 : 280;
    // Rows that end inside the visible wall: a row cut by the wall's foot hides the names written along its tiles' lower
    // edge (and an animation's words in the middle of its poster). So the rows are made a little lower, down to two
    // thirds of their usual height, until the last row that starts in view also ends in view. A wall too short for that
    // keeps its usual rows and fades at its foot, as it says there is more below.
    const wall = $('wall'), view = wall.clientHeight - 20;
    const cutAtFoot = (sel) => {
      const w0 = wall.getBoundingClientRect().top - wall.scrollTop;
      return [...wall.querySelectorAll(sel)].some(t => { const r = t.getBoundingClientRect(), y0 = r.top - w0, y1 = y0 + r.height; return y0 < view && y1 > view + 1; });
    };
    // Four tiles on a desktop: two pairs, as large as the room above the composer allows, left aligned under the headline,
    // rather than one thin row with an empty band under it; one row of four only when the pairs would be too small.
    const tiles = [...host.children];
    if (tiles.length === 4 && W >= 800) {
      const gap = 12, top = host.getBoundingClientRect().top - (wall.getBoundingClientRect().top - wall.scrollTop);
      const ar = tiles.map(t => Number(t.dataset.a) || 1.4);
      const h = Math.floor(Math.min((W - gap) / (ar[0] + ar[1]), (W - gap) / (ar[2] + ar[3]), (view - top - gap) / 2));
      if (h >= 170) {
        host.style.gap = gap + 'px';
        tiles.forEach((t, i) => { t.style.height = h + 'px'; t.style.width = Math.floor(h * ar[i]) + 'px'; });
        host.style.maxWidth = Math.ceil(Math.max(h * (ar[0] + ar[1]), h * (ar[2] + ar[3])) + gap + 1) + 'px';
        continue;
      }
    }
    // A phone's wall is a page that scrolls under its fixed composer, so its tiles keep their size there.
    let fits = W < 600;
    // every row of tiles on the wall counts, the Looks below the ideas too, so no row's names end up under the composer;
    // a window too short for that keeps at least the ideas whole
    for (const sel of ['.mosaic > *, .looks > *', '.mosaic > *']) {
      if (fits) break;
      for (const f of [1, .9, .8, .72, .66]) { layoutMosaic(host, W, base * f); if (!cutAtFoot(sel)) { fits = true; break; } }
    }
    if (!fits || W < 600) layoutMosaic(host, W, base);
  }
  balanceWall();
}
function layoutMosaic(host, W, target) {
  {
    const gap = W < 600 ? 10 : 12;
    host.style.gap = gap + 'px';
    const tiles = [...host.children];
    let row = [], sum = 0;
    const flush = (full) => {
      if (!row.length) return;
      const room = W - gap * (row.length - 1);
      const h = full ? room / sum : Math.min(target, room / sum);
      const widths = row.map(t => Math.floor(h * Number(t.dataset.a)));
      if (full) widths[widths.length - 1] = room - widths.slice(0, -1).reduce((a, b) => a + b, 0);
      row.forEach((t, i) => { t.style.height = Math.floor(h) + 'px'; t.style.width = widths[i] + 'px'; });
      row = []; sum = 0;
    };
    if (tiles.length <= 4 && W >= 800) {
      // A few tiles never end on a lone one: four in two pairs while the pairs fit the wall's height, otherwise (and for
      // three or fewer) all of them in one full row.
      const pairs = tiles.length === 4 && target >= (W < 1000 ? 210 : 280);
      tiles.forEach((t, i) => { row.push(t); sum += Number(t.dataset.a) || 1.4; if (pairs && i % 2) flush(true); });
      if (row.length) flush(true);
    } else for (const t of tiles) { row.push(t); sum += Number(t.dataset.a) || 1.4; if (sum * target + gap * (row.length - 1) >= W) flush(true); }
    // a short last row is stretched too when that keeps its tiles near the size of the others; otherwise it stays left aligned
    flush(row.length && (W - gap * (row.length - 1)) / sum <= target * 1.45);
  }
}
/* Every lane's wall starts at the same place, so the headline does not jump from lane to lane. Rows of cards are laid out
   so no row ends with a lone card: as many to a row as fit, fewer when that divides them evenly, and a last row that is
   still short stretches its cards across the full width. */
function balanceWall() {
  const w = $('wall'); w.classList.toggle('short', w.scrollHeight <= w.clientHeight + 2);
  for (const host of w.querySelectorAll('.rows')) {
    const n = host.children.length, W = host.clientWidth; if (!n || !W) continue;
    const gap = 10, least = Number(host.dataset.least || 260);
    const most = Math.max(1, Math.min(n, Math.floor((W + gap) / (least + gap))));
    let c = most;
    for (let k = most; k >= Math.max(1, Math.ceil(most / 2)); k--) if (n % k === 0) { c = k; break; }
    host.style.setProperty('--per-row', c);
  }
  // A short wall on a desktop (Music, Writing, Voice) does not leave a band of nothing above the composer: its rows of
  // cards share the room left over, each a little taller, up to 44 px more. A wall of pictures keeps its own sizes.
  w.style.setProperty('--grow', '0px');
  const hosts = [...w.querySelectorAll('.rows')].filter(h => h.offsetParent !== null && h.querySelector(':scope > .card-row'));
  if (innerWidth >= 1121 && hosts.length && !w.querySelector('.mosaic')) {
    // what the content really fills: its last child's foot, not scrollHeight (which is never less than the wall itself)
    const top = w.getBoundingClientRect().top - w.scrollTop;
    const foot = Math.max(...[...w.children].filter(e => e.offsetParent !== null).map(e => e.getBoundingClientRect().bottom - top));
    const spare = w.clientHeight - foot - 30;
    const lines = hosts.reduce((a, h) => a + Math.ceil(h.children.length / (Number(h.style.getPropertyValue('--per-row')) || 1)), 0);
    if (spare > 8 && lines) w.style.setProperty('--grow', Math.min(44, Math.floor(spare / lines)) + 'px');
  }
}
new ResizeObserver(() => justifyAll()).observe($('wall'));
function sectionTitle(t, sub) { const h = el('h2', '', t); if (sub) h.append(el('small', '', sub)); return h; }
function voiceCard(s) {
  const c = el('div', 'card-row'); const b = el('button', 'play-btn'); b.setAttribute('aria-label', 'Play this voice');
  const tx = el('button', 't'); tx.style.textAlign = 'left'; tx.append(el('b', '', s.title), el('span', '', s.note || s.text));
  tx.title = s.file ? `Use this voice. The sample says: ${s.text}` : 'Use this voice'; tx.onclick = () => { S.voice = s.id; renderPanel(); updateComposer(); toast(`${s.title} will read the next one.`); };
  if (s.file) {
    const a = el('audio'); a.src = '/starters/' + s.file; a.preload = 'none';
    b.onclick = () => togglePlay(a, b);
    a.onended = () => b.classList.remove('on');
    c.append(b, tx, a);
  } else { b.disabled = true; b.classList.add('mute'); c.append(b, tx); }
  return c;
}
function musicCard(s, use) {
  const c = el('div', 'card-row'); const b = el('button', 'play-btn'); b.setAttribute('aria-label', 'Play this piece');
  const tx = el('button', 't'); tx.style.textAlign = 'left'; tx.append(el('b', '', s.title), el('span', '', s.prompt)); tx.onclick = use;
  const a = el('audio'); a.src = '/starters/' + s.file; a.preload = 'none';
  b.onclick = () => togglePlay(a, b); a.onended = () => b.classList.remove('on');
  c.append(b, tx, a); return c;
}
let nowPlaying = null;
function togglePlay(a, b) {
  if (nowPlaying && nowPlaying.a !== a) { nowPlaying.a.pause(); nowPlaying.b.classList.remove('on'); }
  if (a.paused) { a.play().catch(() => {}); b.classList.add('on'); nowPlaying = {a, b}; } else { a.pause(); b.classList.remove('on'); }
}
function surprise() {
  const m = S.starters; if (!m) return;
  const pick = xs => xs[Math.floor(Math.random() * xs.length)];
  const put = t => { $('prompt').value = t; updateComposer(); renderPanel(); };
  if (S.lane === 'image') { const s = pick(m.images.concat(m.looks)); if (s) { Object.assign(S, {size: s.size, model: s.model, style: 'none', seed: null}); put(s.prompt); } }
  else if (S.lane === 'video') { const s = pick(m.video); if (s) put(s.prompt); }
  else if (S.lane === 'music') { const s = pick(m.music); if (s) put(s.prompt); }
  else if (S.lane === 'voice') put(pick(VOICE_LINES)[1]);
  else if (S.lane === 'text') { const [t, text, task] = pick(WRITING); S.textTask = task; paintTemplates(); put(text); }
  else if (S.lane === 'animation') { const s = pick(m.animation.filter(x => x.text)); if (s) { S.template = s.template; if (s.look) S.look = s.look; paintTemplates(); put(s.text); } }
  $('prompt').focus();
}
$('surpriseBtn').onclick = surprise;
