'use strict';
/* lanes and the composer */
function buildLanes() {
  const nav = $('lanes');
  for (const l of LANES) {
    const b = el('button', 'lane');
    b.innerHTML = icon(l.id);
    b.append(el('span', '', l.label));
    b.setAttribute('role', 'tab'); b.dataset.lane = l.id;
    b.onclick = () => { if (S.item) { S.item = null; setAmbient(null); } yieldStage(l.id); setLane(l.id); };
    nav.append(b);
  }
  const tabs = $('phoneTabs');
  for (const [page, label] of [['studio', 'Studio'], ['gallery', 'Gallery'], ['timeline', 'Timeline'], ['models', 'Models']]) {
    const t = el('button'); t.dataset.page = page; t.innerHTML = icon(page); t.append(el('span', '', label));
    t.onclick = () => go(page); tabs.append(t);
  }
  // On a phone the help sits in the tab bar, where there is room for it at full size, rather than squeezing the header.
  const help = el('button', 'tab-help'); help.innerHTML = icon('help'); help.append(el('span', '', 'Help')); help.setAttribute('aria-label', 'How this works'); help.onclick = () => openKeys(); tabs.append(help);
  for (const p of $('pages').children) p.onclick = () => go(p.dataset.page);
  nav.addEventListener('scroll', railEdges, {passive: true});
  new ResizeObserver(railEdges).observe(nav);
  $('wall').addEventListener('scroll', wallEdge, {passive: true});
  new ResizeObserver(wallEdge).observe($('wall'));
  new MutationObserver(wallEdge).observe($('wall'), {childList: true});
  const insp = document.querySelector('.inspector-scroll');
  insp.addEventListener('scroll', panelEdge, {passive: true});
  new ResizeObserver(panelEdge).observe(insp);
  new MutationObserver(panelEdge).observe($('panelBody'), {childList: true, subtree: true});
}
/* The settings panel fades at its lower edge while there is more below it, the same sign the wall gives. */
function panelEdge() {
  const p = document.querySelector('.inspector-scroll');
  p.classList.toggle('more-down', p.scrollHeight > p.clientHeight + 2 && p.scrollTop + p.clientHeight < p.scrollHeight - 2);
}
/* The wall of ideas fades at its lower edge while there is more below, instead of a row of tiles cut in half. */
function wallEdge() {
  const w = $('wall');
  w.classList.toggle('more-down', w.scrollHeight > w.clientHeight + 2 && w.scrollTop + w.clientHeight < w.scrollHeight - 2);
}
/* On a phone the lanes are a row wider than the screen. The row fades at the edge that has more behind it, so the lanes
   out of sight are known to be there, and the chosen lane is always scrolled into view. */
function railEdges() {
  const nav = $('lanes');
  const horizontal = nav.scrollWidth > nav.clientWidth + 2;
  nav.classList.toggle('more-right', horizontal && nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 2);
  nav.classList.toggle('more-left', horizontal && nav.scrollLeft > 2);
}
function laneInfo() { return LANES.find(l => l.id === S.lane); }
/* Work carries on in the strip while the person looks at another lane, or presses Esc to get the starter page back.
   Going back to the lane of what is being made brings it back to the stage. */
function yieldStage(id) {
  const job = focusJob();
  // This page's own work in the lane being opened comes back to the stage, the running one before a waiting one,
  // whatever held the stage before (the wall, a result, or a job of another lane that is waiting its turn).
  const back = activeJobs().filter(j => j.lane === id && S.mine.has(j.id)).sort((a, b) => Number(a.waiting) - Number(b.waiting))[0];
  if (back) {
    S.away = false;
    if (!job || job.id !== back.id) { S.focus = back.id; S.item = null; S.boardKey = ''; prepareFrame(back); tick(back); }
    return;
  }
  if (job && job.lane !== id) { S.focus = null; S.away = true; toast('It is still being made. Press its ring in the strip to go back to it.'); }
}
function setSeed(value, lane) { S.seed = value === undefined ? null : value; S.seedLane = S.seed === null ? null : (lane || S.lane); }
/* The words box belongs to its lane. A picture description does not follow the person into Voice, where it would be read aloud. */
function keepWords() { S.words[S.lane] = $('prompt').value; }
/* The starting picture belongs to its lane too, like the words: a picture chosen to edit is not quietly used as the start
   of the next picture in the Picture lane. A picture handed over on purpose (Edit or Make a clip under a result) goes with
   the person: it was set just before the lane changed, so it is not the one the old lane had settled on. */
function keepSource(next) {
  S.sources = S.sources || {};
  const handed = !!S.source && S.source !== S.settledSource;  // a picture cleared in this lane is simply not kept
  if (!handed) { S.sources[S.lane] = S.source; S.source = S.sources[next] || null; }
  else S.sources[S.lane] = S.settledSource || null;
  S.settledSource = S.source;
}
function fitPrompt() { const t = $('prompt'); t.style.height = 'auto'; t.style.height = Math.min(180, Math.max(42, t.scrollHeight)) + 'px'; }
function setLane(id) {
  if (id !== S.lane) notice('');  // a message about the lane being left is not about the next one (the nightly pause has its own band)
  if (S.seed !== null && S.seedLane !== id) setSeed(null);  // a seed belongs to the lane it was chosen in
  if (id !== S.lane) { keepWords(); $('prompt').value = S.words[id] || ''; fitPrompt(); keepSource(id); }
  S.lane = id;
  for (const b of $('lanes').children) {
    b.setAttribute('aria-selected', String(b.dataset.lane === id));
    if (b.dataset.lane === id && b.scrollIntoView) b.scrollIntoView({block: 'nearest', inline: 'nearest', behavior: Craft.reduced() ? 'auto' : 'smooth'});
  }
  railEdges();
  $('prompt').placeholder = laneInfo().place || '';
  paintTemplates();
  $('enhanceBtn').hidden = !['image', 'music', 'video', 'voice'].includes(id);
  $('surpriseBtn').hidden = id === 'edit' || id === 'recipe';
  renderPanel();
  paintWall();
  render();
}
function focusJob() { return S.jobs.find(j => j.id === S.focus && j.state === 'running') || null; }
function activeJobs() { return S.jobs.filter(j => j.state === 'running'); }
function render() {
  const job = focusJob();
  const busy = !!job;
  const chainJob = busy ? job.lane === 'recipe' : S.lane === 'recipe';
  const showBoard = chainJob && !S.item && !!currentRecipe();
  $('boardWrap').hidden = !showBoard;
  $('working').hidden = !busy || (showBoard && job && job.lane === 'recipe');
  document.body.classList.toggle('making', busy);  // on a phone the composer folds to its essentials while the stage shows the work
  // A folded phone composer has one line for its example words: it keeps the first sentence, never a line cut in half.
  const full = (laneInfo() || {}).place || '', first = /^(.*?[.?]) For example/.exec(full);
  if (first) $('prompt').placeholder = busy && innerWidth <= 720 ? first[1] : full;
  if (showBoard) paintBoard();
  const showResult = !busy && !!S.item;
  document.body.classList.toggle('viewing', showResult);  // on a phone the composer folds to its essentials while a result is up, so the result has the room
  $('result').hidden = !showResult;
  $('info').hidden = !showResult;
  const showPreview = S.lane === 'animation' && !busy && !S.item && !!S.previewUrl;
  $('preview').hidden = !showPreview;
  $('wall').hidden = busy || !!S.item || showPreview || showBoard;
  $('film').hidden = !S.film.length && !activeJobs().length;
  const hint = S.lane === 'animation' ? $('wall').querySelector('.wall-head p') : null;
  if (hint) { const wait = activeJobs().length || S.previewWait; hint.textContent = 'A title, a name, a slow move over a picture. ' + (wait ? 'A still appears as you type once nothing else is running. For now, press Generate to make it.' : 'A still appears as you type.'); }
  updateComposer();
  S.settledSource = S.source;  // what this lane holds now; a change made before the next lane switch is a hand-over
  document.body.classList.remove('booting');
}
/* The model row as it really stands: Watch it arrive and a starting picture both ask for more memory. If a model only
   fits without watching it arrive, it is still offered, and that picture is made without the steps showing. */
function realAsk(m) {
  if (!m || !m.asks) return m;
  // The card shows the ask's own figure, so its reason is the ask's too: a 34 GB card says 38 GB with the reserve, not the
  // 34 GB of the plain model. A reason that is not about memory (a missing tool) is kept as it is.
  const memoryReason = !m.reason || m.reason === m.badge_text;
  const withAsk = a => a.fits ? {...m, gb: a.gb, badge: a.badge, badge_text: a.badge_text, badge_short: a.badge_short} : {...m, gb: a.gb, badge: a.badge, badge_text: a.badge_text, badge_short: a.badge_short, runnable: false, reason: memoryReason ? a.badge_text : m.reason, reason_short: memoryReason ? a.badge_short : m.reason_short};
  if (S.source) return m.runnable ? withAsk(m.asks.source) : m;
  if (S.live && m.asks.live) return m.asks.live.fits || !m.runnable ? withAsk(m.asks.live) : {...m, liveOff: true};
  return m;
}
const MODEL_LADDER = ['z-image-turbo', 'flux2-klein-4b', 'z-image', 'schnell'];
/* A picture model nobody picked by hand gives way to the best one that fits this machine right now, and comes back when it fits again. */
function settleModel() {
  if (!S.catalog || S.modelChosen || S.lane !== 'image') return;
  const row = id => realAsk(S.catalog.image_models.find(m => m.id === id));
  if (S.wanted && (row(S.wanted) || {}).runnable) { S.model = S.wanted; S.wanted = null; S.steps = null; renderPanel(); return; }
  const cur = row(S.model);
  if (!cur || cur.runnable) return;
  const best = nearestInTime(S.wanted || S.model, MODEL_LADDER.map(row))[0];
  if (best) { S.wanted = S.wanted || S.model; S.model = best.id; S.steps = null; renderPanel(); }
}
/* The models that fit, the one closest in time to the one wanted first: a person who chose Quick (about half a minute)
   gets Fast draft (under a minute), not Careful (four minutes), when Quick does not fit. */
function nearestInTime(wantedId, rows) {
  const t = m => timeFor(m.id) || m.seconds || 600;
  const w = (S.catalog.image_models || []).find(x => x.id === wantedId);
  const tw = w ? t(w) : 60;
  return rows.filter(m => m && m.runnable && m.id !== wantedId).sort((a, b) => Math.abs(Math.log(t(a) / tw)) - Math.abs(Math.log(t(b) / tw)) || t(a) - t(b));
}
function selected() {
  const c = S.catalog;
  if (!c) return null;
  if (S.lane === 'image') return realAsk(c.image_models.find(m => m.id === S.model));
  if (S.lane === 'voice') return c.voices.find(m => m.id === S.voice);
  if (S.lane === 'music') return c.music;
  if (S.lane === 'edit') return c.edit_tools.find(t => t.id === S.tool);
  if (S.lane === 'video') return c.video_models.find(m => m.id === S.videoModel);
  if (S.lane === 'animation') return c.animation;
  if (S.lane === 'text') return c.writers.find(m => m.id === S.writer);
  if (S.lane === 'recipe') return currentRecipe();
  return null;
}
/* Why Watch it arrive is off, with the figures on the screen so the sum can be checked: the model's ask with watching on, the
   reserve that is always kept, and the free figure the fit is judged against (the last quiet reading while work runs). */
function liveOffWords(m) {
  const live = m.asks && m.asks.live, j = S.judged || {};
  if (!live || j.available_gb === null || j.available_gb === undefined) return 'Watching it arrive is off for this one, because it would need about 4 GB more memory than is free right now.';
  const free = `${j.available_gb.toFixed(1)} GB ${j.quiet ? 'was free the last time nothing ran' : 'is free'}`;
  return `Watching it arrive is off for this one: it would need ${live.gb} GB plus the ${Math.round(j.safety_gb || 0)} GB reserve, and ${free}. Without it, ${m.gb} GB fits.`;
}
function paintWhy(text, actions, soft) {
  const w = $('whyBlocked'), key = text + '|' + actions.map(a => a.label).join() + (soft ? '|soft' : '');
  w.hidden = !text;
  w.classList.toggle('soft', !!soft);
  if (key === S.whyKey) return;
  S.whyKey = key;
  w.replaceChildren(el('span', '', text));
  for (const a of actions) { const b = el('button', 'why-act', a.label); b.onclick = a.go; w.append(b); }
}
/* When the choice will not run, the choices that will. */
function fitsInstead(m) {
  const c = S.catalog;
  const lists = {image: ['image_models', 'model'], video: ['video_models', 'videoModel'], voice: ['voices', 'voice'], text: ['writers', 'writer']}[S.lane];
  if (!lists || !m || m.badge !== 'red') return [];
  const fit = c[lists[0]].map(realAsk).filter(x => x.runnable && x.id !== m.id);
  return (S.lane === 'image' ? nearestInTime(m.id, fit) : fit.sort((a, b) => b.gb - a.gb)).slice(0, 2)
    .map(x => ({label: `Use ${x.label}, about ${x.gb} GB`, go: () => { S[lists[1]] = x.id; if (S.lane === 'image') { S.modelChosen = true; S.wanted = null; S.steps = null; } renderPanel(); updateComposer(); }}));
}
/* The time promised before the press. It comes from the server for the settings as they stand (the length of the clip, the
   number of pictures, the kind of writing, whether the writer is in memory), from the same place the working screen's
   figure comes from, so the row in the panel, the chip and the working screen cannot disagree. */
