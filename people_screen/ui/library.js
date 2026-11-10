'use strict';
/* projects */
async function refreshProjects() {
  const r = await api('/api/projects');
  if (!r.ok) return;
  S.projects = r.data;
  const p = currentProject();
  $('projectName').textContent = p ? p.name : 'Project';
  refreshFilm();
}
function currentProject() { return S.projects ? S.projects.projects.find(p => p.id === S.projects.active) : null; }
$('projectBtn').onclick = () => {
  const pop = $('projectPop'); if (!pop.hidden) { closePopovers(); return; }
  closePopovers(); paintProjectPop();
  placePopover(pop, $('projectBtn'), false);
};
function paintProjectPop() {
  const pop = $('projectPop'); pop.replaceChildren();
  pop.append(el('h4', '', 'Projects'));
  for (const p of S.projects.projects) pop.append(projectRow(p));
  const add = el('div', 'field'); add.style.padding = '8px 6px 2px';
  const input = el('input'); input.type = 'text'; input.placeholder = 'New project name'; input.setAttribute('aria-label', 'New project name');
  input.className = 'proj-input';
  const go2 = el('button', 'chip', 'Create');
  const make = async () => { const n = input.value.trim(); if (!n) return; const r = await api('/api/projects', {name: n}); if (r.ok) { await refreshProjects(); closePopovers(); toast('Project created.'); S.item = null; setAmbient(null); render(); } else notice(r.data.error); };
  go2.onclick = make; input.onkeydown = e => { if (e.key === 'Enter') make(); };
  add.append(input, go2); pop.append(add);
}
function projectRow(p) {
  const row = el('div', 'pop-row proj');
  const main = el('button', 'proj-main'); const t = el('div', 't');
  t.append(el('b', '', p.name), el('span', '', `${p.count} ${p.count === 1 ? 'item' : 'items'}`));
  main.append(t); if (p.id === S.projects.active) main.append(el('span', 'dot green'));
  main.onclick = () => activateProject(p.id);
  const rename = el('button', 'pj-act', 'Rename'); rename.onclick = () => askRename(row, p);
  row.append(main, rename);
  if (S.projects.projects.length > 1) { const rm = el('button', 'pj-act', 'Remove'); rm.onclick = () => askRemove(row, p); row.append(rm); }
  return row;
}
function askRename(row, p) {
  row.replaceChildren();
  const input = el('input', 'proj-input'); input.type = 'text'; input.value = p.name; input.setAttribute('aria-label', 'Project name');
  const save = el('button', 'pj-act on', 'Save'), cancel = el('button', 'pj-act', 'Cancel');
  const finish = async () => {
    const n = input.value.trim();
    if (!n || n === p.name) { paintProjectPop(); return; }
    const r = await api('/api/projects/' + encodeURIComponent(p.id), {name: n});
    if (!r.ok) { notice(r.data.error || 'That could not be renamed.', 'warn'); return; }
    await refreshProjects(); paintProjectPop(); if (S.page === 'gallery') openGalleryPage();
  };
  save.onclick = finish; cancel.onclick = paintProjectPop;
  input.onkeydown = e => { if (e.key === 'Enter') finish(); if (e.key === 'Escape') { e.stopPropagation(); paintProjectPop(); } };
  row.append(input, save, cancel);
  input.focus(); input.select();
}
function askRemove(row, p) {
  row.replaceChildren();
  const t = el('div', 't'); t.append(el('b', '', `Remove ${p.name}?`), el('span', '', 'Its files stay in the gallery, under Everything. Its timeline goes.'));
  const yes = el('button', 'pj-act on', 'Remove'), no = el('button', 'pj-act', 'Keep');
  no.onclick = paintProjectPop;
  yes.onclick = async () => {
    const res = await fetch('/api/projects/' + encodeURIComponent(p.id), {method: 'DELETE'}).catch(() => null);
    if (res && signedOut(res)) return;
    if (!res || !res.ok) { notice('That project could not be removed.', 'warn'); paintProjectPop(); return; }
    const wasActive = p.id === S.projects.active;
    await refreshProjects(); paintProjectPop(); toast('Removed. Its files are still in the gallery.');
    if (wasActive) { S.item = null; setAmbient(null); render(); if (S.page === 'gallery') openGalleryPage(); if (S.page === 'timeline') openTimeline(); }
  };
  row.append(t, yes, no);
}
async function activateProject(id) {
  await api('/api/projects/' + encodeURIComponent(id), {active: true});
  await refreshProjects(); closePopovers();
  S.item = null; setAmbient(null); render();
  if (S.page === 'gallery') openGalleryPage();
  if (S.page === 'timeline') openTimeline();
}

