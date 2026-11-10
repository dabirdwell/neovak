'use strict';
let modelsTimer;
const M = {data: null, hoverGb: null};
async function openModels() {
  const page = $('page-models');
  if (!M.data) page.replaceChildren(el('p', 'help', 'Looking at what is on this machine...'));
  await refreshModels();
}
async function refreshModels() {
  clearTimeout(modelsTimer);
  if (S.page !== 'models') return;
  const r = await api('/api/models');
  if (r.ok) { M.data = r.data; paintModels(); }
  modelsTimer = setTimeout(refreshModels, 3000);
}
function fitColor(badge) { return ({green: 'var(--green)', yellow: 'var(--yellow)', orange: 'var(--orange)', red: 'var(--red)'})[badge] || 'var(--grey)'; }
let modelStructure = '';
function paintModels() {
  const d = M.data, page = $('page-models');
  const key = JSON.stringify(d.groups.map(g => g.rows.map(r => r.id + r.runnable + r.reason))) + JSON.stringify(d.offers.map(o => o.id + o.state)) + (d.memory.method || '');
  const free = d.memory.available_gb, total = d.memory.total_gb, safety = d.memory.safety_gb || 4;
  const judged = d.memory.judged_gb === undefined || d.memory.judged_gb === null ? free : d.memory.judged_gb;
  // the header, the big figure and every fit badge on this page come from the same reading, so they agree
  if (free !== null && free !== undefined) { $('memText').textContent = innerWidth <= 720 ? Math.floor(free) + ' GB free' : free.toFixed(1) + ' GB free'; $('memFill').style.width = Math.min(100, free / 64 * 100) + '%'; }
  // The judged figure is the larger of what is free right now and what was free the last time nothing ran, so a
  // session of back to back work is never judged against a stale low reading; the words say which one it is.
  const running = d.memory.running;
  // "For making things" is what is left once the reserve is kept: the free part of the bar, which the reserve sits beside.
  const usable = gb => Math.max(0, gb - safety).toFixed(1);
  const bigText = () => free === null ? 'Memory check not answering' : d.memory.quiet ? `${usable(judged)} GB for making things the last time nothing was running` : `${usable(free)} GB free for making things`;
  const subText = () => d.memory.quiet ? `${free.toFixed(1)} GB is free right now${running ? ' while work is running' : ', with the last job still letting go of its memory'}. New work waits its turn, so each model below is judged against the ${judged.toFixed(1)} GB that was free the last time nothing ran, less the ${safety} GB always kept in reserve.`
    : d.memory.wait ? `Work is running now, so each model below will be checked when its turn comes. ${safety} GB is always kept in reserve.`
    : running ? `${free.toFixed(1)} GB of this Mac's ${total} GB is free beside the work running now, and ${safety} GB of that is always kept in reserve. More comes back when the work finishes.`
    : `${free.toFixed(1)} GB of this Mac's ${total} GB is free, and ${safety} GB of that is always kept in reserve. Each model below says whether it fits right now.`;
  if (key === modelStructure) {
    $('memBig').textContent = bigText(); $('memSub').textContent = subText();
    paintBar();
    paintGhost();
    for (const g of d.groups) for (const r of g.rows) { paintFit(r); paintFacts(r); }
    for (const o of d.offers) paintOffer(o);
    return;
  }
  modelStructure = key;
  page.replaceChildren();
  const head = el('div', 'page-head'); head.append(el('h2', '', 'Models'), el('span', 'count', 'What is on this machine, and whether it will fit right now'));
  page.append(head);
  const hero = el('div', 'mem-hero');
  const row = el('div', 'row'); const big = el('div', 'big'); big.id = 'memBig';
  big.textContent = bigText();
  const sub = el('div', 'sub'); sub.id = 'memSub'; sub.textContent = subText();
  row.append(big, sub);
  const track = el('div', 'mem-track');
  const used = el('div', 'mem-used'); used.id = 'memUsed';
  const back = el('div', 'mem-back'); back.id = 'memBack';
  const reserve = el('div', 'mem-reserve'); reserve.style.right = '0'; reserve.style.width = (safety / total * 100) + '%';
  const ghost = el('div', 'mem-ghost'); ghost.id = 'memGhost';
  track.append(used, back, ghost, reserve);
  const legend = el('div', 'mem-legend'); legend.id = 'memLegend';
  hero.append(row, track, legend);
  if (d.memory.method_words) hero.append(el('p', 'help mem-method', d.memory.method_words));
  page.append(hero);
  paintBar();
  paintLegend();  // after the hero is on the page: it finds the legend by id, which an unattached node has not got yet
  for (const g of d.groups) {
    const sec = el('div', 'shelf-group'); sec.append(el('h3', '', g.title));
    if (g.basis) sec.append(el('p', 'help shelf-basis', g.basis));  // what the times below are for, so a lane on other settings differs for a reason
    const shelf = el('div', 'shelf');
    for (const r of g.rows) shelf.append(shelfCard(g, r));
    sec.append(shelf); page.append(sec);
  }
  const addSec = el('div', 'shelf-group'); addSec.append(el('h3', '', 'Add to this Mac'));
  addSec.append(el('p', 'help', `Only small models with an open licence are offered here. They are kept in ${d.added_dir || 'the added models folder'}. ${d.disk_free_gb ? d.disk_free_gb + ' GB free there.' : ''}`));
  const shelf = el('div', 'shelf'); shelf.style.marginTop = '10px';
  for (const o of d.offers) shelf.append(offerCard(o));
  addSec.append(shelf);
  page.append(addSec);
  const noSec = el('div', 'shelf-group'); noSec.append(el('h3', '', 'Not offered here'));
  const list = el('div', 'shelf');
  for (const n of d.not_offered) { const c = el('div', 'shelf-card'); const t = el('div', 'top'); t.append(el('span', 'name', n.label)); c.append(t, el('p', '', n.why)); list.append(c); }
  noSec.append(list); page.append(noSec);
}
/* The bar is drawn from the live reading, the same one the header shows: "In use now" is what is in use now. While work
   runs and new work is judged against the quieter figure, the part the running work will give back is shown on its own,
   lighter, between the two, so the bar and the header never disagree. */