let estTimer, estSeq = 0;
function estimateBody() {
  const b = {lane: S.lane};
  if (S.lane === 'image') Object.assign(b, {model: S.model, size: S.size, steps: S.steps, count: S.count, live: S.live, source: S.source ? S.source.name : null});
  if (S.lane === 'voice') Object.assign(b, {voice: S.voice, prompt: $('prompt').value.trim().slice(0, 4000)});
  if (S.lane === 'music') Object.assign(b, {duration: S.duration});
  if (S.lane === 'edit') Object.assign(b, {tool: S.tool, scale: S.scale, source: S.source ? S.source.name : null});
  if (S.lane === 'video') Object.assign(b, {seconds: S.videoSeconds, shape: S.videoShape, model: S.videoModel, source: S.source ? S.source.name : null});
  if (S.lane === 'animation') Object.assign(b, {template: S.template, look: S.look, font: S.animFont, shape: S.shape, seconds: S.animSeconds, direction: S.direction});
  if (S.lane === 'text') Object.assign(b, {task: S.textTask, model: S.writer, length: S.length});
  if (S.lane === 'recipe') {
    // only the choices and numbers: the words typed do not change which settings a step is timed for
    const r = currentRecipe();
    if (r) { const v = recipeValues(r); Object.assign(b, {recipe: r.id, values: Object.fromEntries(r.inputs.filter(i => i.type !== 'text' && i.type !== 'long_text').map(i => [i.name, v[i.name]]))}); }
  }
  return b;
}
function askEstimate() {
  if (!S.catalog) return;
  const body = estimateBody(), key = JSON.stringify(body);
  if (key === S.estKey) return;
  S.estKey = key;
  clearTimeout(estTimer);
  estTimer = setTimeout(async () => {
    const seq = ++estSeq;
    const r = await api('/api/estimate', body);
    if (!r.ok || seq !== estSeq || JSON.stringify(estimateBody()) !== key) return;
    S.est = r.data;
    updateComposer();
    if (S.lane === 'recipe') paintRecipeTimes();
    if (S.page === 'studio') renderPanel();
  }, 150);
}
/* The figure for one choice in the lane's list, or null until the server has answered for these settings. */
function timeFor(id) { const e = S.est; return e && e.lane === S.lane && e.options && e.options[id] ? e.options[id] : null; }
function plainTimeFor(id) { const e = S.est; return e && e.lane === S.lane && e.plain && e.plain[id] ? e.plain[id] : null; }
function altTimeFor(id) { const e = S.est; return e && e.lane === S.lane && e.alt && e.alt[String(id)] ? e.alt[String(id)] : null; }
function updateComposer() {
  settleModel();
  const m = selected();
  const chip = $('modelChip');
  chip.querySelector('.dot').className = 'dot ' + (m ? m.badge : '');
  const est = S.est && S.est.lane === S.lane ? S.est : null;
  const secs = (m && m.liveOff && plainTimeFor(m.id)) || (est && est.chosen ? est.chosen : (m && m.seconds));
  const n = S.lane === 'image' ? S.count : 1;
  const upto = est && est.upto && est.upto > secs ? est.upto : null;  // recent runs went well past the usual figure: a range, not a time often missed
  const took = secs && S.lane !== 'recipe' ? (n > 1 ? `, about ${aboutTime(secs)} each, ${aboutTime(secs * n)} in all` : `, about ${upto ? aboutRange(secs, upto) : aboutTime(secs)}`) : '';
  const gbWords = m ? (m.loaded ? 'in memory now' : `${m.gb_kind === 'estimate' ? 'about ' : ''}${m.gb} GB`) : '';
  // What is counted in the figures is said in the chip itself: watching a picture arrive and starting from a picture
  // both ask for more memory and time than the plain figure the Models page shows.
  const extra = S.lane === 'image' && m ? (S.source ? ', from your picture' : (S.live && m.live ? (m.liveOff ? ', without watching it arrive for now' : ', watching it arrive') : '')) : '';
  const recipeTime = S.lane === 'recipe' && secs ? `, about ${aboutTime(secs)} in all` : '';
  chip.querySelector('span:last-child').textContent = m ? (S.lane === 'animation' ? `Drawn on this Mac, nothing to load${took}`
    : S.lane === 'recipe' ? `About ${m.gb} GB at its largest step${recipeTime}${m.waits ? ', waits for memory' : ''}` : `${m.label}${extra}, ${gbWords}${took}`) : (S.lane === 'text' ? 'Choose a writer' : '');
  chip.title = m ? (m.reason || m.badge_text) + (took ? ' The time is what these settings usually take here.' : '') : '';
  const lineFull = activeJobs().length >= 12;
  let block = '', why = '';
  if (S.hold.active && !heldOut()) { block = 'Paused'; why = S.hold.short || S.hold.message; }  // the reason stays under the button once the band is closed
  else if (lineFull) { block = 'Line is full'; why = 'The line holds 12 things. You can add more as soon as some of them have finished.'; }
  else if (m && !m.runnable) { block = m.badge === 'red' && (!m.reason || m.reason === m.badge_text) ? 'Not enough memory' : 'Not available'; why = m.reason || m.badge_text; }  // a missing tool is not a memory problem, whatever the memory says
  else if (S.lane === 'text' && !m) { block = 'Choose a writer'; why = 'The writer chosen before is not on the list right now. Pick another under Settings.'; }
  else if (S.lane === 'edit' && !S.source) block = 'Choose a picture first';
  else if (S.lane === 'animation' && S.template === 'move' && !S.source) block = 'Choose a picture first';
  else if (S.lane === 'recipe' && m && missingRequired(m)) {
    block = 'Fill in the steps';
    // while a recipe runs on the stage, its board is what this page is about; the empty fields of a next one are not news
    const fj = focusJob();
    why = fj && fj.lane === 'recipe' ? '' : `Still to fill in: ${missingNames(m).join(', ')}.`;
  }
  const g = $('generateBtn');
  // "Choose a picture first" is a press that opens the chooser, not a dead button beside a small link
  const opensPicker = block === 'Choose a picture first';
  g.disabled = (!!block && !opensPicker) || !m || S.sending;
  g.classList.toggle('picks', opensPicker);
  const verb = S.lane === 'edit' && m ? m.label : S.lane === 'text' ? 'Write' : S.lane === 'recipe' ? 'Start' : S.lane === 'image' && S.count > 1 ? `Make ${S.count}` : 'Generate';
  g.textContent = block || verb;
  g.title = why;
  const line = lineCounts();
  const ln = $('lineNote');
  // what a press now would do, counting everything already in the line (the work just pressed included)
  const lineText = line.n ? lineWords(line) : '';
  ln.hidden = !!block || !lineText;
  ln.textContent = lineText;
  const wanted = S.wanted && S.catalog ? S.catalog.image_models.find(x => x.id === S.wanted) : null;
  if (why) paintWhy(why, block === 'Not enough memory' ? fitsInstead(m) : [], block === 'Fill in the steps' || block === 'Paused');
  else if (S.lane === 'recipe' && m && m.waits && !(focusJob() && focusJob().lane === 'recipe')) paintWhy(m.badge_text, [], true);  // not while a recipe runs on the stage
  else if (S.lane === 'image' && wanted && m && m.id !== wanted.id) paintWhy(`${wanted.label} will not fit right now, so ${m.label} is selected.`, []);
  else if (S.lane === 'image' && m && m.liveOff) paintWhy(liveOffWords(m), [], true);
  else paintWhy('', []);
  const editing = S.lane === 'edit';
  $('prompt').hidden = S.lane === 'recipe' || (editing && !(m && m.words));
  $('recipeFields').hidden = S.lane !== 'recipe';
  const writingCaption = S.lane === 'text' && S.textTask === 'caption';
  const picks = editing || S.lane === 'video' || S.lane === 'animation' || S.lane === 'image' || writingCaption;
  $('sourceChip').hidden = !picks;
  $('sourceChip').classList.toggle('quiet', S.lane === 'image' && !S.source);
  $('sourceClear').hidden = !(S.lane !== 'edit' && S.source);
  if (picks) {
    $('sourceThumb').hidden = !S.source;
    if (S.source) $('sourceThumb').src = S.source.thumb;
    $('sourceName').textContent = S.source ? shortWords(S.source.caption || S.source.prompt || 'Your picture', 30) : (editing ? 'No picture chosen' : S.lane === 'animation' ? (S.template === 'move' ? 'No picture chosen' : 'Background (optional)') : writingCaption ? 'A picture to write about' : 'Start from a picture');
    $('sourcePick').textContent = S.source ? 'Change' : 'Choose';
  }
  $('settingsBtn').textContent = 'Settings';
  $('seedLock').hidden = S.seed === null || (S.lane !== 'image' && S.lane !== 'video');
  $('seedLock').querySelector('span').textContent = 'Starting number ' + S.seed;
  queuePreview();
  askEstimate();
  if (typeof refreshQualityPick === 'function') refreshQualityPick();
}
const MINI = {chain: 3, title: 2, move: 1, strip: 2, lines: 3, script: 3, caption: 2, rewrite: 3};
function miniFor(id) { const d = el('div', 'mini m-' + id); for (let i = 0; i < (MINI[id] || 0); i++) d.append(el('i')); return d; }
function paintTemplates() {
  const row = $('tpls');
  const isAnim = S.lane === 'animation', isText = S.lane === 'text', isRecipe = S.lane === 'recipe';
  row.hidden = !(isAnim || isText || isRecipe) || !S.catalog || (isRecipe && !S.catalog.recipes.length);
  row.replaceChildren();
  if (isRecipe && S.catalog) paintRecipeFields();
  if (row.hidden) return;
  if (isRecipe) {
    if (!currentRecipe()) S.recipe = S.catalog.recipes[0].id;
    for (const r of S.catalog.recipes) {
      const b = el('button', 'tpl two' + (r.id === S.recipe ? ' sel' : '')); b.dataset.rid = r.id;
      const t = el('span', 't'); t.append(el('b', '', r.label));
      const outcome = recipeOutcome(r);
      if (outcome) t.append(el('small', '', outcome));  // what comes out, so two recipes with similar names can be told apart
      b.append(miniFor('chain'), t);
      b.onclick = () => { S.recipe = r.id; S.item = null; setAmbient(null); paintTemplates(); renderPanel(); render(); };
      row.append(b);
    }
    return;
  }
  const items = isAnim ? S.catalog.animation.templates.map(t => ({id: t.id, label: t.label, note: t.note})) : Object.entries(S.catalog.text_tasks).map(([id, label]) => ({id, label, note: ''}));
  const current = isAnim ? S.template : S.textTask;
  for (const it of items) {
    const b = el('button', 'tpl' + (it.id === current ? ' sel' : ''));
    if (it.note) b.title = it.note;
    b.append(miniFor(it.id), el('span', '', it.label));
    b.onclick = () => {
      if (isAnim) { S.template = it.id; if (it.id === 'move' && S.source && S.source.kind === 'video') S.source = null; } else S.textTask = it.id;
      paintTemplates(); renderPanel(); updateComposer(); $('prompt').focus();
    };
    row.append(b);
  }
  $('prompt').placeholder = isAnim ? (S.catalog.animation.templates.find(t => t.id === S.template) || {}).place || '' : (WRITE_PLACE[S.textTask] || '');
}

/* recipes */
/* What a recipe gives you at the end, said as a thing, not as the name of its last step. */
const RECIPE_GIVES = {image: 'a picture', edit: 'a changed picture', video: 'a short clip', speech: 'a voice recording', music: 'a piece of music',
  text: 'a piece of writing', join: 'a clip with narration', animation: 'an animation'};
function recipeGives(r) {
  const last = (r.steps || [])[(r.steps || []).length - 1];
  if (!last) return '';
  if (/enlarg|bigger|upscal/i.test(last.label || '')) return 'a larger picture';
  return RECIPE_GIVES[last.kind] || '';
}
function recipeOutcome(r) {
  const gives = recipeGives(r);
  const made = gives ? `Gives you ${gives}.` : (r.steps || []).length ? `Ends with: ${r.steps[r.steps.length - 1].label.toLowerCase()}.` : '';
  const total = recipePlanned(r).total || r.estimate;
  const mins = total ? ` About ${aboutTime(total)}.` : '';
  return (made + mins).trim();
}
/* The time of each step for the values chosen so far (a 2 second clip is timed as one), once the server has answered
   for them; until then, and for a recipe not chosen, the figures for its usual values. */
