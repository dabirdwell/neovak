'use strict';
/* What each colour of the memory dot means, on the dot itself. */
const DOT_WORDS = {green: 'Plenty of room in memory', yellow: 'Should fit in memory', orange: 'A tight fit in memory', red: 'Will not fit in memory right now', unknown: 'Checked when its turn comes'};
/* Shapes in plain words. Wide and Tall are the same proportions as a phone screen on its side and upright. */
const SIZE_WORDS = {square: 'Square', landscape: 'Landscape', portrait: 'Portrait', wide: 'Wide, like a screen', tall: 'Tall, like a phone', banner: 'Banner'};
/* On a card in a row of three, one word each; the longer words are on hover. */
const SHAPE_SHORT = {wide: 'Wide', tall: 'Tall', banner: 'Banner'};
const VOICE_AUDIO = new Map();  // the voice samples heard from the Settings panel
/* One choice in a list of models, voices or tools. The plain name and what it is for come first. The memory it asks
   for and how long it usually takes sit on the right. The engine's own name is shown only when Advanced is open. */
function modelRow(m, isSel, onPick) {
  const b = el('button', 'model' + (isSel ? ' sel' : ''));
  b.disabled = !m.runnable;
  const top = el('div', 'top'); top.append(el('span', 'name', m.label));
  const mem = el('span', 'mem num');
  // "about 5.3 GB" is a figure worked out from the size on disk; a plain "7.2 GB" was measured on a real run here. The dot
  // is the fit, in the same four colours the help explains; its words are on hover and in the chip by Generate.
  // With Watch it arrive on, a card that can watch always shows the watched figures, whatever the memory does: when
  // watching does not fit right now, its line says so and gives the figures it would be made with instead. So the card
  // does not change its promise by itself while the switch stays where the person put it.
  const watchedOff = S.lane === 'image' && m.liveOff && m.asks && m.asks.live;
  const shownGb = watchedOff ? m.asks.live.gb : m.gb;
  const figure = !shownGb ? 'nothing to load' : m.gb_kind === 'estimate' ? `about ${shownGb} GB` : `${shownGb} GB`;
  const fig = el('span', 'fig'); const dot = el('span', 'dot ' + m.badge); dot.title = DOT_WORDS[m.badge] || ''; if (dot.title) dot.setAttribute('aria-label', dot.title);
  fig.append(dot, el('span', '', figure)); mem.append(fig);
  mem.title = m.badge_text + (m.gb_kind === 'estimate' ? ' The figure is worked out from the size on disk, until a run here has been measured.' : m.gb_kind === 'measured' ? ' Measured on a real run here.' : '');
  top.append(mem);
  if (m.full_name && m.full_name !== m.label) b.title = 'Listed in LM Studio as ' + m.full_name;
  const secs = timeFor(m.id) || m.seconds;  // for the settings as they stand, once the server has answered for them
  // A voice's time follows the words: it says so, so a figure that grows as the words are typed is not a surprise.
  const forWhat = S.lane === 'voice' ? ($('prompt').value.trim() ? ' for these words' : ' for a short sentence')
    : S.lane === 'image' && m.live && S.live && !S.source ? ', watching it arrive' : '';  // the card says when its figures include watching
  const plain = watchedOff ? plainTimeFor(m.id) : null;
  const instead = watchedOff ? `Watching does not fit right now, so it would be made without it: ${m.gb} GB${plain ? `, about ${aboutTime(plain)}` : ''}.` : '';
  const facts = [m.loaded ? 'In memory now.' : '', m.note, secs ? `About ${aboutTime(secs)}${forWhat}.` : '', instead].filter(Boolean).join(' ');
  b.append(top, el('div', 'sub', facts));
  if (S.advanced && m.engine) b.append(el('div', 'eng', 'Runs on ' + m.engine));
  if (!m.runnable) { const why = el('div', 'why', m.reason_short || m.reason || m.badge_text); why.title = m.reason || m.badge_text; b.append(why); }  // one line here; the whole sentence on hover and in the chip
  b.onclick = onPick; return b;
}
/* The fold that keeps the first view short. What sits inside it is for people who already know they want it. */
function advancedFold(body, fill, hint) {
  const btn = el('button', 'fold' + (S.advanced ? ' open' : ''));
  btn.setAttribute('aria-expanded', String(S.advanced));
  btn.innerHTML = '<svg viewBox="0 0 10 6" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
  btn.append(el('span', '', 'Advanced'), el('small', '', S.advanced ? 'Hide the extra controls' : (hint || 'What runs underneath')));
  btn.onclick = () => {
    S.advanced = !S.advanced; renderPanel();
    // The rows above grow their engine lines when the fold opens, which would push the fold and its controls out of a short
    // sheet; so the fold is brought back into view, with its first controls under it.
    const opened = $('panelBody').querySelector('.fold.open');
    if (opened && S.advanced) requestAnimationFrame(() => opened.scrollIntoView({block: 'start', behavior: Craft.reduced() ? 'auto' : 'smooth'}));
  };
  body.append(btn);
  if (S.advanced) { const box = el('div', 'fold-body'); fill(box); body.append(box); }
}
/* map is {id: label}; a label may be {label, sub} when a small second line (such as the time) belongs under it. */
function optRow(body, title, map, cur, set, help) {
  body.append(el('h3', '', title));
  const r = el('div', 'opts');
  for (const [id, label] of Object.entries(map)) {
    const b = el('button', 'opt' + (String(cur) === String(id) ? ' sel' : ''));
    if (label && typeof label === 'object') { b.classList.add('two'); b.append(el('span', '', label.label)); if (label.sub) b.append(el('small', 'num', label.sub)); }
    else b.textContent = label;
    b.onclick = () => { set(id); renderPanel(); updateComposer(); };
    r.append(b);
  }
  body.append(r);
  if (help) body.append(el('p', 'help', help));
}
function seedField(body, what) {
  body.append(el('h3', '', 'Starting number'));
  const f = el('div', 'field');
  const seed = el('input'); seed.type = 'text'; seed.inputMode = 'numeric'; seed.placeholder = 'New each time'; seed.setAttribute('aria-label', 'Starting number');
  seed.value = S.seed === null ? '' : S.seed;
  seed.oninput = () => { const v = seed.value.trim(); setSeed(/^\d+$/.test(v) ? Number(v) : null); updateComposer(); };
  const clear = el('button', 'ghost', 'New each time');
  clear.onclick = () => { setSeed(null); seed.value = ''; updateComposer(); };
  f.append(seed, clear);
  body.append(f, el('p', 'help', `Every ${what} starts from a random number. Keep the same number to make the same ${what} again, or a close cousin after a small change to the words.`));
}
function renderPanel() {
  const body = $('panelBody');
  const active = document.activeElement;
  if (active && body.contains(active) && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
  body.replaceChildren();
  if (!S.catalog) return;
  const c = S.catalog;
  $('panelTitle').textContent = ({image: 'Picture', voice: 'Voice', music: 'Music', edit: 'Edit a picture', video: 'Video', animation: 'Animate', text: 'Writing', recipe: 'Recipe'})[S.lane];
  if (S.lane === 'recipe') {
    const r = currentRecipe(); if (!r) return;
    const v = recipeValues(r);
    // The steps themselves are on the board beside this panel, each with its time; the panel holds only the choices.
    const adv = r.inputs.filter(i => i.tier !== 'basic');
    const input = (host, i) => {
      host.append(el('h3', '', i.label));
      if (i.type === 'choice') {
        const opts = el('div', 'opts');
        // a choice can change how long a step takes (a 2 second clip against a 5 second one), so the times follow it
        for (const ch of i.choices) { const b = el('button', 'opt' + (v[i.name] === ch.value ? ' sel' : ''), ch.label); b.onclick = () => { v[i.name] = ch.value; renderPanel(); updateComposer(); }; opts.append(b); }
        host.append(opts);
      } else {
        const f = el('div', 'field'); const box = el('input');
        box.type = i.type === 'seed' || i.type === 'number' ? 'number' : 'text';
        box.placeholder = i.type === 'seed' ? 'A new one each time' : '';
        box.value = v[i.name] ?? '';
        box.oninput = () => { v[i.name] = box.value; updateComposer(); };
        f.append(box); host.append(f);
      }
      if (i.help) host.append(el('div', 'help', i.help));
    };
    // the choices a first-time person makes are in view; the starting number waits behind Advanced, as in the other lanes
    for (const i of adv.filter(x => x.type !== 'seed')) input(body, i);
    const seeds = adv.filter(x => x.type === 'seed');
    if (seeds.length) advancedFold(body, box => { for (const i of seeds) input(box, i); }, 'The starting number');
    body.append(el('h3', '', 'Save for next time'));
    const save = el('div', 'save-row field');
    const name = el('input'); name.type = 'text'; name.placeholder = 'A name for this recipe'; name.setAttribute('aria-label', 'A name for this recipe');
    const go = el('button', 'chip', 'Save'); go.onclick = () => saveRecipe(name);
    save.append(name, go); body.append(save);
    body.append(el('div', 'help', 'Saves what you have typed and chosen here as the starting point of a new recipe.'));
    if (!r.builtin) {
      // One press asks; a second one removes, so a stray press does not lose the saved settings. The question is kept in
      // the page's state, not only on screen, so the panel being drawn again (it is, whenever the memory figures move)
      // brings it back instead of throwing it away.
      const del = el('button', 'ghost', 'Remove this recipe'); del.style.marginTop = '12px';
      const askRow = () => {
        const ask = el('div', 'ask-row');
        const t = el('div', 't'); t.append(el('b', '', `Remove ${r.label}?`), el('span', '', 'Its saved words and choices go. Anything it made stays in the gallery.'));
        const yes = el('button', 'pj-act on', 'Remove'), no = el('button', 'pj-act', 'Keep');
        yes.onclick = () => { S.askRemove = null; deleteRecipe(); };
        no.onclick = () => { S.askRemove = null; renderPanel(); };
        ask.append(t, yes, no);
        return ask;
      };
      del.onclick = () => { S.askRemove = r.id; renderPanel(); const keep = $('panelBody').querySelector('.ask-row .pj-act:not(.on)'); if (keep) keep.focus(); };
      body.append(S.askRemove === r.id ? askRow() : del);
    }
    return;
  }
  if (S.lane === 'image') {
    body.append(el('h3', '', 'Shape'));
    // Three shapes a first-time person can tell apart, as in Video and Animate. The wider, taller and banner shapes wait
    // under Advanced; one chosen from there is shown here too, so the choice made is always in view.
    const shapeButton = (name, value) => {
      const [w, h] = value.split('x').map(Number);
      const b = el('button', 'opt size' + (S.size === name ? ' sel' : ''));
      const shape = el('i'); const k = 15 / Math.max(w, h);
      shape.style.width = Math.round(w * k) + 'px'; shape.style.height = Math.round(h * k) + 'px';
      const t = el('span', 't'); t.append(el('span', '', SHAPE_SHORT[name] || SIZE_WORDS[name] || titleCase(name)), el('small', 'num', `${w} by ${h}`));
      b.append(shape, t); b.title = `${SIZE_WORDS[name] || titleCase(name)}, ${w} by ${h} pixels`;
      b.onclick = () => { S.size = name; renderPanel(); updateComposer(); };
      return b;
    };
    const MAIN_SHAPES = ['landscape', 'square', 'portrait'];
    const sizes = el('div', 'opts shapes three');
    // Always three cards in one row. A shape from Advanced (or from an idea) takes the place of the main shape it is
    // closest to, a wide one where Landscape stands and a tall one where Portrait stands, so the row never grows a fourth
    // card or wraps, and the shape in use is always in view.
    const STANDS_FOR = {wide: 'landscape', banner: 'landscape', tall: 'portrait'};
    if (S.source) body.append(el('p', 'help', 'Keeps the shape of your starting picture' + (S.source.dimensions ? ` (${S.source.dimensions})` : '') + ', so nothing gets stretched.'));
    else for (const name of MAIN_SHAPES) {
      const shown = STANDS_FOR[S.size] === name && c.sizes[S.size] ? S.size : name;
      if (c.sizes[shown]) sizes.append(shapeButton(shown, c.sizes[shown]));
    }
    body.append(sizes);
    optRow(body, 'How many', {1: 'One', 2: 'Two', 4: 'Four', 8: 'Eight'}, S.count, v => { S.count = Number(v); }, S.count > 1 ? 'Each one is made in turn, from its own starting number.' : '');
    body.append(el('h3', '', 'Quality'));
    const spec = c.image_models.find(m => m.id === S.model);
    // what the memory and time on each card are for, said once above them, so a card that differs from the Models page says why
    body.append(el('p', 'help basis', S.source ? 'Memory and time on each card are for starting from your picture, which asks for more than words alone.'
      : 'Memory and time on each card are for one picture in the shape above. A card that says watching it arrive includes that too.'));
    // Quick and Polished, the two on the wall, then the rest behind one row; the one chosen is always in view.
    const pick = m => () => { S.model = m.id; S.modelChosen = true; S.wanted = null; S.steps = null; renderPanel(); updateComposer(); };
    const first = c.image_models.slice(0, 2), rest = c.image_models.slice(2);
    for (const m of first) body.append(modelRow(realAsk(m), S.model === m.id, pick(m)));
    const chosenRest = rest.find(m => m.id === S.model);
    if (chosenRest) body.append(modelRow(realAsk(chosenRest), true, pick(chosenRest)));
    const moreModels = el('button', 'fold' + (S.allModels ? ' open' : ''));
    moreModels.setAttribute('aria-expanded', String(!!S.allModels));
    moreModels.innerHTML = '<svg viewBox="0 0 10 6" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
    moreModels.append(el('span', '', `${rest.length - (chosenRest ? 1 : 0)} more picture models`), el('small', '', S.allModels ? 'Hide the list' : 'Slower, for detail, photos or words'));
    moreModels.onclick = () => { S.allModels = !S.allModels; renderPanel(); };
    body.append(moreModels);
    if (S.allModels) { const box = el('div', 'fold-body'); for (const m of rest) if (m !== chosenRest) box.append(modelRow(realAsk(m), false, pick(m))); body.append(box); }
    // Watching it arrive changes the figures above, so its switch sits right under them instead of inside Advanced.
    const canWatch = c.image_models.filter(m => m.live).map(m => m.label);
    if (canWatch.length && !S.source) optRow(body, 'Watch it arrive', {1: 'On', 0: 'Off'}, S.live ? 1 : 0, v => { S.live = v === '1'; },
      `Shows the picture forming, step by step, with ${canWatch.join(', ')}. It asks for about 4 GB more memory and takes longer; the cards above include it while it is on.${spec && !spec.live ? ` ${spec.label} makes its picture without it.` : ''}`);
    body.append(el('h3', '', 'Look'));
    const looks = el('div', 'opts');
    for (const s of c.styles) { const b = el('button', 'opt' + (S.style === s.id ? ' sel' : ''), s.label); b.title = s.text || 'Only your own words, nothing added'; b.onclick = () => { S.style = s.id; renderPanel(); updateComposer(); }; looks.append(b); }
    body.append(looks);
    if (S.source) {
      body.append(el('h3', '', 'How close to your picture'));
      const f = el('div', 'field'); const r = el('input'); r.type = 'range'; r.min = 10; r.max = 90; r.value = Math.round((S.strength || .5) * 100); r.setAttribute('aria-label', 'How close to your picture');
      const o = el('span', 'num', r.value + '%'); r.oninput = () => { S.strength = Number(r.value) / 100; o.textContent = r.value + '%'; };
      f.append(r, o); body.append(f, el('p', 'help', 'Low changes a lot. High stays close. Your picture is not changed.'));
    }
    advancedFold(body, box => {
      if (!S.source) {
        box.append(el('h3', '', 'Other shapes'));
        const other = el('div', 'opts shapes three');
        for (const [name, value] of Object.entries(c.sizes)) if (!MAIN_SHAPES.includes(name)) other.append(shapeButton(name, value));
        box.append(other);
      }
      seedField(box, 'picture');
      box.append(el('h3', '', 'Steps'));
      const stepField = el('div', 'field');
      const range = el('input'); range.type = 'range'; range.min = 1; range.max = 30; range.value = S.steps || spec.steps; range.setAttribute('aria-label', 'Steps');
      const out = el('span', 'num', S.steps ? String(S.steps) : `${spec.steps} (usual)`);
      range.oninput = () => { S.steps = Number(range.value) === spec.steps ? null : Number(range.value); out.textContent = S.steps ? String(S.steps) : `${spec.steps} (usual)`; };
      stepField.append(range, out);
      box.append(stepField, el('p', 'help', 'How many passes the model makes over the picture. More take longer and can add detail. The usual number is the one it was tested at.'));
    }, 'Other shapes, the starting number, steps, and what runs underneath');
  } else if (S.lane === 'voice') {
    body.append(el('h3', '', 'Voice'));
    // each voice with its own sample beside it, so the voices can be heard and chosen in one list
    for (const m of c.voices) {
      const row = el('div', 'voice-pick');
      const sample = ((S.starters || {}).voices || []).find(v => v.id === m.id && v.file);
      if (sample) {
        // one player per voice for the life of the page: the panel is drawn again when memory figures move, and a sample
        // being heard is not cut off by that
        if (!VOICE_AUDIO.has(m.id)) { const a = el('audio'); a.src = '/starters/' + sample.file; a.preload = 'none'; VOICE_AUDIO.set(m.id, a); }
        const a = VOICE_AUDIO.get(m.id);
        const play = el('button', 'play-btn' + (!a.paused ? ' on' : '')); play.setAttribute('aria-label', `Hear ${m.label}`); play.title = `Hear ${m.label}: ${sample.text}`;
        play.onclick = () => togglePlay(a, play); a.onended = () => { for (const b of document.querySelectorAll('.voice-pick .play-btn.on')) b.classList.remove('on'); };
        if (!a.paused && nowPlaying && nowPlaying.a === a) nowPlaying.b = play;
        row.append(play);
      } else { const none = el('span', 'play-btn mute'); none.title = 'No sample recorded yet'; row.append(none); }
      row.append(modelRow(m, S.voice === m.id, () => { S.voice = m.id; renderPanel(); updateComposer(); }));
      body.append(row);
    }
    if (S.voice === 'qwen3-tts') {
      body.append(el('h3', '', 'Describe the voice'));
      const t = el('textarea'); t.rows = 3; t.value = S.description; t.placeholder = 'A warm, slightly amused radio host'; t.setAttribute('aria-label', 'Describe the voice'); t.oninput = () => { S.description = t.value; };
      body.append(t);
    }
    body.append(el('h3', '', 'Speed'));
    const f = el('div', 'field'); const r = el('input'); r.type = 'range'; r.min = 70; r.max = 140; r.value = Math.round(S.speed * 100); r.setAttribute('aria-label', 'Speed');
    const o = el('span', 'num', S.speed.toFixed(2) + ' times'); r.oninput = () => { S.speed = Number(r.value) / 100; o.textContent = S.speed.toFixed(2) + ' times'; };
    f.append(r, o); body.append(f);
    const chosen = c.voices.find(v => v.id === S.voice);
    if (chosen && chosen.english_only) body.append(el('p', 'help', 'This voice reads English. Words in another language come out with English sounds.'));
    advancedFold(body, box => { box.append(el('p', 'help', chosen && !chosen.own_speed ? 'This voice keeps its own pace, so the finished recording is sped up or slowed down afterward. The pitch stays the same.' : 'This voice changes its own pace when the speed is changed.')); }, 'How the speed works, and what runs underneath');
  } else if (S.lane === 'edit') {
    body.append(el('h3', '', 'What to do'));
    for (const t of c.edit_tools) body.append(modelRow(t, S.tool === t.id, () => { S.tool = t.id; renderPanel(); updateComposer(); }));
    if (S.tool === 'bigger') optRow(body, 'How much larger', Object.fromEntries(c.edit_scales.map(n => [n, n + ' times'])), S.scale, v => { S.scale = Number(v); });
    advancedFold(body, box => { box.append(el('p', 'help', 'Each tool above shows what it runs on. The original picture is never changed.')); }, 'What runs underneath');
  } else if (S.lane === 'video') {
    optRow(body, 'Length', Object.fromEntries(c.video_lengths.map(d => [d, {label: d + ' seconds', sub: altTimeFor(d) ? 'about ' + aboutTime(altTimeFor(d)) : ''}])), S.videoSeconds, v => { S.videoSeconds = Number(v); }, 'Longer clips take longer to make. The time under each length is what it usually takes here.');
    // no buttons that change nothing; and no picture size in brackets, which reads as the clip's size and is not
    if (S.source) { body.append(el('h3', '', 'Shape')); body.append(el('p', 'help', 'A clip started from a picture keeps the shape of that picture. It is made at the clip size, which is smaller than the picture, so nothing is stretched.')); }
    else optRow(body, 'Shape', c.video_shapes, S.videoShape, v => { S.videoShape = v; });
    body.append(el('h3', '', 'Quality'));
    for (const m of c.video_models) body.append(modelRow(m, S.videoModel === m.id, () => { S.videoModel = m.id; renderPanel(); updateComposer(); }));
    advancedFold(body, box => { seedField(box, 'clip'); }, 'The starting number, and what runs underneath');
  } else if (S.lane === 'animation') {
    const a = c.animation;
    optRow(body, 'Look', a.looks, S.look, v => { S.look = v; });
    optRow(body, 'Typeface', a.fonts, S.animFont, v => { S.animFont = v; });
    optRow(body, 'Shape', a.shapes, S.shape, v => { S.shape = v; });
    if (S.template === 'move') optRow(body, 'Move', a.directions, S.direction, v => { S.direction = v; });
    body.append(el('h3', '', 'Length'));
    const f = el('div', 'field'); const range = el('input'); range.type = 'range'; range.min = 2; range.max = 20; range.value = S.animSeconds; range.setAttribute('aria-label', 'Length in seconds');
    const out = el('span', 'num', S.animSeconds + ' seconds');
    range.oninput = () => { S.animSeconds = Number(range.value); out.textContent = S.animSeconds + ' seconds'; updateComposer(); };
    f.append(range, out);
    body.append(f, el('p', 'help', S.source && S.source.kind === 'video' ? 'A background clip sets the length, and its sound is kept.' : (timeFor('animation') ? `About ${aboutTime(timeFor('animation'))} to draw at this length.` : 'Longer animations take longer to draw.')));
    const tpl = a.templates.find(t => t.id === S.template);
    if (tpl) body.append(el('p', 'help', tpl.hint));
  } else if (S.lane === 'text') {
    // The choices a first-time writer needs come first: how long, what tone. The writer itself is below, and the
    // longer list of other writers already on this Mac sits behind one row, named as what they are.
    if (S.textTask === 'script') {
      optRow(body, 'Length when read aloud', c.text_lengths, S.length, v => { S.length = Number(v); });
      optRow(body, 'Tone', c.text_tones, S.tone, v => { S.tone = v; });
    }
    if (S.textTask === 'rewrite') optRow(body, 'What the words are for', c.text_targets, S.target, v => { S.target = v; });
    if (S.textTask === 'caption') body.append(el('p', 'help', 'A picture you choose is described to the writer using the words it was made from. The writer does not look at the picture itself.'));
    const pickWriter = m => () => { S.writer = m.id; renderPanel(); updateComposer(); };
    body.append(el('h3', '', 'Writer'));
    const always = c.writers.filter(m => m.source !== 'lmstudio'), inStudio = c.writers.filter(m => m.source === 'lmstudio');
    for (const m of always) body.append(modelRow(m, S.writer === m.id, pickWriter(m)));
    const chosenOther = inStudio.find(m => m.id === S.writer);
    if (chosenOther) body.append(modelRow(chosenOther, true, pickWriter(chosenOther)));  // the one in use is always in view
    const more = el('button', 'fold' + (S.allWriters ? ' open' : ''));
    more.setAttribute('aria-expanded', String(!!S.allWriters));
    more.innerHTML = '<svg viewBox="0 0 10 6" aria-hidden="true"><path d="M1 1l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.4"/></svg>';
    more.append(el('span', '', inStudio.length ? `${inStudio.length} more writers on this Mac` : 'More writers on this Mac'), el('small', '', S.allWriters ? 'Hide the list' : (inStudio.length ? 'Other writing models kept on this Mac' : 'None found right now')));
    more.onclick = () => { S.allWriters = !S.allWriters; renderPanel(); };
    body.append(more);
    if (S.allWriters) {
      const box = el('div', 'fold-body');
      if (inStudio.length) {
        for (const m of inStudio) if (m !== chosenOther) box.append(modelRow(m, S.writer === m.id, pickWriter(m)));
        box.append(el('p', 'help', 'These are language models kept by LM Studio, another app on this Mac, listed smallest first under the names it gives them. One loads when you ask for it, after the memory check, and leaves memory 15 minutes after its last use. A figure that says "about" is worked out from the size on disk until the first run here has been measured.'));
      } else {
        box.append(el('p', 'help', c.lmstudio && c.lmstudio.running ? 'LM Studio, another app on this Mac, is running but lists no language model.' : 'LM Studio, another app on this Mac, is not running right now, so its writers are not offered. Start it and this list fills in.'));
      }
      body.append(box);
    }
  } else if (S.lane === 'music') {
    const upto = S.est && S.est.lane === 'music' && S.est.upto ? S.est.upto : null;  // for the chosen length, a range when recent runs went well past the usual figure
    optRow(body, 'Length', Object.fromEntries(c.music_lengths.map(d => [d, {label: d + ' seconds', sub: altTimeFor(d) ? 'about ' + (Number(d) === Number(S.duration) && upto > altTimeFor(d) ? aboutRange(altTimeFor(d), upto) : aboutTime(altTimeFor(d))) : ''}])), S.duration, v => { S.duration = Number(v); },
      'Longer pieces take longer to make. The time under each length is what it usually takes here; when recent runs of the chosen length varied a lot, it shows the range they took.');
    body.append(el('h3', '', 'Words to sing (optional)'));
    const t = el('textarea'); t.rows = 4; t.value = S.lyrics; t.placeholder = 'Leave empty for an instrumental piece'; t.setAttribute('aria-label', 'Words to sing'); t.oninput = () => { S.lyrics = t.value; };
    body.append(t);
    advancedFold(body, box => { box.append(el('h3', '', 'What makes it')); box.append(modelRow(c.music, true, () => {})); }, 'What runs underneath');
  }
}
