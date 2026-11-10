'use strict';
const KEYS = [['Make it', 'Cmd Enter'], ['Pictures, video, voice and the rest', '1 to 8'], ['Focus the words', '/'], ['Surprise me', 'R'], ['Previous or next in the strip', 'Left, Right'], ['Favorite', 'F'], ['Variation', 'V'], ['Start from similar', 'S'], ['Compare', 'C'], ['Add to timeline', 'T'], ['Open how it was made', 'I'], ['Download', 'D'], ['More actions', '.'], ['Play or pause', 'Space'], ['Gallery', 'G'], ['Timeline', 'Shift T'], ['Models', 'M'], ['Studio', 'H'], ['Close anything', 'Esc'], ['This help', '?']];
function typing() { const a = document.activeElement; return a && (a.tagName === 'TEXTAREA' || (a.tagName === 'INPUT' && a.type !== 'range')); }
/* A focused scrub bar (the waveform, the clip's bar) owns the arrow keys and the space bar. */
function scrubbing() { const a = document.activeElement; return !!(a && a.getAttribute && a.getAttribute('role') === 'slider'); }
/* The help sheet: how this works, in a few plain lines, and then the keyboard. */
const HELP = [
  ['Pick what to make', 'The list down the side (across the top on a phone): Picture, Video, Voice, Music, Animate, Writing, Edit and Recipes. Each opens on a few ready ideas. Press one, or type your own words in the box.'],
  ['Press Generate', 'Everything is made on this Mac, by the picture makers, voices and writers kept on it. Nothing is sent anywhere. The grey line by the button says which one will do it, the memory it needs and about how long it will take.'],
  ['Watch it being made', 'The stage shows the work as it goes, with the time left. Stop ends it and keeps nothing. You can start more while something runs; it waits in line, and the counter at the top says how many are lined up.'],
  ['Settings', 'The panel on the right (Settings on a phone) holds the choices for the lane: size, quality, voice, length. Advanced holds the rest. Each choice says whether it fits in memory right now.'],
  ['What you made', 'Everything lands in the Gallery, in the open project. Under a result: favorite, variations, edit, make a clip, download, and More for the rest. The Timeline lays pictures, clips and sound out in order and joins them into one film.'],
  ['Memory', 'The figure at the top is the memory this Mac can spare right now. While something is being made, its model holds memory that comes back when it finishes, so each choice is judged against what will be free then, and its card says that figure. A choice that will not fit is greyed out with the reason, and a smaller one is offered instead. The coloured dot beside each choice: green has plenty of room, yellow should fit, orange is tight, red will not fit.'],
];
function openKeys() {
  const b = $('keysBody'); b.replaceChildren();
  const intro = el('div', 'help-intro');
  for (const [title, words] of HELP) { const r = el('div', 'help-row'); r.append(el('b', '', title), el('span', '', words)); intro.append(r); }
  b.append(intro);
  b.append(el('h3', 'help-h', 'Keyboard'));
  const grid = el('div', 'keys-grid');
  for (const [what, key] of KEYS) { const r = el('div', 'key-row'); r.append(el('span', '', what), el('kbd', '', key)); grid.append(r); }
  b.append(grid);
  $('keys').hidden = false;
}
$('helpBtn').onclick = openKeys; $('keysClose').onclick = () => { $('keys').hidden = true; };
$('keys').onclick = e => { if (e.target === $('keys')) $('keys').hidden = true; };
function stepFilm(delta) {
  if (!S.film.length) return;
  const i = S.item ? S.film.findIndex(x => x.name === S.item.name) : -1;
  const next = S.film[Math.max(0, Math.min(S.film.length - 1, (i < 0 ? 0 : i + delta)))];
  if (next) openItem(next);
}
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); if (S.page !== 'studio') go('studio'); generate(); return; }
  if (e.key === 'Escape') {
    if (!$('keys').hidden) $('keys').hidden = true;
    else if (!$('compare').hidden) $('compare').hidden = true;
    else if (!$('how').hidden) closeHow();
    else if (!$('queuePop').hidden || !$('projectPop').hidden || !$('variationPop').hidden || !$('morePop').hidden || !$('personPop').hidden) closePopovers();
    else if (S.picking) go('studio');
    else if (S.page !== 'studio') go('studio');
    else if (S.item) { S.item = null; setAmbient(null); render(); }
    else if ($('panel').classList.contains('open')) $('panel').classList.remove('open');
    else if (focusJob()) { S.focus = null; S.away = true; toast('It is still being made. Press its ring in the strip to go back to it.'); render(); }
    return;
  }
  if (typing() || e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key;
  if (k >= '1' && k <= '8') { e.preventDefault(); go('studio'); S.item = null; setAmbient(null); yieldStage(LANES[Number(k) - 1].id); setLane(LANES[Number(k) - 1].id); return; }
  if (k === '/') { e.preventDefault(); go('studio'); $('prompt').focus(); return; }
  if (k === '?') { openKeys(); return; }
  if (k === 'g') { go('gallery'); return; }
  if (k === 'T' && e.shiftKey) { go('timeline'); return; }
  if (k === 'm') { go('models'); return; }
  if (k === 'h') { go('studio'); return; }
  if (S.page === 'timeline') {
    if (k === ' ') { e.preventDefault(); T.playing ? tlPause() : tlPlay(); }
    if (k === 'Delete' || k === 'Backspace') { e.preventDefault(); tlRemoveSel(); }
    return;
  }
  if (S.page !== 'studio') return;
  if (scrubbing() && (k === 'ArrowLeft' || k === 'ArrowRight' || k === ' ')) return;
  if (k === 'ArrowLeft') { e.preventDefault(); stepFilm(1); return; }
  if (k === 'ArrowRight') { e.preventDefault(); stepFilm(-1); return; }
  if (k === 'r') { e.preventDefault(); surprise(); return; }  // it puts the cursor in the words, and the letter must not follow it there
  const it = S.item; if (!it) return;
  if (k === ' ' && (it.kind === 'video' || it.kind === 'audio')) { e.preventDefault(); const m = $('canvas').querySelector('video,audio'); if (m) (m.paused ? m.play() : m.pause()); return; }
  if (k === 'f' && it.name) { setFavorite(it, !it.favorite).then(() => { paintActions(it); }); return; }
  if (k === 'd' && it.url) { const d = $('actions').querySelector('a[download]'); if (d) d.click(); return; }
  if (k === '.' ) { const m = $('moreBtn'); if (m) m.click(); return; }
  if (k === 'v' && it.kind === 'image') { const b = $('varBtn'); if (b) b.click(); return; }
  if (k === 's') { e.preventDefault(); moreAction('Start from similar'); return; }
  if (k === 'c') { compareWithPrevious(it); return; }
  if (k === 't' && it.name) { addToTimeline(it); return; }
  if (k === 'i' && it.how) { openHow(); return; }
});
(async function start() {
  buildLanes();
  setLane('image');
  await refreshProjects();
  const st = await api('/api/starters');
  if (st.ok) { S.starters = st.data; paintWall(); }
  await refreshStatus();
  go('studio');
  resumeEnhance();
  pollQueue();
  setInterval(refreshStatus, 8000);
})();