function recipePlanned(r) {
  const e = S.est;
  if (!r || !e || e.lane !== 'recipe' || e.recipe !== r.id || !e.steps) return {};
  return {total: e.chosen, steps: e.steps};
}
function paintRecipeTimes() {
  for (const b of $('tpls').querySelectorAll('.tpl[data-rid]')) {
    const r = (S.catalog.recipes || []).find(x => x.id === b.dataset.rid), sm = b.querySelector('small');
    if (r && sm) sm.textContent = recipeOutcome(r);
  }
  if (!$('boardWrap').hidden) paintBoard();
}
function currentRecipe() { const c = S.catalog; if (!c || !c.recipes || !c.recipes.length) return null; return c.recipes.find(r => r.id === S.recipe) || c.recipes[0]; }
function recipeValues(r) {
  if (!S.recipeValues[r.id]) { const v = {}; for (const i of r.inputs) v[i.name] = i.default === null || i.default === undefined ? '' : i.default; S.recipeValues[r.id] = v; }
  return S.recipeValues[r.id];
}
function missingNames(r) { const v = recipeValues(r); return r.inputs.filter(i => i.required).filter(i => !String(v[i.name] ?? '').trim()).map(i => i.label.toLowerCase()); }
function missingRequired(r) { return missingNames(r).length; }
function paintRecipeFields() {
  const box = $('recipeFields'), r = currentRecipe();
  box.replaceChildren();
  if (!r) return;
  S.recipe = r.id;
  const v = recipeValues(r);
  const basics = r.inputs.filter(i => i.tier === 'basic');
  basics.forEach(i => {
    const span = i.type === 'long_text' && basics.filter(x => x.type === 'long_text').length === 1;
    const rf = el('div', 'rf' + (span || (basics.length % 2 && i === basics[basics.length - 1]) ? ' span' : ''));
    const id = 'rf_' + i.name;
    const lab = el('label', '', i.label + (i.required ? '' : ' (optional)')); lab.htmlFor = id;
    const input = el(i.type === 'long_text' ? 'textarea' : 'input');
    input.id = id; input.placeholder = i.place || '';
    if (i.type !== 'long_text') input.type = i.type === 'number' ? 'number' : 'text';
    input.value = v[i.name] ?? '';
    input.oninput = () => { v[i.name] = input.value; updateComposer(); };
    rf.append(lab, input); box.append(rf);
  });
}
function waveStub(n) { const w = el('div', 'wavebar'); for (let i = 0; i < 18; i++) { const b = el('i'); b.style.height = (6 + Math.abs(Math.sin(i * 1.3 + n)) * 26) + 'px'; w.append(b); } return w; }
const STEP_ICON = {image: 'image', video: 'video', speech: 'voice', music: 'music', text: 'text', animation: 'animation', edit: 'edit', join: 'timeline'};
const STEP_WORDS = {pending: 'Next', running: 'Working', waiting: 'Waiting', done: 'Done', failed: 'Stopped here', 'not run': 'Not run', cancelled: 'Stopped'};
function paintBoard() {
  const fj = focusJob();
  const job = fj && fj.lane === 'recipe' ? fj : null;
  // the board of a running recipe is named for that recipe, whichever one the composer has chosen
  const r = job ? ((S.catalog && S.catalog.recipes || []).find(x => x.id === job.recipe) || null) : currentRecipe();
  if (!job && !r) return;
  const steps = (job && job.steps && job.steps.length ? job.steps : ((r && r.steps) || []).map(s => ({id: s.id, label: s.label, state: 'pending', estimate: s.estimate_seconds, name: null})));
  $('boardTitle').textContent = job ? (job.recipe_label || (r && r.label) || 'Recipe') : r.label;
  $('boardNote').textContent = job ? (job.held ? 'A step is waiting for memory to free up. It starts by itself when there is room. Whatever is finished is kept.'
    : 'Each step starts when the one before it finishes. Whatever is finished is kept.') : (r.description || '');
  const own = job && S.mine.has(job.id);
  $('boardStop').hidden = !(job && job.can_stop && own);
  $('boardAside').hidden = !(job && job.can_stop && !own);
  if (job) $('boardAside').textContent = job.by_someone_else ? 'Someone else started this' : 'Started from another page';
  const board = $('board');
  const key = (job ? job.id : r.id) + ':' + steps.map(s => s.id).join(',');
  if (S.boardKey !== key) {
    S.boardKey = key;
    // what kind of work each step is, drawn on its card until the step has made something of its own
    const kinds = Object.fromEntries(((r && r.steps) || []).map(x => [x.id, x.kind]));
    board.replaceChildren(...steps.map((s, n) => {
      const beat = el('div', 'beat'); beat.dataset.id = s.id;
      const scene = el('div', 'scene');
      const ic = STEP_ICON[kinds[s.id]];
      if (ic) { const k = el('div', 'scene-ic'); k.innerHTML = icon(ic); scene.append(k); }
      scene.append(el('div', 'no', String(n + 1)));
      const tag = el('span', 'tag');  // above the card's picture, so it never covers what the step made
      beat.append(tag, scene, el('h4', '', s.label), el('div', 'sub'), el('div', 'craft-slot'));
      return beat;
    }));
  }
  const stepKinds = Object.fromEntries(((r && r.steps) || []).map(x => [x.id, x.kind]));
  steps.forEach(s => {
    const beat = board.querySelector(`.beat[data-id="${CSS.escape(s.id)}"]`);
    if (!beat) return;
    beat.className = 'beat ' + (s.state === 'not run' ? 'not-run' : s.state);
    const tag = beat.querySelector('.tag');
    tag.textContent = STEP_WORDS[s.state] || s.state; tag.hidden = !job;
    const scene = beat.querySelector('.scene');
    if (s.name && !scene.dataset.made) {
      scene.dataset.made = s.name;
      scene.querySelector('.no')?.remove(); scene.querySelector('.scene-ic')?.remove();
      // what the step really made: the picture or clip, the first words of a text, or the recording's own waveform
      if (s.thumb) { const img = el('img'); img.src = s.thumb; img.alt = s.label; scene.prepend(img); }
      else if (s.kind === 'text') scene.prepend(el('div', 'scene-text', s.excerpt || 'Written'));
      else { const wf = el('div', 'wavebar'); scene.prepend(wf); api('/peaks/' + encodeURIComponent(s.name)).then(r => { if (r.ok) waveBars(wf, r.data.peaks); else wf.replaceWith(waveStub(s.label.length)); }); }
    }
    const sub = beat.querySelector('.sub'), slot = beat.querySelector('.craft-slot');
    let text = '';
    if (s.state !== 'running' && slot.firstChild) slot.replaceChildren();
    if (s.state === 'waiting') text = 'Waiting for ' + (s.waiting || 'its turn');
    else if (s.state === 'running' && /memory/i.test(s.stage || '')) {
      if (slot.firstChild) slot.replaceChildren();
      text = 'Waiting for memory to free up. It starts by itself.';  // no time left is promised: the step has not begun
    } else if (s.state === 'running') {
      // the step's own numbers, read like any other job's: steps where its engine reports them, else time against its estimate
      const truth = Craft.read({step: s.step, total: s.total, elapsed: s.elapsed || 0, estimate: s.estimate, stage: s.stage, id: (job ? job.id : '') + ':' + s.id});
      // the step's own craft: a clip step counts down on the film leader the Video lane uses, a voice step is on air
      const lane = ({video: 'video', speech: 'voice', music: 'music'})[stepKinds[s.id]] || 'recipe';
      if (!slot.firstChild || slot.craftLane !== lane) { slot.replaceChildren(); const c = Craft.make(lane, 'mini'); slot.append(c.el); slot.craft = c; slot.craftLane = lane; }
      slot.craft.update(truth);
      text = s.stage === 'Finished' ? 'Finishing' : Craft.words(truth) + ' (this step)';  // the step's own figures; the strip tile and the line count the whole recipe
    } else if (s.state === 'done') text = 'Finished';
    else if (!job && (recipePlanned(r).steps || {})[s.id]) text = 'About ' + aboutTime(recipePlanned(r).steps[s.id]);  // for the values chosen so far, in words like every other lane
    else if (!job && s.estimate) text = 'About ' + aboutTime(s.estimate);
    sub.textContent = text;
  });
}
async function startRecipe() {
  const r = currentRecipe();
  if (!r || S.hold.active) return;
  if (missingRequired(r)) { toast('Please fill in each step first.'); return; }
  if (S.sending) return;
  S.sending = true; updateComposer();
  const res = await api('/api/create', {lane: 'recipe', recipe: r.id, values: recipeValues(r)});
  sendFinished(res);
  if (!res.ok) { notice(res.data.error || 'That could not be started.', res.status === 409 ? 'warn' : ''); return; }
  S.item = null; begin(res.data, true);
}
async function saveRecipe(nameInput) {
  const r = currentRecipe(); const name = nameInput.value.trim();
  if (!name) { toast('Please give it a name.'); return; }
  const res = await api('/api/recipes', {from: r.id, name, values: recipeValues(r)});
  if (!res.ok) { notice(res.data.error || 'That could not be saved.', 'warn'); return; }
  await refreshStatus();
  S.recipe = res.data.id; nameInput.value = '';
  paintTemplates(); render(); renderPanel();
  toast('Saved as ' + res.data.label + '.');
}
async function deleteRecipe() {
  const r = currentRecipe();
  const res = await fetch('/api/recipes/' + encodeURIComponent(r.id), {method: 'DELETE'}).catch(() => null);
  if (res && signedOut(res)) return;
  if (!res || !res.ok) { notice('That could not be removed.', 'warn'); return; }
  await refreshStatus();
  S.recipe = S.catalog.recipes.length ? S.catalog.recipes[0].id : null;
  paintTemplates(); render(); renderPanel(); toast('Removed.');
}

/* the animation preview */
function previewKey() { return [S.template, S.look, S.animFont, S.shape, S.direction, S.source ? S.source.name : '', $('prompt').value].join('|'); }
/* The nightly hold keeps models from loading. An animation loads none, so it is drawn during the hold like any other time. */
function heldOut() { return S.lane === 'animation'; }
function queuePreview() {
  if (S.lane !== 'animation' || activeJobs().length || !S.catalog) return;
  const key = previewKey();
  if (key === S.previewKey) return;
  S.previewKey = key;
  const t = (S.catalog.animation.templates.find(x => x.id === S.template) || {});
  if ((t.needs_words && !$('prompt').value.trim()) || (S.template === 'move' && !S.source)) { if (S.previewUrl) { S.previewUrl = null; render(); } return; }
  clearTimeout(S.previewTimer);
  S.previewTimer = setTimeout(fetchPreview, 650);
}
async function fetchPreview() {
  if (S.lane !== 'animation' || activeJobs().length) return;
  const seq = ++S.previewSeq;
  const r = await api('/api/preview', animationBody());
  if (seq !== S.previewSeq || S.lane !== 'animation' || activeJobs().length) return;
  if (!r.ok) { if (r.status === 400) notice(r.data.error); else { S.previewWait = true; render(); } return; }
  notice('');
  await new Promise(resolve => { const i = new Image(); i.onload = i.onerror = resolve; i.src = r.data.url + '?v=' + seq; });
  if (seq !== S.previewSeq) return;
  S.previewUrl = r.data.url + '?v=' + seq;
  $('previewImg').src = S.previewUrl;
  S.item = null; render();
}
function animationBody() { return {prompt: $('prompt').value.trim(), template: S.template, look: S.look, font: S.animFont, shape: S.shape, seconds: S.animSeconds, direction: S.direction, source: S.source ? S.source.name : null}; }

/* The header's memory figure. Every page shows the one reading the screen keeps (read every few seconds while work runs,
   and sent with the line, which a page asks for every second then), so two pages at the same moment agree. One decimal on
   a desktop, the same figure the cards quote; a phone keeps the word "free" and drops the decimal. "now" is said only
   while work is running, when the cards are judged against what will be free once it ends. */
function paintMemory(gb, running) {
  if (gb === null || gb === undefined) { $('memText').textContent = 'Memory check not answering'; $('memFill').style.width = '0'; return; }
  const j = S.judged || {}, later = running && j.quiet && j.available_gb !== null && j.available_gb !== undefined;
  $('memText').textContent = innerWidth <= 720 ? Math.floor(gb) + ' GB free' : gb.toFixed(1) + ' GB free' + (later ? ' now' : '');
  $('memory').title = `${gb.toFixed(1)} GB of memory this Mac can spare right now.` + (later ? ` The work running now holds some of it; each choice is judged against the ${j.available_gb.toFixed(1)} GB that will be free once it is done.` : '');
  $('memFill').style.width = Math.min(100, gb / 64 * 100) + '%';
  $('memFill').style.background = gb > 28 ? 'var(--green)' : gb > 20 ? 'var(--yellow)' : gb > 12 ? 'var(--orange)' : 'var(--red)';
}
/* status */
async function refreshStatus() {
  const r = await api('/api/status');
  if (!r.ok) { $('memText').textContent = 'Cannot reach NeoVak'; return; }
  const st = r.data; const first = !S.catalog;
  S.catalog = st.catalog; S.hold = st.hold; S.judged = (st.memory && st.memory.judged) || null;
  if (st.person && st.person !== S.person) { S.person = st.person; $('personName').textContent = st.person.split(' ')[0]; $('personBtn').title = 'Signed in as ' + st.person; $('personBtn').setAttribute('aria-label', 'Signed in as ' + st.person); }
  if (first) { paintTemplates(); renderPanel(); paintWall(); }
  paintMemory(st.memory.available_gb, !!(st.memory.judged && st.memory.judged.running));
  holdBand(st.hold.active ? (st.hold.band || st.hold.message) : '');
  const sig = JSON.stringify(st.catalog);
  if (sig !== S.catalogSig) { S.catalogSig = sig; if (S.page === 'studio') renderPanel(); }
  render();
}

/* the line of work: every job on the queue */
let queueTimer;
async function pollQueue() {
  clearTimeout(queueTimer);
  try { await readQueue(); } catch (e) { /* one bad answer must never stop the line from being followed; the next poll reads it again */ }
  queueTimer = setTimeout(pollQueue, activeJobs().length ? 700 : 4000);
}
async function readQueue() {
  const r = await api('/api/queue');
  if (r.ok) {
    S.jobs = (r.data.jobs || []).filter(j => j && j.id); S.others = (r.data.others || []).filter(Boolean); S.rewrites = (r.data.rewrites || []).filter(j => j && j.id);
    if (r.data.memory && S.page !== 'models') paintMemory(r.data.memory.available_gb, true);  // the Models page paints its own, from the same reading
    for (const j of S.jobs) if (j.mine) S.mine.add(j.id);  // this person's work, from this page or any other of theirs, after a reload too
    if (S.previewWait && !activeJobs().length && !S.others.length) { S.previewWait = false; S.previewKey = ''; }
    for (const j of S.jobs) {
      const was = S.lastStates[j.id];
      S.lastStates[j.id] = j.state;  // first, so an ending is handled once even if handling it goes wrong
      if (was === 'running' && j.state !== 'running') onJobFinished(j);
    }
    for (const j of S.jobs) {  // second, so a job that has just ended has let go of the stage before the next one asks for it
      if (j.state === 'running' && !j.waiting && S.wasWaiting[j.id]) onJobStarted(j);
      S.wasWaiting[j.id] = j.state === 'running' && j.waiting;
    }
    takeStageIfDue();
    const fj = focusJob();
    if (fj) tick(fj); else if (S.focus && !S.jobs.find(j => j.id === S.focus && j.state === 'running')) S.focus = null;
    if (!activeJobs().length) S.away = false;
    if (!S.focus && !S.item && !S.away && activeJobs().length) adoptFocus();
    paintQueue(); paintFilm(); render();
    if (S.page === 'timeline' && typeof tlPaintFilm === 'function') tlPaintFilm();
  }
}
/* Only work this page started may take the stage on its own. Work from another visit or another tool stays in the strip,
   so a second person who opens the page lands on the starting wall and not on someone else's recipe board. */
function adoptFocus() { const a = activeJobs().filter(j => S.mine.has(j.id)).sort((x, y) => Number(x.waiting) - Number(y.waiting))[0]; if (a) { S.focus = a.id; prepareFrame(a); tick(a); } }
/* A picture that was waiting in line has reached the front. If its maker asked to watch it arrive it takes
   the stage, unless the person has opened something themselves, in which case they are told how to get there. */