function backGb() {
  const m = M.data.memory, free = m.available_gb, judged = m.judged_gb;
  return free !== null && free !== undefined && judged !== null && judged !== undefined && judged > free + 0.05 ? judged - free : 0;
}
function paintBar() {
  const m = M.data.memory, total = m.total_gb || 64, free = m.available_gb === null || m.available_gb === undefined ? (m.judged_gb || 0) : m.available_gb;
  const used = $('memUsed'), back = $('memBack');
  if (!used || !back) return;
  const usedPct = Math.max(0, 100 - free / total * 100), backPct = backGb() / total * 100;
  used.style.width = Math.max(0, usedPct - backPct) + '%';
  back.style.left = Math.max(0, usedPct - backPct) + '%'; back.style.width = backPct + '%';
  back.hidden = !backPct;
}
/* What the colours on the bar mean, in words under it; while a model is pointed at, what its own block means too. */
function paintLegend() {
  const lg = $('memLegend'); if (!lg) return;
  const d = M.data, safety = d.memory.safety_gb || 4;
  lg.replaceChildren();
  const key = (cls, words) => { const k = el('span', 'key'); k.append(el('i', cls), el('span', '', words)); lg.append(k); };
  key('used', 'In use now');
  if (backGb()) key('back', `${backGb().toFixed(1)} GB the work running now gives back when it ends`);
  key('free', 'Free'); key('reserve', `${safety} GB always kept in reserve`);
  if (M.hoverGb && M.hoverName) {
    const free = (d.memory.judged_gb === undefined || d.memory.judged_gb === null ? d.memory.available_gb : d.memory.judged_gb) || 0;
    key(M.hoverGb + safety <= free ? 'fits' : 'no', `${M.hoverName} would take ${M.hoverGb} GB of the free part${M.hoverGb + safety <= free ? ', and fits' : ', which is more than is free with the reserve kept'}`);
  }
}
function paintGhost() {
  const g = $('memGhost'); if (!g) return;
  const d = M.data; const gb = M.hoverGb;
  paintLegend();
  if (!gb) { g.classList.remove('show'); return; }
  const free = (d.memory.judged_gb === undefined || d.memory.judged_gb === null ? d.memory.available_gb : d.memory.judged_gb) || 0, total = d.memory.total_gb, safety = d.memory.safety_gb || 4;
  const left = 100 - free / total * 100;
  g.style.left = left + '%'; g.style.width = Math.min(100 - left, gb / total * 100) + '%';
  g.classList.add('show'); g.classList.toggle('fits', gb + safety <= free); g.classList.toggle('no', gb + safety > free);
}
function shelfCard(g, r) {
  const c = el('div', 'shelf-card');
  const top = el('div', 'top'); top.append(el('span', 'name', r.label));
  c.append(top, el('p', '', r.note || ''));
  if (r.engine) c.append(el('p', 'eng', (r.full_name ? 'Listed in LM Studio as ' + r.full_name : 'Runs on a model called ' + r.engine) + '.'));
  const fit = el('div', 'fit'); fit.dataset.fit = r.id;
  fit.append(el('span', 'num', !r.gb ? 'no model' : r.gb_kind === 'estimate' ? `about ${r.gb} GB, estimated` : r.gb_kind === 'measured' ? `${r.gb} GB, measured here` : `about ${r.gb} GB`));
  if (r.loaded) fit.append(el('span', 'num', 'In memory now'));
  const mini = el('div', 'track-mini'); const i = el('i'); mini.append(i); fit.append(mini);
  fit.append(el('span', 'fit-text'));
  c.append(fit);
  if (r.asks && r.asks.live) c.append(el('p', 'help', 'Watching a picture arrive asks for 4 GB more.'));
  if (!r.runnable && r.reason) c.append(el('p', 'why-off', r.reason));
  const foot = el('div', 'shelf-foot');
  const facts = el('span', 'num'); facts.dataset.facts = r.id;
  foot.append(facts);
  paintFacts(r, facts);
  const use = el('button', 'chip', 'Use this'); use.disabled = !r.runnable; use.dataset.fitUse = r.id;
  use.onclick = () => { const k = g.lane; if (k === 'image') { S.model = r.id; S.modelChosen = true; S.wanted = null; } if (k === 'voice') S.voice = r.id; if (k === 'video') S.videoModel = r.id; if (k === 'text') S.writer = r.id; if (k === 'edit') S.tool = r.id; S.item = null; setAmbient(null); go('studio'); setLane(k); };
  foot.append(use); c.append(foot);
  c.addEventListener('pointerenter', () => { M.hoverGb = r.gb; M.hoverName = r.label; paintGhost(); });
  c.addEventListener('pointerleave', () => { M.hoverGb = null; M.hoverName = null; paintGhost(); });
  paintFit(r, fit);
  return c;
}
/* The time, written by the same aboutTime as the Studio's cards and chip, from the same server figure. */
function paintFacts(r, span) {
  span = span || document.querySelector(`[data-facts="${CSS.escape(r.id)}"]`);
  if (!span) return;
  const t = [r.seconds ? `about ${aboutTime(r.seconds)}` : '', r.disk_gb ? `${r.disk_gb} GB on disk` : ''].filter(Boolean).join(', ');
  if (span.textContent !== t) span.textContent = t;
}
function paintFit(r, fit) {
  fit = fit || document.querySelector(`.fit[data-fit="${CSS.escape(r.id)}"]`);
  if (!fit) return;
  const free = (M.data.memory.judged_gb === undefined || M.data.memory.judged_gb === null ? M.data.memory.available_gb : M.data.memory.judged_gb) || 0;
  const i = fit.querySelector('i');
  i.style.width = Math.min(100, (r.gb || 0) / Math.max(free, 1) * 100) + '%';
  i.style.background = fitColor(r.badge);
  fit.querySelector('.fit-text').textContent = !r.runnable && r.reason !== r.badge_text ? 'Switched off' : ({green: 'Plenty of room', yellow: 'Should fit', orange: 'Tight', red: 'Will not fit now'})[r.badge] || '';
}
function offerCard(o) {
  const c = el('div', 'shelf-card'); c.dataset.offer = o.id;
  const top = el('div', 'top'); top.append(el('span', 'name', o.label), el('span', 'eng', o.engine));
  c.append(top, el('p', '', o.note));
  const facts = el('div', 'shelf-foot'); facts.append(el('span', 'num', `${o.gb_download} GB download, ${o.licence}`));
  c.append(facts);
  const bar = el('div', 'install-bar'); const i = el('i'); bar.append(i); bar.hidden = true; c.append(bar);
  const msg = el('p', 'help offer-msg'); c.append(msg);
  const foot = el('div', 'shelf-foot');
  const btn = el('button', 'primary offer-btn', 'Add'); foot.append(el('span', ''), btn);
  btn.onclick = () => (o.state === 'running' ? stopInstall(o.id) : startInstall(o.id));
  c.append(foot);
  paintOffer(o, c);
  return c;
}
function paintOffer(o, c) {
  c = c || document.querySelector(`[data-offer="${CSS.escape(o.id)}"]`);
  if (!c) return;
  const btn = c.querySelector('.offer-btn'), bar = c.querySelector('.install-bar'), msg = c.querySelector('.offer-msg');
  btn.onclick = () => (o.state === 'running' ? stopInstall(o.id) : startInstall(o.id));
  btn.disabled = o.state === 'installed';
  btn.textContent = o.state === 'installed' ? 'On this Mac' : o.state === 'running' ? 'Stop' : 'Add';
  bar.hidden = o.state !== 'running';
  if (o.state === 'running') bar.firstElementChild.style.width = Math.min(100, (o.done_gb || 0) / o.gb_download * 100) + '%';
  msg.textContent = o.message || '';
}
async function startInstall(id) { const r = await api('/api/models/install', {id}); if (!r.ok) notice(r.data.error || 'That could not start.', 'warn'); else { modelStructure = ''; refreshModels(); } }
async function stopInstall(id) { await api('/api/models/stop', {id}); toast('Stopping.'); refreshModels(); }
