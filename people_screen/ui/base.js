'use strict';
const $ = id => document.getElementById(id);
const IC = {
  image: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.2 3.4 2.7 3.1-2.4L20 16.6"/>',
  voice: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v2.5"/>',
  music: '<path d="M9.5 18V6.2l10-2V16"/><circle cx="7" cy="18" r="2.5"/><circle cx="17" cy="16" r="2.5"/>',
  edit: '<path d="M4 20l9.5-9.5M14.5 3.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9zM19 12l.5 1.5L21 14l-1.5.5L19 16l-.5-1.5L17 14l1.5-.5z"/>',
  video: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M10 9.2l5 2.8-5 2.8z"/>',
  animation: '<circle cx="6" cy="12" r="2.3" opacity=".4"/><circle cx="12" cy="12" r="2.3" opacity=".7"/><circle cx="18" cy="12" r="2.3"/>',
  text: '<path d="M4 19.5h4l10.2-10.2a2 2 0 00-2.8-2.8L5.2 16.7z"/><path d="M13.5 8l2.8 2.8"/>',
  recipe: '<circle cx="5.5" cy="12" r="2.5"/><circle cx="18.5" cy="6.5" r="2.5"/><circle cx="18.5" cy="17.5" r="2.5"/><path d="M8 11l8-3.5M8 13l8 3.5"/>',
  studio: '<rect x="3.5" y="4.5" width="17" height="15" rx="2.5"/><path d="M8 4.5v15"/>',
  gallery: '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/><rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
  timeline: '<rect x="3.5" y="6" width="9" height="5" rx="1"/><rect x="13.5" y="6" width="7" height="5" rx="1"/><rect x="3.5" y="14" width="13" height="4.5" rx="1"/>',
  models: '<path d="M12 3.5l8 4.3v8.4l-8 4.3-8-4.3V7.8zM4.2 7.9l7.8 4.2 7.8-4.2M12 12.1v8.3"/>',
  help: '<circle cx="12" cy="12" r="8.5"/><path d="M9.6 9.6a2.5 2.5 0 014.8.9c0 1.7-2.4 2-2.4 3.6"/><circle cx="12" cy="16.9" r=".6" fill="currentColor"/>',
};
function icon(name) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${IC[name] || ''}</svg>`; }
const LANES = [
  {id: 'image', label: 'Picture', place: 'Describe a picture. For example: a lighthouse at dusk, fog rolling in, one warm window'},
  {id: 'video', label: 'Video', place: 'Describe a short scene. For example: a tabby cat walks across a sunlit wooden porch'},
  {id: 'voice', label: 'Voice', place: 'Type the words you want read aloud'},
  {id: 'music', label: 'Music', place: 'Describe the mood and instruments. For example: slow piano and soft strings, hopeful'},
  {id: 'animation', label: 'Animate', place: ''},
  {id: 'text', label: 'Writing', place: 'A one minute script about why a lighthouse keeper keeps a log book'},
  {id: 'edit', label: 'Edit', place: 'What should change? For example: make the sky stormy'},
  {id: 'recipe', label: 'Recipes', place: ''},
];
const WRITE_PLACE = {script: 'A one minute script about why a lighthouse keeper keeps a log book', caption: 'What should the captions do? For example: warm and short, for a family album', rewrite: 'Paste a rough prompt and it will be rewritten'};
const S = {page: 'studio', lane: 'image', catalog: null, hold: {active: false}, focus: null, item: null, jobs: [], others: [], lastStates: {},
  model: 'flux2-klein-4b', size: 'landscape', style: 'none', steps: null, seed: null, count: 1, live: true, voice: 'kokoro', speed: 1, description: '', duration: 30, lyrics: '', musicSeed: null,
  template: 'title', look: 'night', animFont: 'clean', shape: 'landscape', animSeconds: 5, direction: 'in',
  previewUrl: null, previewKey: '', previewSeq: 0, previewTimer: null, picking: null,
  textTask: 'script', writer: '9b', length: 60, tone: 'plain', target: 'image',
  recipe: null, recipeValues: {}, boardKey: '', tool: 'bigger', source: null, seedLane: null, modelChosen: false, wanted: null, away: false, rewrites: [], whyKey: '', previewWait: false, scale: 2, videoSeconds: 5, videoShape: 'landscape', videoModel: 'ltx-2.5-q8',
  parent: null, film: [], galleryOffset: 0, galleryFav: false, galleryKind: '', galleryScope: 'project', galleryText: '', galleryHidden: false, comparing: false, picks: [], enhance: null, undoText: null, sending: false, pinned: false, wasWaiting: {}, projects: null, starters: null, hold_shown: false,
  words: {}, advanced: false, mine: new Set()};  // words: what was typed in each lane; mine: the jobs this page started, the only ones that may take the stage on their own

/* A 401 means this device is no longer signed in (the session ended, or the passcode was removed), so the page
   goes back to the front door, which shows the sign-in page. Once is enough. */
function signedOut(r) {
  if (r.status !== 401 || S.signedOut) return false;
  S.signedOut = true;
  location.replace('/');
  return true;
}
async function api(path, body) {
  const opts = body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)};
  try {
    const r = await fetch(path, opts);
    if (signedOut(r)) return {ok: false, status: 401, data: {error: 'Please sign in first.'}};
    const data = await r.json().catch(() => ({}));
    return {ok: r.ok, status: r.status, data};
  } catch (e) {
    return {ok: false, status: 0, data: {error: 'The Studio cannot be reached from this computer right now.'}};
  }
}
async function signOut() {
  await api('/api/signout', {});
  S.signedOut = true;
  location.replace('/');
}
function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = text;
  return n;
}
/* A length of time in plain words: 20 seconds, 1.5 minutes, 13 minutes. */
function aboutTime(s) { s = Math.max(1, Math.round(s)); if (s === 1) return '1 second'; if (s < 60) return `${s} seconds`; const m = s / 60; if (m < 10) { const r = Math.round(m * 2) / 2; return `${r} ${r === 1 ? 'minute' : 'minutes'}`; } return `${Math.round(m)} minutes`; }
/* A range in plain words: 2 to 3 minutes, 40 seconds to 1.5 minutes. One figure when the two say the same. */
function aboutRange(a, b) {
  const x = aboutTime(a), y = aboutTime(b);
  if (x === y) return x;
  const unit = t => t.replace(/^[\d.]+ /, '');
  return unit(x) === unit(y) || (unit(x) === 'minute' && unit(y) === 'minutes') ? `${x.split(' ')[0]} to ${y}` : `${x} to ${y}`;
}
function clock(s) { s = Math.max(0, Math.round(s)); return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0'); }
function when(iso) { const d = new Date(iso); return isNaN(d) ? '' : d.toLocaleString(undefined, {month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit'}); }
function titleCase(s) { return s.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()); }
let toastTimer;
function toast(text) {
  const t = $('toast'); t.textContent = text; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 2600);
}
function notice(text, cls, actions) {
  const n = $('notice');
  n.hidden = !text; n.className = 'notice' + (cls ? ' ' + cls : '');
  const p = n.querySelector('p');
  p.textContent = text || '';
  if (actions && actions.length) { const row = el('span', 'notice-acts'); for (const a of actions) { const b = el('button', 'why-act', a.label); b.onclick = a.go; row.append(b); } p.append(row); }
  roomForNotice();
}
/* The starter page moves down so a notice never covers its headline. */
function roomForNotice() { const n = $('notice'); document.documentElement.style.setProperty('--notice-room', n.hidden ? '0px' : (n.offsetHeight + 8) + 'px'); }
$('notice').querySelector('button').onclick = () => { $('notice').hidden = true; roomForNotice(); };
/* The nightly pause is a band of its own under the header, not a card floating over the page: everything below it moves
   down by its height, so it never covers the lane tabs, the Timeline's controls or anything else. Closing it gives the
   room back, and the same words do not come back until they change. */
function holdBand(text) {
  const b = $('holdBand');
  const show = !!text && S.bandClosed !== text;
  if (show && b.querySelector('p').textContent !== text) b.querySelector('p').textContent = text;
  b.hidden = !show;
  document.documentElement.style.setProperty('--band', show ? b.offsetHeight + 'px' : '0px');
}
$('holdBand').querySelector('button').onclick = () => { S.bandClosed = $('holdBand').querySelector('p').textContent; holdBand(''); };
new ResizeObserver(() => { if (!$('holdBand').hidden) document.documentElement.style.setProperty('--band', $('holdBand').offsetHeight + 'px'); }).observe($('holdBand'));
function closePopovers() { for (const id of ['queuePop', 'projectPop', 'variationPop', 'morePop', 'personPop']) $(id).hidden = true; $('personBtn').setAttribute('aria-expanded', 'false'); }
/* who is signed in on this device, and the way out */
function openPerson() {
  const pop = $('personPop'); const btn = $('personBtn');
  if (!pop.hidden) { closePopovers(); return; }
  closePopovers();
  pop.replaceChildren();
  pop.append(el('h4', '', 'Signed in as ' + (S.person || 'you')));
  pop.append(el('p', 'pop-note', 'This device stays signed in for 30 days. Passcodes are made and removed on the Mac that runs NeoVak.'));
  const help = el('button', 'pop-row menu-row', 'How this works'); help.setAttribute('role', 'menuitem'); help.onclick = () => { closePopovers(); openKeys(); };  // on a phone the header has no room for the ? button, so the help lives here too
  const out = el('button', 'pop-row menu-row', 'Sign out of this device'); out.setAttribute('role', 'menuitem'); out.onclick = signOut;
  pop.append(help, out);
  placePopover(pop, btn, true);
  btn.setAttribute('aria-expanded', 'true');
}
$('personBtn').onclick = openPerson;
function placePopover(pop, anchor, alignRight) {
  pop.hidden = false;
  const a = anchor.getBoundingClientRect();
  const w = pop.offsetWidth;
  pop.style.top = (a.bottom + 8) + 'px';
  pop.style.left = Math.max(12, Math.min(innerWidth - w - 12, alignRight ? a.right - w : a.left)) + 'px';
}
document.addEventListener('pointerdown', e => {
  if (!e.target.closest('.popover') && !e.target.closest('#queueBtn,#projectBtn,#varBtn,#moreBtn,#personBtn')) closePopovers();
});

/* pages */
function go(page) {
  S.page = page;
  if (page !== 'gallery' && S.picking) { S.picking = null; S.galleryKind = ''; S.galleryScope = 'project'; }  // leaving the picker ends it
  document.body.dataset.page = page;
  $('page-studio').style.visibility = page === 'studio' ? '' : 'hidden';
  $('page-gallery').hidden = page !== 'gallery';
  $('page-timeline').hidden = page !== 'timeline';
  $('page-models').hidden = page !== 'models';
  for (const b of $('pages').children) b.classList.toggle('sel', b.dataset.page === page);
  for (const b of $('phoneTabs').children) b.classList.toggle('sel', b.dataset.page === page);
  closePopovers();
  if (page !== 'studio') document.querySelector('.inspector').classList.remove('open');
  if (page === 'gallery') openGalleryPage();
  if (page === 'timeline') openTimeline();
  if (page === 'models') openModels();
  if (page !== 'timeline') tlPause();
}