function onJobStarted(job) {
  if (!job.live || S.focus || S.away || !S.mine.has(job.id)) return;
  if (S.item && S.pinned) { toast('Your next picture has started. Press Making in the strip to watch it arrive.'); return; }
  S.watchNext = {id: job.id, at: S.item ? Date.now() + 5000 : 0};  // a result that has just arrived is left up long enough to see
}
function takeStageIfDue() {
  const w = S.watchNext;
  if (!w || Date.now() < w.at) return;
  S.watchNext = null;
  const job = S.jobs.find(j => j.id === w.id && j.state === 'running');
  if (!job || S.focus || (S.item && S.pinned)) return;
  S.focus = job.id; S.item = null; S.boardKey = ''; setAmbient(null); prepareFrame(job); tick(job);
}
function itemFromJob(job) {
  if (job.item) { const item = {...job.item}; if (job.text) item.text = job.text; if (job.task) item.task = job.task; return item; }
  if (job.text) return {kind: 'text', lane: 'text', name: null, url: null, prompt: job.title || '', target: job.target || 'image', task: job.task, settings: {}, text: job.text};
  return null;
}
function onJobFinished(job) {
  const mine = job.id === S.focus;
  // a finished run changes what the next one of its kind is promised: the figures are asked for again
  if (job.state === 'done') { S.estKey = ''; setTimeout(askEstimate, 11000); }  // after the screen's ten second copy of the engine's figure
  setTimeout(refreshStatus, 2500);  // the memory the work gave back, read again once the model has let go, on every page alike
  const item = job.state === 'done' ? itemFromJob(job) : null;
  if (job.lane === 'film' && typeof T !== 'undefined' && T.filmJob === job.id) {  // the Timeline page shows its own film
    if (item) { T.filmDone = item; if (job.item) S.film = [job.item, ...S.film.filter(x => x.name !== job.item.name)]; refreshProjects(); }
    else if (job.state === 'failed') notice(job.message || 'The film could not be made.', 'warn');
    if (mine) S.focus = null;
    tlPaintFilm(); render(); refreshStatus();
    if (S.page === 'timeline') return;
  }
  if (item) {
    const own = S.mine.has(job.id);
    if (job.item && own) S.film = [job.item, ...S.film.filter(x => x.name !== job.item.name)];  // another person's piece reaches the strip only if it is in this project, when the strip is read again
    if (mine) {
      S.focus = null; S.previewKey = previewKey(); showItem(item); S.pinned = false;
      toast(!own ? 'Finished.' : job.item ? 'Saved to your project.' : 'Done.');  // a piece someone else started, watched from the strip, is theirs
    } else if (S.mine.has(job.id) && !S.item && !focusJob() && (!S.away || job.lane === S.lane)) { showItem(item); S.pinned = false; toast('Saved to your project.'); }  // an empty stage shows what this person's own work made; another person's never takes it
    else if (S.mine.has(job.id)) toast('Finished: ' + shortWords(job.title || 'one more', 44));  // someone else's work finishing is theirs to hear about
    if (job.note && own) notice(job.note, 'warn');
    refreshProjects();
  } else if (job.state === 'failed') { if (S.mine.has(job.id)) notice(job.message || 'Nothing was made.', 'warn'); if (mine) S.focus = null; render(); }
  else if (job.state === 'cancelled') { if (mine) { S.focus = null; } if (S.mine.has(job.id)) toast(job.message || 'Stopped. Nothing was kept.'); render(); }
  refreshStatus();
}
/* The line as one count, used by the header, the note under Generate and the popover alike: everything on the engine's
   queue from this page, other visits and other tools, split into what is being made now and what is waiting. */
function lineCounts() {
  const act = activeJobs(), rewrites = S.rewrites || [];
  const n = act.length + S.others.length + rewrites.length;
  // a job held at the memory check is not being made: it is waiting, for memory rather than for its turn
  const held = act.filter(j => j.held && !j.waiting).length + S.others.filter(o => o.state === 'running' && o.stage === 'Waiting for memory to free up').length;
  // A recipe that waits for memory waits by itself and leaves the engine free, so new work that fits starts before it.
  // A single job waiting for memory holds the engine's place: what is added after it starts after it.
  const heldAside = act.filter(j => j.held && !j.waiting && j.lane === 'recipe').length;
  // A job held for the nightly job waits aside too: work that loads no model goes ahead of it.
  const night = act.filter(j => j.night).length + S.others.filter(o => o.night).length;
  const running = act.filter(j => !j.waiting && !j.held).length + S.others.filter(o => o.state === 'running' && o.stage !== 'Waiting for memory to free up').length + rewrites.filter(j => !j.waiting).length;
  return {n, running, waiting: n - running, held, heldAside, night};
}
/* What a press now would do, counting everything already in the line, in the order the engine will really take it. */
function lineWords(line) {
  const aside = line.heldAside + line.night;
  const ahead = line.n - aside;  // the work a new press really starts after
  const holding = line.held - line.heldAside;  // a job waiting for memory in the engine's own place
  let text = '';
  if (ahead > 0) {
    const first = line.running ? 'One thing is being made' : holding ? 'One thing is waiting for memory to free up' : '';
    const queued = ahead - (first ? 1 : 0);
    text = first && !queued ? `${first} now. Anything you add starts when it finishes.`
      : first ? `${first} and ${queued === 1 ? 'one is' : queued + ' are'} waiting. Anything you add now starts after ${ahead === 2 ? 'both' : 'all ' + ahead}.`
      : `${queued === 1 ? 'One thing is' : queued + ' things are'} waiting to start. Anything you add now starts after ${queued === 1 ? 'it' : 'them'}.`;
  }
  if (line.heldAside) text += (text ? ' ' : '') + `${line.heldAside === 1 ? 'A recipe is' : line.heldAside + ' recipes are'} waiting for memory by ${line.heldAside === 1 ? 'itself' : 'themselves'}. Work that fits can start before ${line.heldAside === 1 ? 'it' : 'them'}.`;
  if (line.night) text += (text ? ' ' : '') + `${line.night === 1 ? 'One thing waits' : line.night + ' things wait'} for the nightly job. An animation can start before ${line.night === 1 ? 'it' : 'them'}.`;
  return text;
}
function paintQueue() {
  const {n, running, waiting, held} = lineCounts();
  $('queueBtn').classList.toggle('busy', n > 0);
  const phone = innerWidth <= 720;
  // the same word for the same count on both widths; a phone keeps the shorter form so the project's name keeps its room
  const words = !n ? 'Nothing waiting' : running ? (phone ? (waiting ? `${waiting} waiting` : 'Making') : `Making one${waiting ? `, ${waiting} waiting` : ''}`)
    : held && held === waiting ? 'Needs memory' : `${waiting} waiting`;
  $('queueText').textContent = words;
  $('queueBtn').title = !n ? 'Nothing is being made or waiting' : `${words}. Press to see the line.`;
  if (!$('queuePop').hidden) renderQueuePop();
}
function renderQueuePop() {
  const pop = $('queuePop'); pop.replaceChildren();
  const act = [...activeJobs(), ...(S.rewrites || []).map(j => ({...j, lane: 'enhance', title: 'Improving your words'}))];
  if (!act.length && !S.others.length) pop.append(el('div', 'pop-empty', 'Nothing is running or waiting. New work starts as soon as you ask for it.'));
  if (act.length) pop.append(el('h4', '', 'Now and next'));
  const place = j => j.position || 1000;  // the running one first, then the line in the order it will really run
  for (const j of act.sort((a, b) => Number(a.waiting) - Number(b.waiting) || place(a) - place(b) || a.id.localeCompare(b.id))) {
    const row = el('div', 'pop-row');
    const truth = Craft.read(j);
    const c = Craft.make(j.lane, 'mini'); c.update(truth);  // the small version of this craft's drawing, from the same numbers
    const t = el('div', 't');
    t.append(el('b', '', j.title || laneName(j.lane)));
    t.append(el('span', '', j.lane === 'recipe' ? Craft.recipeWords(truth) : Craft.words(truth)));  // a recipe's figures are the whole run's, and say so
    row.append(c.el, t);
    // Only work this page started gets a Stop here: another person's job from another page is theirs to stop, from their page.
    if (j.can_stop && S.mine.has(j.id)) { const s = el('button', 'ghost', 'Stop'); s.onclick = () => stopJob(j.id); row.append(s); }
    else if (j.can_stop) row.append(el('span', 'pop-aside', j.by_someone_else ? 'Someone else started this' : 'Started from another page'));
    pop.append(row);
  }
  if (S.others.length) {
    pop.append(el('h4', '', 'From other tools'));
    for (const o of S.others) { const row = el('div', 'pop-row'); const t = el('div', 't'); t.append(el('b', '', laneName(o.lane)), el('span', '', (o.client === 'people-screen' ? 'From an earlier visit' : 'Another tool') + ', ' + (o.state === 'running' ? (o.stage === 'Waiting for memory to free up' ? 'waiting for memory' : 'working') : o.night ? 'waiting for the nightly job' : 'waiting'))); row.append(t); pop.append(row); }
  }
  const done = S.jobs.filter(j => j.state !== 'running' && S.mine.has(j.id)).slice(0, 6);  // this person's own: another person's finished work is theirs to open
  if (done.length) {
    pop.append(el('h4', '', 'Just finished'));
    for (const j of done) {
      const row = el('button', 'pop-row'); const t = el('div', 't');
      t.append(el('b', '', j.title || laneName(j.lane)), el('span', '', `${laneName(j.lane)}. ${j.state === 'done' ? 'Finished in ' + clock(j.elapsed) : j.state === 'cancelled' ? 'Stopped' : 'Did not finish'}`));
      row.append(t);
      const finished = j.state === 'done' ? itemFromJob(j) : null;
      if (finished) row.onclick = () => { closePopovers(); go('studio'); openItem(finished); };
      pop.append(row);
    }
  }
}
function laneName(l) { return ({image: 'A picture', voice: 'A voice recording', speech: 'A voice recording', music: 'Music', edit: 'A picture edit', video: 'A clip', animation: 'An animation', text: 'Writing', recipe: 'A recipe', remake: 'Making it again', film: 'Joining a film', enhance: 'Improving your words'})[l] || 'Work'; }
async function stopJob(id) {
  const r = await api('/api/job/' + encodeURIComponent(id) + '/stop', {});
  if (!r.ok) notice(r.data.error || 'That could not be stopped.', 'warn');
  else toast('Stopping.');
}
$('queueBtn').onclick = () => { const p = $('queuePop'); if (!p.hidden) { closePopovers(); return; } closePopovers(); placePopover(p, $('queueBtn'), true); renderQueuePop(); };
$('stopBtn').onclick = () => { if (S.focus) stopJob(S.focus); };
$('boardStop').onclick = () => { if (S.focus) stopJob(S.focus); };

/* making */
function prepareFrame(job) {
  S.lastPeek = null;
  const sizes = S.catalog ? S.catalog.sizes : null;
  let ratio = null;
  const lane = job.lane;
  if (lane === 'image' && sizes) ratio = job.source_ratio || (sizes[job.size || S.size] || '1024x1024').replace('x', '/');
  if (lane === 'video') ratio = ({landscape: '960/576', portrait: '576/960', square: '1/1'})[job.size || S.videoShape];
  if (lane === 'animation') ratio = ({landscape: '16/9', portrait: '9/16', square: '1/1'})[S.shape];
  if (lane === 'edit' || lane === 'remake') ratio = '4/3';
  const f = $('frame');
  f.hidden = !ratio; if (ratio) { const [w, h] = ratio.split('/').map(Number); f.dataset.ar = w / (h || 1); fitFrame(); }
  f.classList.remove('has-frames', 'source');
  $('peekA').classList.remove('show'); $('peekB').classList.remove('show');
  $('peekA').removeAttribute('src'); $('peekB').removeAttribute('src');
  // the lane tabs and the composer follow what is on the stage, so a recipe's board is not under the Voice lane's words
  const laneId = lane === 'recipe' ? 'recipe' : lane;
  if (lane === 'recipe' && job.recipe && S.catalog && S.catalog.recipes.some(x => x.id === job.recipe)) S.recipe = job.recipe;
  if (laneId !== S.lane && LANES.some(l => l.id === laneId)) setLane(laneId);
  $('workPrompt').textContent = job.title || '';  // before the frame is sized, so its lines are counted
  $('workLabel').textContent = ({recipe: 'Working through the steps', remake: 'Making it again', image: 'Making your picture', voice: 'Reading it aloud', music: 'Writing your music', edit: 'Working on your picture', video: 'Making your clip', animation: 'Drawing your animation', text: 'Writing', film: 'Joining your film'})[lane] || 'Working';
  mountCraft(job);
  if (ratio) grainStart();
  if (lane === 'animation' && S.previewUrl && S.mine.has(job.id)) {
    // the still the lane drew while the words were typed is what the animation will look like, so it stands on the bench
    $('peekA').src = S.previewUrl; $('peekA').classList.add('show'); f.classList.add('source');
  }
  if ((lane === 'edit' || lane === 'video') && S.source && S.source.thumb) {
    // the picture being worked on, dimmed, is what is really on the bench
    const dim = /(\d+) by (\d+)/.exec(S.source.dimensions || '');
    if (dim) { f.dataset.ar = Number(dim[1]) / Number(dim[2]); fitFrame(); }
    $('peekA').src = S.source.thumb; $('peekA').classList.add('show'); f.classList.add('source');
  }
  // A picture or an animation with nothing yet to show: the words it is being made from, set in the frame, so the largest
  // thing on the stage is not an empty sheet. They are the person's own words, not a drawing that pretends to be the
  // result, and they give way to the first real frame (Watch it arrive) or to the still the lane drew.
  const fw = $('frameWords');
  const wordsInFrame = (lane === 'image' || lane === 'animation') && !f.classList.contains('source') && !!(job.title || '').trim();
  fw.hidden = !wordsInFrame;
  fw.querySelector('span').textContent = wordsInFrame ? job.title : '';
  fw.classList.toggle('lines', lane === 'animation');
  $('workPrompt').classList.toggle('in-frame', wordsInFrame);
  fitFrame();
}
/* The progress drawing for this job: the film leader sits in the frame where the clip will appear; the strip, the
   record and the recording sit under the label. One drawing per job, updated in place on every report. */