/* Out of the hidden pieces, back to the gallery as it was. */
function leaveHidden() { S.galleryHidden = false; S.galleryOffset = 0; openGalleryPage(); }
/* gallery page: every file in this project, or everything */
function pickFromGallery(title) { S.picking = title; S.galleryKind = 'image'; S.galleryScope = 'all'; S.galleryFav = false; S.galleryText = ''; go('gallery'); }
function openGalleryPage() {
  const page = $('page-gallery'); page.replaceChildren();
  const head = el('div', 'page-head');
  const proj = currentProject();
  const h = el('h2', '', S.picking || (S.galleryHidden ? 'Hidden pieces' : S.galleryScope === 'project' && proj ? proj.name : 'Everything'));
  const count = el('span', 'count num'); count.id = 'galleryCount';
  head.append(h, count);
  // The hidden pieces are a view of their own with a plain way out, not a filter to find and press again.
  if (S.galleryHidden) { const back = el('button', 'chip back-to-gallery', 'Back to the gallery'); back.onclick = leaveHidden; head.append(back); }
  // The filters are one scrolling row of chips (This project, Everything, the kinds, Favorites, Hidden) so a phone shows
  // them in one line instead of a stack; the search and the three actions sit on their own line.
  const filters = el('div', 'gal-filters');
  const chipFor = (label, on, go) => { const b = el('button', 'opt' + (on ? ' sel' : ''), label); b.onclick = go; return b; };
  for (const [id, label] of [['project', 'This project'], ['all', 'Everything']]) filters.append(chipFor(label, S.galleryScope === id, () => { S.galleryScope = id; openGalleryPage(); }));
  filters.append(el('i', 'gap'));
  for (const [id, label] of [['', 'All'], ['image', 'Pictures'], ['video', 'Clips'], ['sound', 'Sound'], ['text', 'Writing']]) filters.append(chipFor(label, S.galleryKind === id, () => { S.galleryKind = id; openGalleryPage(); }));
  filters.append(el('i', 'gap'));
  filters.append(chipFor(S.galleryFav ? 'Showing favorites' : 'Favorites', S.galleryFav, () => { S.galleryFav = !S.galleryFav; openGalleryPage(); }));
  const hid = chipFor('Hidden', S.galleryHidden, () => { S.galleryHidden = !S.galleryHidden; openGalleryPage(); }); hid.title = S.galleryHidden ? 'Showing the pieces you have hidden. Press again to go back to the gallery.' : 'Pieces you have hidden from the gallery. Nothing is deleted.'; hid.setAttribute('aria-pressed', String(S.galleryHidden)); filters.append(hid);
  const tools = el('div', 'gal-tools');
  const search = el('input', 'search'); search.type = 'search'; search.placeholder = 'Search the words'; search.value = S.galleryText; search.setAttribute('aria-label', 'Search the words');
  let tm; search.oninput = () => { clearTimeout(tm); tm = setTimeout(() => { S.galleryText = search.value.trim(); S.galleryOffset = 0; $('grid').replaceChildren(); loadGallery(); }, 260); };
  tools.append(search);
  const toTl = el('button', 'chip', 'See as a timeline'); toTl.onclick = () => go('timeline'); tools.append(el('span', 'grow'), toTl);
  const cmp = el('button', 'chip', 'Compare two'); cmp.id = 'compareToggle'; cmp.onclick = () => setCompareMode(!S.comparing); tools.append(cmp);
  const add = el('button', 'chip', 'Add a file'); add.onclick = pickFile; tools.append(add);
  page.append(head, filters, tools);
  const grid = el('div', 'grid'); grid.id = 'grid'; page.append(grid);
  const more = el('button', 'ghost more', 'Show more'); more.id = 'more'; more.hidden = true; more.onclick = loadGallery; page.append(more);
  const bar = el('div', 'compare-bar'); bar.id = 'compareBar'; bar.hidden = true;
  const txt = el('span'); txt.id = 'compareText'; const go2 = el('button', 'primary', 'Compare'); go2.id = 'compareGo'; go2.disabled = true; go2.onclick = () => showCompare(S.picks[0].item, S.picks[1].item);
  bar.append(txt, go2); page.append(bar);
  S.comparing = false; S.picks = [];
  S.galleryOffset = 0; loadGallery();
}
async function loadGallery() {
  const scope = S.galleryScope === 'project' && S.projects ? `&project=${encodeURIComponent(S.projects.active)}` : '';
  const q = `offset=${S.galleryOffset}&limit=48&favorites=${S.galleryFav ? 1 : 0}&hidden=${S.galleryHidden ? 1 : 0}${scope}&kind=${S.galleryKind}&text=${encodeURIComponent(S.galleryText)}`;
  const r = await api('/api/gallery?' + q);
  if (!r.ok) { notice(r.data.error || 'The gallery could not be loaded.'); return; }
  const {items, total} = r.data;
  $('galleryCount').textContent = total + (total === 1 ? ' item' : ' items');
  for (const item of items) $('grid').append(card(item));
  S.galleryOffset += items.length;
  $('more').hidden = S.galleryOffset >= total;
  if (!total) $('grid').append(el('p', 'help', S.galleryHidden ? 'Nothing is hidden. Point at a piece and press Hide to tuck it away without deleting it.' : S.galleryFav ? 'Nothing marked as a favorite yet.' : S.galleryScope === 'project' ? 'Nothing in this project yet. Whatever you make will appear here. You can also drop a file anywhere on this page.' : 'Nothing here yet.'));
}
function card(item) {
  const c = el('div', 'card'); c.tabIndex = 0;
  const th = el('div', 'thumb');
  if (item.kind === 'image' || item.kind === 'video') {
    const img = el('img'); img.loading = 'lazy'; img.src = item.thumb; img.alt = ''; th.append(img);
    if (item.kind === 'video') th.append(el('div', 'play'));
  } else if (item.kind === 'text') th.append(el('div', 'excerpt', item.excerpt || ''));
  else {
    const wave = el('div', 'wave'); th.append(wave);
    api('/peaks/' + encodeURIComponent(item.name)).then(r => { if (r.ok) waveBars(wave, r.data.peaks); });
  }
  c.append(th);
  const cap = el('div', 'cap');
  cap.append(el('div', 'prompt', item.caption || item.prompt || 'A file'));
  const meta = el('div', 'meta num');
  if (item.model && item.model !== item.prompt && item.model !== item.caption && !(item.caption || '').startsWith(item.model + ':')) meta.append(el('span', '', item.model));  // an edit's caption already starts with its tool's name
  if (item.time) meta.append(el('span', '', when(item.time)));
  cap.append(meta); c.append(cap);
  const tools = el('div', 'card-tools');
  const fav = el('button', 'fav' + (item.favorite ? ' on' : ''));
  fav.setAttribute('aria-label', 'Favorite');
  fav.innerHTML = '<svg class="star' + (item.favorite ? ' on' : '') + '" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.9l6-.8z"/></svg>';
  fav.onclick = async ev => { ev.stopPropagation(); if (await setFavorite(item, !item.favorite)) { fav.classList.toggle('on', item.favorite); fav.querySelector('svg').classList.toggle('on', item.favorite); fav.setAttribute('aria-label', item.favorite ? 'Favorited. Press to take it off your favorites' : 'Favorite'); } };
  fav.setAttribute('aria-label', item.favorite ? 'Favorited. Press to take it off your favorites' : 'Favorite');
  const hide = el('button', 'hide-btn', item.hidden ? 'Bring back' : 'Hide');
  hide.title = item.hidden ? 'Show this piece in the gallery again' : 'Take this piece out of the gallery, the strip and the timeline bin. The file stays on disk.';
  hide.onclick = async ev => {
    ev.stopPropagation();
    const r = await api('/api/hide', {name: item.name, on: !item.hidden});
    if (!r.ok) { notice(r.data.error || 'That could not be changed.', 'warn'); return; }
    item.hidden = !item.hidden;
    c.classList.add('gone');
    setTimeout(() => {
      c.remove();
      const n = $('galleryCount'); const left = n ? Math.max(0, Number(n.textContent.split(' ')[0]) - 1) : 0;
      if (n) n.textContent = left + (left === 1 ? ' item' : ' items');
      // the last hidden piece brought back: there is nothing left to show here, so the page goes back to the gallery
      if (!item.hidden && S.galleryHidden && !left) { leaveHidden(); toast('Back in the gallery. Nothing else is hidden.'); }
    }, 260);
    if (item.hidden) S.film = S.film.filter(x => x.name !== item.name); else refreshFilm();
    paintFilm();
    toast(item.hidden ? 'Hidden. Press Hidden at the top to see it again.' : 'Back in the gallery.');
  };
  tools.append(hide, fav); c.append(tools);
  const open = () => {
    if (S.comparing) { togglePick(item, c); return; }
    if (S.picking) {
      const wantsPicture = S.lane === 'edit' || S.lane === 'video' || S.lane === 'image' || (S.lane === 'animation' && S.template === 'move') || S.lane === 'text';
      if (item.kind === 'image' || (item.kind === 'video' && !wantsPicture)) { S.source = item; S.picking = null; S.galleryKind = ''; S.galleryScope = 'project'; go('studio'); S.item = null; setAmbient(item.thumb); renderPanel(); render(); return; }
      toast(wantsPicture ? 'Please pick a picture.' : 'Please pick a picture or a clip.'); return;
    }
    go('studio'); openItem(item);
  };
  c.onclick = open; c.onkeydown = e => { if (e.key === 'Enter') open(); };
  return c;
}
function setCompareMode(on) {
  S.comparing = on; S.picks = [];
  $('compareToggle').textContent = on ? 'Cancel compare' : 'Compare two';
  $('compareBar').hidden = !on;
  $('grid').classList.toggle('comparing', on);  // while two are picked, a card's Hide and star step aside for the pick number
  for (const c of $('grid').querySelectorAll('.card')) { c.classList.remove('picked'); c.querySelector('.pick-num')?.remove(); }
  paintCompareBar();
}
function togglePick(item, node) {
  const at = S.picks.findIndex(p => p.item.name === item.name);
  if (at >= 0) { S.picks.splice(at, 1); node.classList.remove('picked'); node.querySelector('.pick-num')?.remove(); }
  else {
    if (S.picks.length === 2) { const old = S.picks.shift(); old.node.classList.remove('picked'); old.node.querySelector('.pick-num')?.remove(); }
    S.picks.push({item, node}); node.classList.add('picked');
  }
  S.picks.forEach((p, i) => { let n = p.node.querySelector('.pick-num'); if (!n) { n = el('div', 'pick-num'); p.node.append(n); } n.textContent = i + 1; });
  paintCompareBar();
}
function paintCompareBar() { $('compareText').textContent = S.picks.length < 2 ? `Pick ${2 - S.picks.length} more` : 'Ready to compare'; $('compareGo').disabled = S.picks.length !== 2; }
let cmpPair = null, cmpMode = 'side';
function showCompare(a, b) {
  cmpPair = [a, b];
  const bothImg = a.kind === 'image' && b.kind === 'image';
  if (!bothImg) cmpMode = 'side';
  $('compareMode').hidden = !bothImg;
  paintCompareView();
  $('compare').hidden = false;
}
function paintCompareView() {
  const [a, b] = cmpPair; const panes = $('comparePanes'); panes.replaceChildren();
  for (const x of $('compareMode').children) x.classList.toggle('sel', x.dataset.m === cmpMode);
  panes.classList.toggle('wipe', cmpMode === 'wipe');
  if (cmpMode === 'wipe') {
    const pane = el('div', 'pane');
    const view = el('div', 'wipe-view'); view.style.setProperty('--w', '50%');
    const i1 = el('img'); i1.src = b.url; i1.alt = ''; const i2 = el('img', 'a2'); i2.src = a.url; i2.alt = '';
    view.append(i1, i2, el('div', 'hbar'));
    const move = e => { const r = view.getBoundingClientRect(); view.style.setProperty('--w', Math.max(0, Math.min(100, (e.clientX - r.left) / r.width * 100)) + '%'); };
    view.addEventListener('pointerdown', e => { view.setPointerCapture(e.pointerId); move(e); });
    view.addEventListener('pointermove', e => { if (e.buttons || e.pointerType === 'mouse') move(e); });
    const cap = el('div', 'wipe-cap'); cap.append(el('span', '', a.caption || a.prompt || ''), el('span', '', b.caption || b.prompt || ''));
    pane.append(view, cap); panes.append(pane);
  } else for (const item of [a, b]) {
    const pane = el('div', 'pane'); const view = el('div', 'view');
    if (item.kind === 'image') {
      const img = el('img'); img.src = item.url; img.alt = item.prompt || ''; view.append(img);
      if (/^neovak_cutout_/.test(item.name || '')) view.classList.add('checker');  // a cut-out on the checkerboard its gallery card shows, so the missing background reads as missing
    }
    else if (item.kind === 'video') { view.append(videoPlayer(item.url, item.thumb)); }
    else { view.append(audioCard(item)); }
    pane.append(view, el('div', 'prompt', item.caption || item.prompt || ''));
    const meta = el('div', 'meta num');
    if (item.seed !== null && item.seed !== undefined) meta.append(el('span', '', `Starting number ${item.seed}`));  // no empty first word that pushes the rest in
    if (item.model) meta.append(el('span', '', item.model));
    pane.append(meta); panes.append(pane);
  }
}
for (const b of $('compareMode').children) b.onclick = () => { cmpMode = b.dataset.m; paintCompareView(); };
$('compareClose').onclick = () => { $('compare').hidden = true; };
/* A variation or a clip from a picture is compared with the picture it came from; anything else with the one before it. */
async function compareWithPrevious(item) {
  if (item.parent && item.lane !== 'edit') {
    const r = await api('/api/item/' + encodeURIComponent(item.parent));
    if (r.ok) { showCompare(item, r.data); return; }
  }
  const i = S.film.findIndex(x => x.name === item.name);
  const other = S.film.slice(i + 1).concat(S.film.slice(0, Math.max(0, i))).find(x => x.kind === item.kind && x.name !== item.name);
  if (other) showCompare(item, other); else toast('There is nothing else like it in this project yet.');
}