function mountCraft(job) {
  if (S.craft && S.craft.jobId === job.id && S.craft.el.isConnected) return;
  $('craft').replaceChildren(); $('craftIn').replaceChildren();
  const c = Craft.make(job.lane, 'large'); c.jobId = job.id;
  (c.kind === 'leader' && !$('frame').hidden ? $('craftIn') : $('craft')).append(c.el);
  S.craft = c;
  fitFrame();
}
/* The frame takes what is left of the stage after the label, the words, the progress drawing and the Stop row. */
function fitFrame() {
  const f = $('frame'), host = $('stage'); const ar = Number(f.dataset.ar);
  if (!ar || f.hidden) return;
  const used = [...$('working').children].filter(n => n !== f && !n.hidden && n.childNodes.length).reduce((a, n) => a + n.getBoundingClientRect().height + 13, 0) + 36;
  const least = innerWidth <= 720 ? 110 : 160;  // a phone keeps the words and the drawing in view before it keeps a large frame
  const w = Math.min(host.clientWidth - 52, Math.max(least, host.clientHeight - Math.max(130, used)) * ar);
  f.style.width = Math.floor(w) + 'px'; f.style.height = Math.floor(w / ar) + 'px';
}
new ResizeObserver(fitFrame).observe($('stage'));
for (const id of ['workPrompt', 'craft', 'workTime', 'heldOffer']) new ResizeObserver(fitFrame).observe($(id));  // heldOffer: the frame makes room for the offer, so its buttons are never under the composer  // the words and the drawing settle after the first paint
function begin(job, takeStage) {
  closeHow();
  const taken = focusJob();
  S.jobs = [job, ...S.jobs.filter(j => j.id !== job.id)];
  S.lastStates[job.id] = 'running';
  S.mine.add(job.id);
  if (!taken || takeStage) { S.away = false; S.focus = job.id; S.item = null; S.boardKey = ''; prepareFrame(job); tick(job); }
  render();
  clearTimeout(queueTimer); queueTimer = setTimeout(pollQueue, 400);
}
function tick(job) {
  const t = Craft.read(job);
  mountCraft(job);
  S.craft.update(t);
  const words = Craft.words(t);
  if ($('workTime').textContent !== words) $('workTime').textContent = words;
  if (job.title && $('workPrompt').textContent !== job.title) { $('workPrompt').textContent = job.title; fitFrame(); }  // the first report from the line carries the words
  // Stop only for work this page started: another person's job, opened from the strip, is theirs to stop from their page.
  const own = S.mine.has(job.id);
  $('stopBtn').hidden = !job.can_stop || !own;
  $('workAside').hidden = own;
  $('workAside').textContent = job.by_someone_else ? 'Someone else started this' : 'Started from another page';
  paintHeldOffer(job, own);
  if (job.peek !== null && job.peek !== undefined && job.peek !== S.lastPeek) {
    S.lastPeek = job.peek;
    const showB = $('peekA').classList.contains('show');
    const incoming = showB ? $('peekB') : $('peekA'), outgoing = showB ? $('peekA') : $('peekB');
    incoming.onload = () => { incoming.classList.add('show'); outgoing.classList.remove('show'); $('frame').classList.add('has-frames'); grainStop(); };
    incoming.src = '/peek/' + encodeURIComponent(job.id) + '?s=' + job.peek;
    Grain.step = Math.min(1, (job.step || 0) / (job.total || 1));
  }
  if (job.lane === 'recipe') paintBoard();
  const live = $('livePage');
  live.hidden = job.lane !== 'text';
  if (job.lane === 'text') {
    if (job.partial && job.partial !== live.textContent) { live.textContent = job.partial; live.scrollTop = live.scrollHeight; }
    if (!job.partial) live.textContent = '';
  }
}
/* A picture of this person's that has waited for memory a while: why it waits, in figures, and the picture models that fit
   right now, each one press away (that press stops the waiting one and makes the same words with the model that fits). */
const HELD_PATIENCE = 15;  // seconds; memory often frees itself in the first few
function paintHeldOffer(job, own) {
  const box = $('heldOffer');
  const c = S.catalog;
  const show = own && job.held && job.lane === 'image' && (job.held_for || 0) >= HELD_PATIENCE && c && job.words;
  if (!show) { if (!box.hidden) { box.hidden = true; box.replaceChildren(); box.dataset.key = ''; fitFrame(); } return; }
  const spec = (c.image_models || []).find(m => m.id === job.model);
  // The reason is given in the engine's own figures, from the check that keeps refusing it, so it cannot contradict the
  // wait (the screen's reading, taken a moment apart, can be a little higher than the check's).
  const mem = job.mem || {};
  const asked = mem.need_gb || (spec ? spec.gb + (job.live && spec.live ? 4 : 0) : null);
  // only what asks for less memory than the waiting picture: another model of the same size would wait just the same
  const checkFree = mem.free_gb !== null && mem.free_gb !== undefined ? Number(mem.free_gb) - (mem.safety_gb || 4) : null;
  const fit = (c.image_models || []).map(realAsk).filter(m => m && m.runnable && m.id !== job.model && (!asked || m.gb < asked) && (checkFree === null || m.gb <= checkFree));
  const alts = spec ? nearestInTime(spec.id, fit).slice(0, 2) : [];
  const key = job.id + '|' + alts.map(a => a.id).join() + '|' + (mem.free_gb || 0);
  if (box.dataset.key === key && !box.hidden) return;
  box.dataset.key = key; box.replaceChildren(); box.hidden = false;
  const reserve = Math.round(mem.safety_gb || (S.judged || {}).safety_gb || 4);
  const why = spec && asked && mem.free_gb !== null && mem.free_gb !== undefined
    ? `${spec.label} needs about ${Math.round(asked + reserve)} GB with the reserve, and the memory check finds ${Number(mem.free_gb).toFixed(1)} GB free, so it waits.`
    : 'This picture waits for memory to free up.';
  box.append(el('p', '', alts.length ? `${why} ${alts.length === 1 ? 'This one fits' : 'These fit'} now:` : `${why} No other picture model fits right now either.`));
  for (const a of alts) {
    const secs = (S.est && S.est.lane === 'image' && S.est.options && S.est.options[a.id]) || a.seconds;
    const b = el('button', 'why-act', `Make it with ${a.label} instead, ${a.gb} GB${secs ? `, about ${aboutTime(secs)}` : ''}`);
    b.title = 'Stops the waiting picture and makes the same words with this model.';
    b.onclick = async () => {
      b.disabled = true;
      const stopped = await api('/api/job/' + encodeURIComponent(job.id) + '/stop', {});
      if (!stopped.ok) { b.disabled = false; notice(stopped.data.error || 'The waiting picture could not be stopped.', 'warn'); return; }
      S.model = a.id; S.modelChosen = true; S.wanted = null; S.steps = null;
      if (S.lane !== 'image') setLane('image');
      $('prompt').value = job.words; fitPrompt();
      renderPanel(); updateComposer();
      generate();
    };
    box.append(b);
  }
}
function collectBody(opts) {
  const m = selected();
  const prompt = $('prompt').value.trim();
  const body = {lane: S.lane, prompt, parent: (opts && opts.parent) || S.parent};
  if (S.lane === 'image') Object.assign(body, {model: S.model, size: S.size, style: S.style, steps: S.steps, seed: S.seed, count: S.count, live: S.live && !(m && m.liveOff), source: S.source ? S.source.name : null, strength: S.strength});
  if (S.lane === 'voice') Object.assign(body, {voice: S.voice, speed: S.speed, description: S.description});
  if (S.lane === 'music') Object.assign(body, {duration: S.duration, lyrics: S.lyrics, seed: S.musicSeed});
  if (S.lane === 'edit') Object.assign(body, {tool: S.tool, source: S.source.name, scale: S.scale});
  if (S.lane === 'animation') Object.assign(body, animationBody());
  if (S.lane === 'text') Object.assign(body, {task: S.textTask, model: S.writer, length: S.length, tone: S.tone, target: S.target, about: S.textTask === 'caption' && S.source ? (S.source.prompt || '') : ''});
  if (S.lane === 'video') Object.assign(body, {seconds: S.videoSeconds, shape: S.videoShape, seed: S.seed, model: S.videoModel, source: S.source ? S.source.name : null});
  return body;
}
/* The press is over when the server has answered, and for the length of a double click after it: the server can
   answer in a few milliseconds, so the second click of a double click can arrive after the first has finished. */
function sendFinished(r) {
  if (!r.ok) { S.sending = false; updateComposer(); return; }
  setTimeout(() => { S.sending = false; updateComposer(); }, 600);
}
/* A refusal for memory comes with what would run, one press away. */
function refused(r, opts) {
  const offers = (r.data.try || []).map(t => ({label: t.kind === 'live_off' ? 'Turn off watching it arrive and make it' : `Make it with ${t.label}, about ${t.gb} GB`, go: () => {
    notice('');
    if (t.kind === 'live_off') S.live = false; else { S[t.field] = t.id; if (t.field === 'model') { S.modelChosen = true; S.wanted = null; S.steps = null; } }
    renderPanel(); updateComposer(); generate(opts);
  }}));
  notice(r.data.error || 'That could not be started.', r.status === 409 ? 'warn' : '', offers);
}
async function generate(opts) {
  opts = opts || {};
  if ((S.hold.active && !heldOut()) || S.sending) return;  // a second press while the first is still being sent is the same press
  if (S.lane === 'recipe') { startRecipe(); return; }
  const m = selected();
  if (!m) return;
  if (!m.runnable) {  // never silent: the reason, with what would run instead
    const lead = S.lane === 'image' && (S.source || opts.source) ? 'Starting from a picture asks for more memory than words alone. ' : '';
    notice(lead + (m.reason || m.badge_text || 'That cannot be made right now.'), m.badge === 'red' ? 'warn' : '', fitsInstead(m).map(f => ({label: f.label, go: () => { notice(''); f.go(); generate(opts); }})));
    return false;
  }
  const prompt = $('prompt').value.trim();
  const wordsOptional = (S.lane === 'edit' && !m.words) || (S.lane === 'animation' && S.template === 'move');
  // the picture first: the big button opens the chooser when no picture is chosen yet, whatever the words say
  if (S.lane === 'animation' && S.template === 'move' && !S.source) { pickFromGallery('Choose a picture to move across'); return; }
  if (S.lane === 'edit' && !S.source) { pickFromGallery('Choose a picture to edit'); return; }
  if (!prompt && !wordsOptional) { notice(S.lane === 'animation' ? 'Please type the words for this animation.' : 'Please describe what you want first.'); $('prompt').focus(); return; }
  const body = collectBody(opts);
  if (opts.count) body.count = opts.count;
  if (opts.source) { body.source = opts.source; body.strength = opts.strength; }
  if (opts.seed === null) body.seed = null;
  notice('');
  S.sending = true; updateComposer();
  // An animation pressed before its still was drawn gets the still first (a second or two, no model), so the frame shows
  // what is being drawn for the whole run instead of an empty sheet. Nothing waits for it longer than six seconds.
  if (S.lane === 'animation' && !activeJobs().length && (!S.previewUrl || S.previewKey !== previewKey())) {
    clearTimeout(S.previewTimer); S.previewKey = previewKey();
    await Promise.race([fetchPreview().catch(() => {}), new Promise(done => setTimeout(done, 6000))]);
  }
  const r = await api('/api/create', body);
  sendFinished(r);
  if (!r.ok) { refused(r, opts); return false; }
  S.parent = null;
  if (r.data.same_press) { toast('That was already on its way, so it was not added twice.'); begin(r.data); return true; }
  if (r.data.others && r.data.others.length) toast(`${r.data.others.length + 1} added to the line.`);
  begin(r.data);
  return true;
}

/* showing a finished thing */
function action(label, title, onclick, cls) { const b = el('button', 'ghost ' + (cls || ''), label); if (title) b.title = title; b.onclick = onclick; return b; }
function openItem(item) {
  S.pinned = true;  // the person chose this, so a picture that starts later does not take it away
  if (item.lane === 'voice' || item.lane === 'music' || item.kind === 'video' || item.kind === 'text' || item.kind === 'audio') setLane(item.kind === 'video' ? (item.lane === 'animation' ? 'animation' : 'video') : item.kind === 'text' ? 'text' : item.lane === 'upload' ? 'image' : item.lane);
  else if (S.lane !== 'edit') setLane('image');
  showItem(item);
}
function showItem(item) {
  S.focus = null;  // whatever was on the stage gives way to the thing that was asked for; work carries on in the strip
  S.item = item;
  const canvas = $('canvas');
  canvas.replaceChildren();
  grainStop();
  if (item.kind === 'image') {
    const pic = lifted(item.url, item.name ? '/lift/' + encodeURIComponent(item.name) : null, item.prompt || 'Finished picture');
    if (/^neovak_cutout_/.test(item.name || '')) pic.classList.add('checker');  // a cut-out sits on a checkerboard, so the missing background can be seen to be missing
    // a changed or enlarged picture is shown against the one it came from, with the same slider the Edit wall teaches
    canvas.append(item.lane === 'edit' && item.parent && !/^neovak_cutout_/.test(item.name || '') ? beforeAfter(item) : pic);
    setAmbient(item.thumb || item.url);
  } else if (item.kind === 'video') {
    canvas.append(videoPlayer(item.url, item.thumb)); setAmbient(item.thumb);
  } else if (item.kind === 'text') {
    canvas.append(pageFor(item)); setAmbient(null);
    if (item.text === undefined && item.url) fetch(item.url).then(r => r.text()).then(t => { item.text = t.trimEnd(); if (S.item === item) { canvas.replaceChildren(pageFor(item)); paintWords(item); } }).catch(() => {});
  } else {
    setAmbient(null);
    canvas.append(audioCard(item));
  }
  // an edit is named like every other edit, its tool and then its words; everything else by its own words
  $('resultPrompt').textContent = (item.lane === 'edit' && item.caption) || item.prompt || 'No description was saved with this file.';
  $('resultPrompt').hidden = !!item.prompt && item.prompt.trim() === $('prompt').value.trim();  // the same words sit in the box just below
  const meta = $('resultMeta'); meta.replaceChildren();
  if (item.model && item.model !== item.prompt && item.model !== item.caption && !(item.caption || '').startsWith(item.model + ':')) meta.append(el('span', '', item.model));
  if (item.dimensions) meta.append(el('span', '', item.dimensions));
  if (item.seconds) meta.append(el('span', '', `${Math.round(item.seconds)} seconds long`));
  if (item.time) meta.append(el('span', '', when(item.time)));
  if (item.elapsed) meta.append(el('span', '', 'took ' + clock(item.elapsed)));
  if (item.remade) meta.append(el('span', '', 'made again from saved settings'));
  else if (item.parent) meta.append(el('span', '', fromWords(item)));
  paintActions(item); paintChainStrip(item); paintDots(item);
  if (item.kind === 'text') paintWords(item);
  render(); paintFilm();
}
/* Before and after, one picture over the other, cut where the pointer is (or where the arrow keys move the cut). The
   before is the picture the edit started from, stretched to the same frame, which an enlargement shares exactly. */
function beforeAfter(item) {
  const box = el('div', 'before-after'); box.style.setProperty('--cut', '50%');
  const after = el('img', 'ba-after'); after.src = item.url; after.alt = item.caption || item.prompt || 'The changed picture';
  const before = el('img', 'ba-before'); before.src = '/media/' + encodeURIComponent(item.parent); before.alt = 'The picture it started from';
  const bar = el('div', 'ba-bar'); bar.append(el('i'));
  box.append(after, before, bar, el('span', 'ba-tag left', 'Before'), el('span', 'ba-tag right', 'After'));
  box.tabIndex = 0; box.setAttribute('role', 'slider'); box.setAttribute('aria-label', 'Before and after. Move to compare.');
  box.setAttribute('aria-valuemin', '0'); box.setAttribute('aria-valuemax', '100'); box.setAttribute('aria-valuenow', '50');
  const set = p => { p = Math.max(0, Math.min(100, p)); box.style.setProperty('--cut', p.toFixed(1) + '%'); box.setAttribute('aria-valuenow', String(Math.round(p))); };
  const at = x => { const r = box.getBoundingClientRect(); set((x - r.left) / r.width * 100); };
  box.addEventListener('pointermove', e => { if (e.pointerType === 'mouse' || e.buttons) at(e.clientX); });
  box.addEventListener('pointerdown', e => { box.setPointerCapture(e.pointerId); at(e.clientX); });
  box.onkeydown = e => { if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') { e.preventDefault(); e.stopPropagation(); set(Number(box.getAttribute('aria-valuenow')) + (e.key === 'ArrowRight' ? 5 : -5)); } };
  after.addEventListener('load', () => { box.dataset.ar = after.naturalWidth / (after.naturalHeight || 1); fitBeforeAfter(box); }, {once: true});
  return box;
}
function fitBeforeAfter(box) {
  const host = box.parentElement, ar = Number(box.dataset.ar);
  if (!host || !ar) return;
  const w = Math.min(host.clientWidth, host.clientHeight * ar);
  box.style.width = Math.floor(w) + 'px'; box.style.height = Math.floor(w / ar) + 'px';
}
new ResizeObserver(() => { for (const b of document.querySelectorAll('.before-after')) fitBeforeAfter(b); }).observe($('canvas'));
/* What a file's parent means, in the words of what happened: a picture redrawn from a picture is a variation; an
   animation or a clip over a picture is not. A picture that only borrowed another's words and settings says so. */
function fromWords(item) {
  const fromFile = ((item.how && item.how.sources) || []).some(s => s.param === 'source' && s.file);
  if (item.lane === 'edit' || item.lane === 'video') return 'made from a picture';
  if (item.lane === 'animation') return 'over a picture';
  if (item.kind === 'image') return fromFile ? 'variation' : 'started from the words of an earlier picture';
  return 'started from an earlier piece';
}
/* The row under a result: a few clear actions, and the rest behind More. Every action is a real button with a name. */
const AI = {
  star: '<path d="M12 3.6l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.9l6-.8z"/>',
  down: '<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M5 19h14"/>',
  more: '<circle cx="6" cy="12" r="1.6"/><circle cx="12" cy="12" r="1.6"/><circle cx="18" cy="12" r="1.6"/>',
  vary: '<rect x="4" y="4" width="9" height="9" rx="2"/><rect x="11" y="11" width="9" height="9" rx="2"/>',
  edit: '<path d="M4 20l9.5-9.5M14.5 3.5l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/>',
  clip: '<rect x="3.5" y="5.5" width="17" height="13" rx="2.5"/><path d="M10 9.2l5 2.8-5 2.8z"/>',
  timeline: '<rect x="3.5" y="6" width="9" height="5" rx="1"/><rect x="13.5" y="6" width="7" height="5" rx="1"/><rect x="3.5" y="14" width="13" height="4.5" rx="1"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 00-2-2H6a2 2 0 00-2 2v8a2 2 0 002 2h2"/>',
  voice: '<rect x="9" y="3.5" width="6" height="11" rx="3"/><path d="M5.5 11.5a6.5 6.5 0 0013 0M12 18v2.5"/>',
};
function aicon(n) { return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${AI[n] || ''}</svg>`; }
/* One action under a result. phoneLabel is the one word it keeps on a phone, where six buttons share the width and a
   longer label would wrap onto a second line and make its button taller than the others. */
function act(label, ic, title, go, cls, phoneLabel) {
  const b = el('button', 'act' + (cls ? ' ' + cls : '')); b.innerHTML = ic ? aicon(ic) : '';
  if (phoneLabel) { b.append(el('span', 'lab-long', label), el('span', 'lab-short', phoneLabel)); b.setAttribute('aria-label', label); }
  else b.append(el('span', '', label));
  if (title) b.title = title; b.onclick = go; return b;
}
let moreItems = [];  // the menu's actions for the item on the stage, so a keyboard shortcut can find one by name
function paintActions(item) {
  const bar = $('actions'); bar.replaceChildren();
  const isImage = item.kind === 'image', isText = item.kind === 'text', isVideo = item.kind === 'video';
  const more = [];
  if (item.name) {
    const fav = act('', 'star', 'Mark this as a favorite', async () => { if (await setFavorite(item, !item.favorite)) paintFav(fav, item); }, 'icon'); fav.id = 'favBtn'; paintFav(fav, item); bar.append(fav);
  }
  if (isImage && item.lane !== 'edit') { const v = act('Variations', 'vary', 'Make new versions of this. The original is kept.', () => openVariations(v, item)); v.id = 'varBtn'; bar.append(v); }
  if (isImage) {
    bar.append(act('Edit', 'edit', 'Change, enlarge or repair this picture. The original is kept.', () => { S.source = item; setLane('edit'); S.item = null; setAmbient(item.thumb); render(); renderPanel(); }));
    bar.append(act('Make a clip', 'clip', 'Start a short video from this picture. The picture is kept.', () => { S.source = item; S.item = null; setLane('video'); render(); }, '', 'Clip'));
  }
  if (isText) {
    bar.append(act('Copy', 'copy', 'Copy the words', async () => toast(await copyText(item.text || '') ? 'Copied.' : 'Could not copy from this browser.')));
    bar.append(act('Read it aloud', 'voice', 'Send these words to the Voice lane', () => startFromText('voice', item.text || ''), '', 'Read'));
  }
  if ((item.lane === 'voice' || item.lane === 'music' || isVideo) && item.name) bar.append(act('Add to timeline', 'timeline', 'Put this on the project timeline', () => addToTimeline(item), '', 'Timeline'));
  if (item.url) { const d = el('a', 'act', ''); d.innerHTML = aicon('down'); d.append(el('span', '', 'Download')); d.href = item.url; d.setAttribute('download', item.name || ''); d.title = 'Save a copy to this device'; bar.append(d); }
  // the rest, behind More
  // a cut-out has no slider (its before is a whole picture, its after mostly empty), so it keeps the press and hold
  if (item.name && isImage && item.parent && item.lane === 'edit' && /^neovak_cutout_/.test(item.name)) more.push({label: 'Show the original', hold: true, title: 'Press and hold to see the picture this one came from'});
  if (item.lane !== 'edit' && item.lane !== 'film') more.push({label: 'Start from similar', go: async () => { await startFromSimilar(item); $('prompt').focus(); }});
  if (item.name && isImage) more.push({label: 'Add to timeline', go: () => addToTimeline(item)});
  if (item.name && (isImage || isVideo)) more.push({label: item.parent && item.lane !== 'edit' ? 'Compare with the picture it came from' : 'Compare with the one before', go: () => compareWithPrevious(item)});
  if (isImage && item.lane !== 'edit' && item.seed !== null && item.seed !== undefined) more.push({label: 'Make the next picture from the same starting number', go: () => { setSeed(item.seed, 'image'); renderPanel(); updateComposer(); toast('The next picture will start from the same number as this one.'); }});
  if (isText) {
    more.push({label: 'Make a title card from the first line', go: () => { const first = (item.text || '').split('\n').map(x => x.trim()).filter(Boolean)[0] || ''; const sentence = (first.match(/^.{1,70}?[.!?](?=\s|$)/) || [first])[0]; S.template = 'title'; startFromText('animation', sentence.length > 90 ? sentence.slice(0, 90).trim() : sentence); }});
    if (!item.name) more.push({label: 'Use these words', go: () => startFromText(item.target || 'image', item.text || '')});
  }
  if (item.how) more.push({label: 'How this was made', go: openHow});
  if (item.name) more.push({label: 'Hide from the gallery', go: async () => { const r = await api('/api/hide', {name: item.name, on: true}); if (!r.ok) { notice(r.data.error || 'That could not be hidden.', 'warn'); return; } S.film = S.film.filter(x => x.name !== item.name); S.item = null; setAmbient(null); render(); paintFilm(); toast('Hidden. The file is still on disk, and the gallery can show hidden pieces.'); }});
  moreItems = more;
  if (more.length) { const m = act('More', 'more', 'Everything else you can do with this', () => openMore(m, item)); m.id = 'moreBtn'; m.setAttribute('aria-haspopup', 'menu'); bar.append(m); }
}
function openMore(anchor, item) {
  const pop = $('morePop');
  if (!pop.hidden) { closePopovers(); return; }
  closePopovers(); pop.replaceChildren();
  for (const m of moreItems) {
    const b = el('button', 'pop-row menu-row', m.label); b.setAttribute('role', 'menuitem'); if (m.title) b.title = m.title;
    if (m.hold) {
      const show = on => { const fg = $('canvas').querySelector('.lifted'); if (!fg) return; for (const im of fg.querySelectorAll('.bg')) im.src = on ? '/media/' + encodeURIComponent(item.parent) : item.url; fg.classList.toggle('has-subject', !on); };
      b.addEventListener('pointerdown', () => show(true)); for (const ev of ['pointerup', 'pointerleave', 'pointercancel']) b.addEventListener(ev, () => show(false));
    } else b.onclick = () => { closePopovers(); m.go(); };
    pop.append(b);
  }
  placePopover(pop, anchor, true);
  pop.querySelector('button')?.focus();
}
function moreAction(label) { const m = moreItems.find(x => x.label.startsWith(label)); if (m && m.go) m.go(); }

/* The players, in the app's own style. The browser's own controls are never shown. */
function playerBtn(a) { const b = el('button', 'pp-play'); b.setAttribute('aria-label', 'Play'); b.onclick = () => (a.paused ? a.play().catch(() => {}) : a.pause()); return b; }
function playerTimes(a, wrap, btn) {
  const t = el('span', 'pp-time num', '0:00 / 0:00');
  const paint = () => { t.textContent = `${clock(a.currentTime)} / ${clock(a.duration || 0)}`; };
  a.addEventListener('loadedmetadata', paint); a.addEventListener('timeupdate', paint); a.addEventListener('durationchange', paint);
  a.addEventListener('play', () => { btn.classList.add('on'); btn.setAttribute('aria-label', 'Pause'); wrap.classList.add('playing'); });
  a.addEventListener('pause', () => { btn.classList.remove('on'); btn.setAttribute('aria-label', 'Play'); wrap.classList.remove('playing'); });
  a.addEventListener('ended', () => { btn.classList.remove('on'); wrap.classList.remove('playing'); });
  return t;
}
function soundBtn(a) {
  const b = el('button', 'pp-sound'); b.setAttribute('aria-label', 'Turn the sound off'); b.setAttribute('aria-pressed', 'false');
  b.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 9.5v5h3.5L13 19V5L7.5 9.5z"/><path class="w1" d="M16 9.5a4 4 0 010 5"/><path class="w2" d="M18.5 7a7.5 7.5 0 010 10"/><path class="x" d="M16.5 9.5l5 5M21.5 9.5l-5 5"/></svg>';
  const paint = () => { b.classList.toggle('off', a.muted); b.setAttribute('aria-label', a.muted ? 'Turn the sound on' : 'Turn the sound off'); b.setAttribute('aria-pressed', String(a.muted)); };
  b.onclick = () => { a.muted = !a.muted; paint(); };
  return b;
}
function scrubBar(a) {
  const bar = el('div', 'pp-bar'); bar.setAttribute('role', 'slider'); bar.setAttribute('aria-label', 'Position'); bar.tabIndex = 0;
  const fill = el('i'); bar.append(fill);
  const paint = () => { const p = a.duration ? a.currentTime / a.duration : 0; fill.style.width = (p * 100) + '%'; bar.setAttribute('aria-valuenow', String(Math.round(p * 100))); };
  a.addEventListener('timeupdate', paint);
  const seekTo = x => { const r = bar.getBoundingClientRect(); if (a.duration) a.currentTime = Math.max(0, Math.min(1, (x - r.left) / r.width)) * a.duration; paint(); };
  bar.addEventListener('pointerdown', e => { bar.setPointerCapture(e.pointerId); seekTo(e.clientX); bar.onpointermove = ev => seekTo(ev.clientX); bar.onpointerup = () => { bar.onpointermove = null; }; });
  bar.onkeydown = e => { if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') { e.preventDefault(); e.stopPropagation(); a.currentTime = e.key === 'ArrowRight' ? Math.min(a.duration || 0, a.currentTime + 5) : Math.max(0, a.currentTime - 5); paint(); } };
  return bar;
}
function audioCard(item) {
  const card = el('div', 'audio-card');
  const head = el('div', 'head');
  const length = item.seconds ? `${Math.round(item.seconds)} seconds` : '';
  const musicTitle = (item.prompt || '').trim() ? shortWords(item.prompt, 70) : 'A short piece';
  head.append(el('div', 'eyebrow', item.lane === 'music' ? (length ? `Music, ${length}` : 'Music') : 'Voice'), el('div', 'kind', item.lane === 'music' ? musicTitle : (item.model ? `Read by ${item.model}` : 'Read aloud')));
  card.append(head);
  const a = el('audio'); a.src = item.url; a.preload = 'metadata';
  const wave = el('div', 'big-wave'); wave.setAttribute('role', 'slider'); wave.setAttribute('aria-label', 'Position in the recording'); wave.tabIndex = 0;
  card.append(wave);
  const row = el('div', 'pp-row');
  const play = playerBtn(a); const times = playerTimes(a, card, play);
  row.append(play, times, el('span', 'grow'), soundBtn(a));
  card.append(row, a);
  if (item.name) api('/peaks/' + encodeURIComponent(item.name)).then(r => { if (r.ok) waveBars(wave, r.data.peaks, 'big'); });
  // The waveform is the scrub bar: a slider with its value said aloud, moved by the pointer or the arrow keys.
  wave.setAttribute('aria-valuemin', '0'); wave.setAttribute('aria-valuemax', '100'); wave.setAttribute('aria-valuenow', '0'); wave.setAttribute('aria-valuetext', '0:00');
  const paintWave = () => {
    const bars = wave.children; const p = a.currentTime / (a.duration || 1); const n = Math.floor(p * bars.length);
    for (let i = 0; i < bars.length; i++) bars[i].classList.toggle('past', i < n);
    wave.setAttribute('aria-valuenow', String(Math.round(p * 100))); wave.setAttribute('aria-valuetext', `${clock(a.currentTime)} of ${clock(a.duration || 0)}`);
  };
  a.ontimeupdate = paintWave; a.addEventListener('loadedmetadata', paintWave);
  const seek = x => { const r = wave.getBoundingClientRect(); if (a.duration) { a.currentTime = Math.max(0, Math.min(1, (x - r.left) / r.width)) * a.duration; paintWave(); } };
  wave.addEventListener('pointerdown', e => { wave.setPointerCapture(e.pointerId); seek(e.clientX); wave.onpointermove = ev => seek(ev.clientX); wave.onpointerup = () => { wave.onpointermove = null; }; });
  wave.onkeydown = e => {
    if (e.key === ' ') { e.preventDefault(); play.click(); }
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault(); e.stopPropagation();  // the keys scrub this recording; they do not also step to the next piece in the strip
      a.currentTime = e.key === 'ArrowRight' ? Math.min(a.duration || 0, a.currentTime + 5) : Math.max(0, a.currentTime - 5);
      paintWave();
    }
  };
  return card;
}
function videoPlayer(url, poster) {
  const box = el('div', 'player');
  const v = el('video'); v.loop = true; v.playsInline = true; v.preload = 'metadata'; v.src = url; if (poster) v.poster = poster;
  box.append(v);
  const big = el('button', 'pp-big'); big.setAttribute('aria-label', 'Play'); big.onclick = () => (v.paused ? v.play().catch(() => {}) : v.pause()); box.append(big);
  const bar = el('div', 'pp-controls');
  const play = playerBtn(v); const times = playerTimes(v, box, play);
  bar.append(play, scrubBar(v), times, soundBtn(v));
  box.append(bar);
  v.onclick = () => big.click();
  v.addEventListener('loadedmetadata', () => { box.style.setProperty('--ar', String(v.videoWidth / (v.videoHeight || 1))); fitPlayer(box); });
  let idle;
  const wake = () => { box.classList.add('awake'); clearTimeout(idle); idle = setTimeout(() => box.classList.remove('awake'), 2200); };
  box.addEventListener('pointermove', wake); box.addEventListener('pointerdown', wake); wake();
  return box;
}
/* the clip fills the stage like a picture does, whatever its shape */
function fitPlayer(box) {
  const host = box.parentElement, ar = Number(box.style.getPropertyValue('--ar'));
  if (!host || !ar) return;
  const w = Math.min(host.clientWidth, host.clientHeight * ar);
  box.style.width = Math.floor(w) + 'px'; box.style.height = Math.floor(w / ar) + 'px';
  box.classList.toggle('tiny', w / ar < 170);  // in a short box the big play button would cover the bar's controls, so only the bar is kept
}
new ResizeObserver(() => { for (const b of document.querySelectorAll('.player')) fitPlayer(b); }).observe($('canvas'));
function paintFav(btn, item) { btn.innerHTML = `<svg class="star${item.favorite ? ' on' : ''}" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.6l2.6 5.5 6 .8-4.4 4.2 1.1 6-5.3-2.9-5.3 2.9 1.1-6L3.4 9.9l6-.8z"/></svg>`; btn.setAttribute('aria-label', item.favorite ? 'Favorited. Press to take it off your favorites' : 'Mark as a favorite'); btn.title = btn.getAttribute('aria-label'); btn.classList.toggle('is-on', !!item.favorite); if (btn.id === 'favBtn') btn.append(el('span', 'ph', 'Favorite')); }
function paintDots(item) {
  const dots = $('dots');
  const set = item.batch ? S.film.filter(x => x.batch === item.batch) : [];
  dots.hidden = set.length < 2;
  dots.replaceChildren(...set.map(x => { const b = el('button', x.name === item.name ? 'on' : ''); b.setAttribute('aria-label', 'Show this version'); b.onclick = () => showItem(x); return b; }));
}
function pageFor(item) {
  const page = el('div', 'page-view');
  if (item.text === undefined) { page.textContent = 'Opening...'; return page; }
  if (item.task === 'caption' || /^neovak_text_/.test(item.name || '') && item.text && item.text.split('\n').length <= 4 && item.text.length < 260) {
    for (const ln of item.text.split('\n').filter(Boolean)) page.append(el('div', 'caption-line', ln));
  } else page.textContent = item.text;
  return page;
}
function paintWords(item) {
  const count = (item.text || '').trim().split(/\s+/).filter(Boolean).length;
  if (!count) return;
  const meta = $('resultMeta');
  meta.querySelector('.words-note')?.remove();
  const n = el('span', 'words-note', `${count} ${count === 1 ? 'word' : 'words'}, about ${clock(Math.round(count / 150 * 60))} read aloud`);
  meta.prepend(n);
}
function paintChainStrip(item) {
  const strip = $('chainStrip'); strip.replaceChildren();
  const how = item.how; const chain = how && how.chain ? how.chain : [];
  strip.hidden = !chain.length;
  if (!chain.length) return;
  // Every step knows the whole chain in the order it was made, so a step opened from here shows the same row, in the
  // same order, and can lead back to any other step.
  const all = how.all || [...chain, {label: how.step || 'This file', name: item.name, thumb: item.thumb}];
  strip.append(el('span', 'lbl', `Made in ${all.length} steps`));
  const add = (label, name, thumb, here) => {
    const b = el('button', 'step-thumb' + (here ? ' here' : ''));
    if (thumb) { const img = el('img'); img.src = thumb; img.alt = ''; b.append(img); }
    else if (/\.txt$/i.test(name || '')) b.append(el('span', 'ico text', 'Aa'));  // a page of writing
    else if (name) { const wf = el('span', 'ico wave'); b.append(wf); api('/peaks/' + encodeURIComponent(name)).then(r => { if (r.ok) waveBars(wf, r.data.peaks); }); }  // a recording
    else b.append(el('span', 'ico'));
    b.append(el('span', '', label));
    if (name && !here) b.onclick = async () => {
      const r = await api('/api/item/' + encodeURIComponent(name));
      if (!r.ok) { toast('That file is no longer in the output folder.'); return; }
      const d = r.data;
      d.how = {sources: [], settings: {}, ...(d.how || {}), chain: all.filter(x => x.name !== name), all, step: label, recipe: (d.how && d.how.recipe) || how.recipe};
      showItem(d);
    };
    strip.append(b);
  };
  all.forEach(c => add(c.label || c.name, c.name, c.thumb, c.name === item.name));
}
async function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) { try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* falls through */ } }
  const area = el('textarea'); area.value = text; area.style.position = 'fixed'; area.style.opacity = '0';
  document.body.append(area); area.select();
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  area.remove(); return ok;
}
/* The first words of a text, cut at a word, with three dots when there is more. */
function shortWords(text, limit) { const t = String(text || '').replace(/\s+/g, ' ').trim(); if (t.length <= limit) return t; const cut = t.slice(0, limit); return (cut.includes(' ') ? cut.slice(0, cut.lastIndexOf(' ')) : cut).replace(/[ ,;:]+$/, '') + '...'; }
function startFromText(lane, text) { S.item = null; S.source = null; setAmbient(null); setLane(lane); $('prompt').value = text; updateComposer(); render(); $('prompt').focus(); }
async function setFavorite(item, on) { const r = await api('/api/favorite', {name: item.name, on}); if (r.ok) item.favorite = on; return r.ok; }
/* Start from similar: loadSettings, and the picture the piece started from, when it had one. */
async function startFromSimilar(item) {
  loadSettings(item);
  S.parent = item.name;
  const from = ((item.how && item.how.sources) || []).find(x => x.param === 'source' && x.file);
  let word = 'Words and settings loaded. Change anything, then Generate.';
  if (from && ['image', 'video', 'animation'].includes(S.lane)) {
    const r = await api('/api/item/' + encodeURIComponent(from.file));
    if (r.ok) { S.source = r.data; if (S.lane === 'image' && item.how.settings.strength) S.strength = Number(item.how.settings.strength); word = 'Words, settings and the starting picture loaded. Change anything, then Generate.'; }
    else notice('The picture this one started from is no longer in the output folder, so only the words and settings came back.', 'warn');
    renderPanel(); updateComposer();
  }
  toast(word);
}
function loadSettings(item) {
  const s = item.settings || {}; const h = (item.how && item.how.settings) || {};
  let lane = item.lane === 'upload' ? 'image' : (item.lane || 'image');
  if (!LANES.find(l => l.id === lane)) lane = item.kind === 'video' ? 'video' : item.kind === 'audio' ? 'voice' : 'image';
  $('prompt').value = item.prompt || '';
  S.source = null;  // a variation sets its own; Start from similar brings back the one this file was made from
  S.seed = null; S.seedLane = null;
  if (lane === 'image') {
    const usable = ((S.catalog && S.catalog.image_models) || []).find(m => m.id === (s.model || h.model) && m.runnable);
    S.model = usable ? usable.id : S.model;
    if (usable) { S.modelChosen = true; S.wanted = null; }
    if (s.size || h.size) S.size = s.size || h.size;
    S.style = s.style || h.style || 'none'; S.steps = s.steps || h.steps || null; setSeed(item.seed, 'image');
    if (h.live !== undefined && !(item.how.sources || []).length) S.live = !!h.live;
  } else if (lane === 'voice') { S.voice = s.voice || h.voice || S.voice; if (h.speed) S.speed = Number(h.speed); S.description = h.description || ''; }
  else if (lane === 'music') { if (s.duration || h.duration) S.duration = Number(s.duration || h.duration); S.lyrics = h.lyrics && h.lyrics !== '[instrumental]' && h.lyrics !== '[inst]' ? h.lyrics : ''; }
  else if (lane === 'video') { if (h.seconds) S.videoSeconds = Number(h.seconds); if (h.model) S.videoModel = h.model; if (h.size && S.catalog.video_shapes[h.size]) S.videoShape = h.size; setSeed(item.seed, 'video'); }
  else if (lane === 'animation') { for (const [k, key] of [['look', 'look'], ['font', 'animFont'], ['shape', 'shape'], ['direction', 'direction'], ['template', 'template']]) if (h[k]) S[key] = h[k]; if (h.seconds) S.animSeconds = Number(h.seconds); }
  else if (lane === 'text') {
    if (h.task) S.textTask = h.task; if (h.tone) S.tone = h.tone; if (h.length) S.length = Number(h.length); if (h.target) S.target = h.target;
    // the writer comes back too, when it is still on the list; a writer LM Studio no longer has leaves the choice as it was
    const writer = ((S.catalog && S.catalog.writers) || []).find(w => w.id === (s.model || h.model));
    if (writer) S.writer = writer.id;
    else if (s.model || h.model) setTimeout(() => notice('The writer this was made with is not on the list right now, so the one chosen before is kept.', 'warn'), 0);
  }
  S.item = null; setLane(lane); render(); renderPanel();
}
$('sourcePick').onclick = () => pickFromGallery(S.lane === 'edit' ? 'Choose a picture to edit' : 'Choose a starting picture');
$('sourceClear').onclick = () => { S.source = null; renderPanel(); updateComposer(); };
$('seedLock').querySelector('button').onclick = () => { setSeed(null); renderPanel(); updateComposer(); };
$('generateBtn').onclick = () => generate();
$('prompt').addEventListener('input', () => {
  updateComposer();
  fitPrompt();
});
$('settingsBtn').onclick = () => { $('panel').classList.toggle('open'); renderPanel(); };
$('panelClose').onclick = () => $('panel').classList.remove('open');