/* files from outside */
function pickFile() { const inp = el('input'); inp.type = 'file'; inp.accept = 'image/png,image/jpeg,image/webp,video/mp4,audio/*'; inp.onchange = () => { if (inp.files[0]) uploadFile(inp.files[0]); }; inp.click(); }
async function uploadFile(file) {
  toast('Adding ' + file.name);
  try {
    const r = await fetch('/api/upload', {method: 'POST', headers: {'Content-Type': file.type || 'application/octet-stream', 'X-File-Name': encodeURIComponent(file.name || '')}, body: file});
    if (signedOut(r)) return;
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { notice(data.error || 'That file could not be added.', 'warn'); return; }
    toast('Added to this project.');
    S.film = [data, ...S.film.filter(x => x.name !== data.name)]; paintFilm(); render();
    if (S.page === 'gallery') openGalleryPage();
    if (S.page === 'timeline') openTimeline();
  } catch (e) { notice('That file could not be added.', 'warn'); }
}
let dragDepth = 0;
window.addEventListener('dragenter', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) { dragDepth++; $('dropVeil').hidden = false; } });
window.addEventListener('dragover', e => { if (e.dataTransfer && [...e.dataTransfer.types].includes('Files')) e.preventDefault(); });
window.addEventListener('dragleave', () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) $('dropVeil').hidden = true; });
window.addEventListener('drop', e => { e.preventDefault(); dragDepth = 0; $('dropVeil').hidden = true; for (const f of e.dataTransfer.files) uploadFile(f); });