/* film strip */
async function refreshFilm() {
  if (!S.projects) return;
  const r = await api(`/api/gallery?project=${encodeURIComponent(S.projects.active)}&limit=40`);
  if (r.ok) { S.film = r.data.items; paintFilm(); render(); }
}
const filmCache = new Map();
let lastFilmKey = '';
function paintFilm() {
  const film = $('film');
  const key = activeJobs().map(j => j.id + (j.waiting ? 'w' : '')).join() + '|' + S.film.map(x => x.name).join() + '|' + (S.item ? S.item.name : '');
  if (key === lastFilmKey) { for (const j of activeJobs()) updateFilmJob(j); return; }
  lastFilmKey = key;
  film.replaceChildren();
  // this person's own work first; another person's running work after it, plainly marked as theirs
  const act = activeJobs(), own = act.filter(j => S.mine.has(j.id)), theirs = act.filter(j => !S.mine.has(j.id));
  for (const j of own) film.append(filmJob(j));
  for (const item of S.film) film.append(filmItem(item));
  for (const j of theirs) film.append(filmJob(j));
}
/* A job in the strip of recent work: the small version of its craft's progress drawing, and a few words under it. It is a
   real button, so the way back to a running job can be reached from the keyboard too. */
const filmCrafts = new Map();
function filmJob(job) {
  const mine = S.mine.has(job.id);
  const n = el('button', 'film-item job' + (mine ? '' : ' theirs')); n.dataset.job = job.id; n.type = 'button';
  const what = job.title || laneName(job.lane);
  n.title = mine ? what : `Someone else is making this: ${what}`;
  n.setAttribute('aria-label', (mine ? 'Your work in progress: ' : 'Someone else\'s work in progress: ') + what);
  const ring = el('span', 'ring');
  const c = Craft.make(job.lane, 'small'); filmCrafts.set(job.id, c);
  ring.append(c.el);
  n.append(ring, el('span', 'n', Craft.short(Craft.read(job))));  // its words from the first paint, before it is on the page
  if (!mine) n.append(el('span', 'whose', 'Someone else'));
  updateFilmJob(job);
  n.onclick = () => { S.focus = job.id; S.item = null; prepareFrame(job); tick(job); render(); };
  return n;
}
function updateFilmJob(job) {
  const c = filmCrafts.get(job.id); if (!c) return;
  const t = Craft.read(job);
  c.update(t);
  const n = document.querySelector(`.film-item.job[data-job="${CSS.escape(job.id)}"] .n`);
  if (n) { const s = Craft.short(t); if (n.textContent !== s) n.textContent = s; }
  for (const id of filmCrafts.keys()) if (!S.jobs.some(j => j.id === id && j.state === 'running')) filmCrafts.delete(id);
}
function filmItem(item) {
  const b = el('button', 'film-item' + (item.kind === 'image' || item.kind === 'video' ? '' : ' wide') + (S.item && S.item.name === item.name ? ' here' : ''));
  b.title = item.caption || item.prompt || '';
  if (item.kind === 'image' || item.kind === 'video') {
    const img = el('img'); img.loading = 'lazy'; img.src = item.thumb; img.alt = ''; b.append(img);
    if (item.kind === 'video') b.append(el('span', 'badge'));
  } else if (item.kind === 'text') { b.className += ' txt wide'; b.textContent = (item.excerpt || '').slice(0, 110); }
  else {
    const wf = el('div', 'wf'); b.append(wf);
    if (filmCache.has(item.name)) requestAnimationFrame(() => waveBars(wf, filmCache.get(item.name)));
    else api('/peaks/' + encodeURIComponent(item.name)).then(r => { if (r.ok) { filmCache.set(item.name, r.data.peaks); waveBars(wf, r.data.peaks); } });
  }
  b.onclick = () => openItem(item);
  return b;
}

/* how this was made */
function howRow(body, k, v) { if (v === null || v === undefined || v === '') return; const row = el('div', 'how-row'); row.append(el('div', 'k', k), el('div', 'v', String(v))); body.append(row); }
function openHow() {
  const item = S.item; const how = item && item.how; const body = $('howBody');
  if (!how) return;
  body.replaceChildren();
  howRow(body, 'Description', how.prompt || item.prompt);
  if (how.prompt_as_sent && how.prompt_as_sent !== how.prompt) howRow(body, 'As sent', how.prompt_as_sent);
  howRow(body, 'Starting number', how.seed); howRow(body, 'Made with', how.model);
  howRow(body, 'Made', when(how.made));
  if (item.elapsed || how.seconds) howRow(body, 'Took', clock(item.elapsed || how.seconds));  // the same figure as the line under the result
  howRow(body, 'Recipe', how.recipe); howRow(body, 'Step', how.step);
  if (how.sources.length) howSources(body, how.sources);
  const names = {size: 'Size', steps: 'Steps', seconds: 'Length', duration: 'Length', style: 'Look', look: 'Look', voice: 'Voice', speed: 'Speed', template: 'Kind', direction: 'Move', tone: 'Tone', length: 'Length', scale: 'Enlarged by', strength: 'Stayed close'};
  const fromPicture = (how.sources || []).some(s => s.param === 'source' && s.file);
  const settings = Object.entries(how.settings || {}).filter(([k, v]) => names[k] && v !== '' && v !== null && v !== undefined && v !== 0 && !(k === 'speed' && Number(v) === 1)
    && !(k === 'strength' && (!fromPicture || item.kind !== 'image')));  // closeness only means something for a picture redrawn from a picture
  if (settings.length) howRow(body, 'Settings', settings.map(([k, v]) => `${names[k]}: ${howValue(k, v)}`).join(', '));
  const again = el('button', 'primary', 'Make it again');
  again.style.marginTop = '14px'; again.disabled = !how.can_remake;
  again.title = how.can_remake ? 'The same settings and seed, as a new file. The original is kept.' : 'This one cannot be repeated exactly.';
  again.onclick = () => remake(item);
  body.append(again);
  $('how').hidden = false; $('howScrim').hidden = false;
  document.body.classList.add('how-open');  // the studio makes room for the sheet, so it covers no part of the result row or the composer
}
/* Which pieces this one was made from, each named by its own words with its small picture, and one press away. A file
   that is no longer in the output folder is said to be gone rather than left out. */
function howSources(body, sources) {
  const row = el('div', 'how-row');
  const list = el('div', 'v how-sources');
  for (const s of sources) {
    if (!s.name) { list.append(el('div', 'how-gone', s.file ? 'A file that is no longer in the output folder' : 'An earlier file')); continue; }
    const b = el('button', 'how-source');
    if (s.thumb) { const im = el('img'); im.src = s.thumb; im.alt = ''; b.append(im); }
    const t = el('span', 't'); t.append(el('b', '', s.caption || 'A piece with no words saved'), el('small', '', 'Press to open it'));
    b.append(t);
    b.onclick = async () => {
      const r = await api('/api/item/' + encodeURIComponent(s.name));
      if (!r.ok) { toast('That file is no longer in the output folder.'); return; }
      closeHow(); openItem(r.data);
    };
    list.append(b);
  }
  row.append(el('div', 'k', sources.length === 1 ? 'Started from' : `Started from ${sources.length} pieces`), list);
  body.append(row);
}
/* A saved setting as the screen names it, never the engine's own word for it. */
function howValue(k, v) {
  const c = S.catalog || {}, a = c.animation || {};
  const named = (list, id) => ((list || []).find(x => x.id === id) || {}).label;
  const out = {voice: () => named(c.voices, v), speed: () => `${Number(v).toFixed(2)} times`, style: () => named(c.styles, v), look: () => (a.looks || {})[v], template: () => named(a.templates, v),
    direction: () => (a.directions || {})[v], tone: () => (c.text_tones || {})[v], length: () => (c.text_lengths || {})[v], size: () => titleCase(String(v)),
    strength: () => `${Math.round(Number(v) * 100)} percent`, seconds: () => `${v} seconds`, duration: () => `${v} seconds`, scale: () => `${v} times`}[k];
  return (out && out()) || (typeof v === 'string' ? titleCase(v) : v);
}
function closeHow() { $('how').hidden = true; $('howScrim').hidden = true; document.body.classList.remove('how-open'); }
$('howClose').onclick = closeHow; $('howScrim').onclick = closeHow;
async function remake(item) {
  closeHow();
  if (S.sending) return;
  S.sending = true;
  const r = await api('/api/create', {lane: 'remake', name: item.name});
  sendFinished(r);
  if (!r.ok) { notice(r.data.error || 'That could not be started.', r.status === 409 ? 'warn' : ''); return; }
  begin(r.data);
}

/* variations */
function openVariations(anchor, item) {
  const pop = $('variationPop');
  if (!pop.hidden) { closePopovers(); return; }
  closePopovers();
  pop.replaceChildren();
  pop.append(el('h4', '', 'New versions of this picture'));
  const box = el('div'); box.style.padding = '4px 8px 8px';
  const lab = el('div', 'help', 'How close should they stay?');
  const line = el('div', 'field');
  const r = el('input'); r.type = 'range'; r.min = 0; r.max = 90; r.step = 10; r.value = 0; r.setAttribute('aria-label', 'How close to stay');  // the first stop past New each time is 10 percent, the loosest the engine takes
  const out = el('span', 'num', 'Free'); out.style.minWidth = '74px';
  const desc = () => { const v = Number(r.value); out.textContent = v === 0 ? 'New each time' : v < 40 ? 'Loosely' : v < 70 ? 'Fairly close' : 'Very close'; };
  r.oninput = desc; desc(); line.append(r, out);
  const row = el('div', 'opts'); row.style.marginTop = '10px';
  for (const n of [1, 2, 4, 8]) { const b = el('button', 'opt num', n === 1 ? 'One' : `${n} of them`); b.onclick = () => { closePopovers(); variation(item, n, Number(r.value) / 100); }; row.append(b); }
  box.append(lab, line, row); pop.append(box);
  placePopover(pop, anchor, true);
}
function variation(item, count, strength) {
  const name = item.name;
  loadSettings(item);
  S.seed = null;
  const brought = ok => { if (!ok) showItem(item); };  // nothing started, so the picture stays where it was
  if (strength > 0) {
    S.source = item; S.strength = strength;
    generate({parent: name, count, source: name, strength}).then(ok => { S.source = null; S.strength = undefined; updateComposer(); brought(ok); });
  } else generate({parent: name, count, seed: null}).then(brought);
}

/* enhance */
function showSuggest(label, text, choices) { $('suggest').hidden = false; $('suggestLabel').textContent = label; $('suggestText').textContent = text; $('suggestRow').hidden = !choices; }
function hideSuggest() { $('suggest').hidden = true; }
/* A rewrite is a job like any other: it can wait in line, be stopped, and be picked up again after a reload. */
const ENHANCE_KEY = 'neovak.enhance';
function enhanceNote(v) { try { if (v) localStorage.setItem(ENHANCE_KEY, JSON.stringify(v)); else localStorage.removeItem(ENHANCE_KEY); } catch (e) { /* the page works without it */ } }
function enhanceSaved() { try { return JSON.parse(localStorage.getItem(ENHANCE_KEY) || 'null'); } catch (e) { return null; } }
function followEnhance(id, from) {
  S.enhance = id; S.enhanceFrom = from; $('enhanceBtn').disabled = true;
  showSuggest('Waiting for the writing helper...', '', false);
  const finish = () => { clearInterval(t); S.enhance = null; $('enhanceBtn').disabled = false; $('suggestBusy').hidden = true; };
  const look = async () => {
    const p = await api('/api/enhance/' + encodeURIComponent(id));
    if (S.enhance !== id) return;
    if (!p.ok) { if (p.status === 404) { finish(); hideSuggest(); enhanceNote(null); } return; }
    if (p.data.state === 'running') {
      $('suggestLabel').textContent = p.data.waiting ? `Waiting in line${p.data.position ? `, number ${p.data.position}` : ''}. Your words will be rewritten when their turn comes.` : 'Rewriting your words... ' + clock(p.data.elapsed || 0);
      $('suggestBusy').hidden = !p.data.can_stop;
      return;
    }
    finish();
    if (p.data.state === 'done') { showSuggest('Suggested rewrite', p.data.text, true); return; }  // kept until it is used or dismissed, so a reload still has it
    hideSuggest(); enhanceNote(null);
    if (p.data.state === 'cancelled') toast('Stopped. Your words were left as they are.');
    else notice(p.data.message || 'The writing helper could not finish.', 'warn');
  };
  const t = setInterval(look, 1200);
  look();
}
function resumeEnhance() {
  const v = enhanceSaved();
  if (!v || !v.id || S.enhance) return;
  if (v.lane && v.lane !== S.lane && LANES.find(l => l.id === v.lane)) setLane(v.lane);
  followEnhance(v.id, v.from || '');
}
$('enhanceBtn').onclick = async () => {
  if (S.enhance) return;
  const text = $('prompt').value.trim();
  if (!text) { notice('Please write something to improve first.'); return; }
  $('undoBtn').hidden = true; S.undoText = null;
  $('enhanceBtn').disabled = true;
  showSuggest('Waiting for the writing helper...', '', false);
  const r = await api('/api/enhance', {prompt: text, lane: S.lane});
  if (!r.ok) { $('enhanceBtn').disabled = false; hideSuggest(); notice(r.data.error || 'That could not be started.', r.status === 409 ? 'warn' : ''); return; }
  enhanceNote({id: r.data.id, from: text, lane: S.lane});
  followEnhance(r.data.id, text);
};
$('suggestStop').onclick = async () => {
  if (!S.enhance) return;
  const r = await api('/api/job/' + encodeURIComponent(S.enhance) + '/stop', {});
  if (!r.ok) notice(r.data.error || 'That could not be stopped.', 'warn'); else toast('Stopping.');
};
$('suggestUse').onclick = () => { S.undoText = S.enhanceFrom; $('prompt').value = $('suggestText').textContent; hideSuggest(); enhanceNote(null); $('undoBtn').hidden = false; updateComposer(); };
$('suggestKeep').onclick = () => { hideSuggest(); enhanceNote(null); };
$('undoBtn').onclick = () => { if (S.undoText !== null) $('prompt').value = S.undoText; S.undoText = null; $('undoBtn').hidden = true; toast('Back to your original words.'); };
