'use strict';
/* Progress you can read, one for each craft.
   Picture, Edit, Animate, Writing and Recipes: a film strip that exposes one more frame per finished step.
   Video: a film leader countdown, with the minutes left in the centre and a hand that sweeps real seconds.
   Music: a record and a tonearm that travels from the outer groove to the label.
   Voice: a studio recording, an ON AIR lamp and a waveform drawn behind a moving playhead.
   Every dial follows the job's real numbers: the step the engine reports when it reports one, otherwise the time
   elapsed against what this kind of work usually takes here. Nothing moves faster than the truth. Time alone never
   fills a dial: the last tenth is kept for the real end, which only the engine can report, so a job that runs past
   its usual time stops short and the words beside it say so. With reduced motion on, the page's own rule turns off
   every animation and transition, and what is left is a still picture that updates with each report. */
const Craft = (() => {
  const NS = 'http://www.w3.org/2000/svg';
  const KIND = {video: 'leader', music: 'vinyl', voice: 'onair', speech: 'onair'};
  const kindFor = lane => KIND[lane] || 'strip';
  const reduced = () => !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
  let seq = 0;
  const uid = () => 'craft' + (++seq);
  function sv(tag, attrs, parent) {
    const n = document.createElementNS(NS, tag);
    for (const k in (attrs || {})) n.setAttribute(k, attrs[k]);
    if (parent) parent.append(n);
    return n;
  }
  function root(w, h, cls) { return sv('svg', {viewBox: `0 0 ${w} ${h}`, class: 'craft ' + cls, 'aria-hidden': 'true', focusable: 'false'}); }
  /* The first paint lands where the job already is; only later changes are allowed to glide. */
  function place(node, value, state) {
    if (state.first) { node.style.transition = 'none'; node.style.transform = value; void node.getBoundingClientRect(); node.style.transition = ''; state.first = false; }
    else node.style.transform = value;
  }

  /* The truth of one job, read the same way everywhere. */
  function read(job) {
    const estimate = Number(job.estimate) || 0, elapsed = Math.max(0, Number(job.elapsed) || 0);
    const total = Number(job.total) || 0;
    const step = job.step === null || job.step === undefined ? null : Math.max(0, Number(job.step) || 0);
    const steps = total > 0 && step !== null;
    const waiting = !!job.waiting;
    // The last step reported is not the end: a picture is still decoded and saved, an enlargement still written out.
    // So when every step is in, the job is "finishing": the dial keeps the last part back for the real end, which
    // only the engine can report, and the words say finishing rather than counting a second that never ends.
    const finishing = steps && step >= total;
    // Held at the memory check: nothing is being made yet, so no time is left to count down and no part is filled
    // beyond what was really done; the figures stand still and the words say what it is waiting for.
    const held = !!job.held && !waiting;
    const heldFor = Math.max(0, Number(job.held_for) || 0);
    // The model is still loading: none of its steps has begun, so no frame is lit for them, and the time left is the
    // engine's (what is left of the usual load plus all of the steps) or, before any load has been timed here, none.
    const loading = !waiting && !held && job.phase === 'loading' && !steps;
    const loadKnown = loading && !!job.phase_known;
    // the first run of its kind on this Mac: its steps are counted as they come, and no time left is promised yet
    const untimed = !waiting && !held && job.phase === 'steps' && !job.phase_known;
    const timeP = estimate && !loading ? Math.min(1, elapsed / estimate) : 0;
    const p = waiting ? 0 : steps ? Math.min(1, step / total) : timeP;
    // A job of one or two steps reports almost nothing until its end, so between its reports the time against its
    // usual time fills the dial too (never past nine tenths), and the dial never falls back when a report arrives.
    const dial = steps ? Math.max(Math.min(p, 1 - 0.5 / Math.max(1, total)), total < 3 && !held ? timeP * 0.9 : 0) : (held ? 0 : p * 0.9);
    // Past the usual time, with a few seconds of grace so a run that lands a breath late is not called slow.
    const over = !waiting && !held && !loadKnown && estimate > 0 && elapsed > estimate + Math.max(4, estimate * 0.08);
    const remaining = estimate && !held && !(loading && !loadKnown) && !untimed ? Math.max(0, estimate - elapsed) : null;
    // A recipe's own steps: which one is on, so the tile and the popover can say what their figures count.
    const list = Array.isArray(job.steps) ? job.steps : null;
    const at = list ? list.findIndex(s => s.state === 'running' || s.state === 'waiting') : -1;
    const recipe = list && list.length ? {n: at < 0 ? list.filter(s => s.state === 'done').length : at + 1, of: list.length, label: at >= 0 ? list[at].label : ''} : null;
    return {waiting, held, heldFor, position: job.position || 1, steps, step: step || 0, total, planned: Number(job.planned) || 0, p, dial, elapsed, estimate, remaining, over, finishing,
            stage: job.stage || '', id: String(job.id || ''), recipe, loading, loadKnown, loadOver: !!job.load_over, stepsSeconds: Number(job.steps_seconds) || 0,
            night: !!job.night};
  }
  /* One figure for the time left, and the sentence, the tile and the leader's centre all print that same figure, so
     they cannot disagree. It is rounded the same way as the time promised before the press (aboutTime): half minutes
     under ten minutes, whole minutes above, and under 45 seconds, seconds in steps of five. */
  function figure(r) {
    if (r >= 45) { const m = r / 60; return {n: m < 10 ? Math.max(1, Math.round(m * 2) / 2) : Math.round(m), unit: 'min'}; }
    if (r >= 5) return {n: Math.ceil(r / 5) * 5, unit: 's'};
    return {n: Math.max(1, Math.ceil(r)), unit: 's'};  // the last few seconds count down one by one
  }
  function left(r) {
    if (r < 1) return '';  // the usual time is spent and the engine has not said it is done: no number is honest here
    const f = figure(r);
    if (f.unit === 'min') return f.n === 1 ? 'about a minute left' : `about ${f.n} minutes left`;
    return f.n === 1 ? 'about a second left' : `about ${f.n} seconds left`;
  }
  /* The sentence beside the dial. */
  function words(t) {
    if (t.night) return `${t.stage || 'Waiting for the nightly job'}. It starts by itself then. Work that loads no model, such as an animation, can go ahead of it`;
    if (t.waiting) return `Waiting for its turn, number ${t.position} in line`;
    if (t.held) return `Waiting for memory to free up, ${clock(t.heldFor)} so far. It starts by itself when there is room`;
    if (t.loading) {
      const steps = t.total ? `the ${t.total} steps` : 'the work itself';
      if (!t.loadKnown) return t.over ? `Getting the model ready, taking longer than usual: ${clock(t.elapsed)} so far, usually about ${aboutTime(t.estimate)} in all`
        : `Getting the model ready, ${clock(t.elapsed)} so far. Usually about ${aboutTime(t.estimate)} in all, counted once ${steps} begin`;
      if (t.loadOver) return `Getting the model ready, which is taking a little longer than usual. Then about ${aboutTime(t.stepsSeconds)} for ${steps}`;
      return 'Getting the model ready, ' + (left(t.remaining) || 'nearly ready');
    }
    const stage = t.stage && !['Working', 'Starting', 'Finished', 'Waiting for memory to free up'].includes(t.stage) ? t.stage + '. ' : '';
    const where = t.steps ? (t.finishing ? '' : t.step ? `Step ${t.step} of ${t.total}` : `${t.total} steps to go`) : `${clock(t.elapsed)} so far`;
    if (t.over) return stage + (where && t.steps ? where + '. ' : '') + `Taking longer than usual: ${clock(t.elapsed)} so far, usually about ${clock(t.estimate)}`;
    // Every step reported: the work is being written out. Not "done", and not "finishing" next to a time still to come.
    if (t.finishing) return stage + (t.remaining !== null && t.remaining >= 1 ? 'Finishing, ' + left(t.remaining) : 'Finishing');  // the same word as its tile
    const rest = t.remaining !== null ? left(t.remaining) : '';
    // inside the grace after the usual time, with steps still to come, the step count stands alone: no time is promised
    if (!rest && !t.steps && t.remaining !== null) return stage + (t.elapsed >= 2 ? `${clock(t.elapsed)} so far, nearly done` : 'Just started');
    if (!rest && t.steps && t.remaining === null) return stage + where + `, ${clock(t.elapsed)} so far`;  // counted, not promised
    return stage + where + (rest ? ', ' + rest : '');
  }
  /* The whole of a recipe, for the line popover: which step is on, and the figures for the whole run, named as such. */
  function recipeWords(t) {
    if (!t.recipe) return words(t);
    if (t.waiting) return `Step ${t.recipe.n} of ${t.recipe.of}, waiting for its turn, number ${t.position} in line`;
    const step = t.recipe.label ? `Step ${t.recipe.n} of ${t.recipe.of}: ${t.recipe.label}. ` : '';
    if (t.held) return step + `Waiting for memory to free up, ${clock(t.heldFor)} so far. It starts by itself when there is room`;
    if (t.over) return step + `The whole recipe is taking longer than usual: ${clock(t.elapsed)} so far, usually about ${clock(t.estimate)}`;
    const rest = t.remaining !== null ? left(t.remaining) : '';
    return step + `Whole recipe: ${clock(t.elapsed)} so far` + (rest ? ', ' + rest : '');
  }
  /* A few words for a small tile. */
  function short(t) {
    if (t.night) return 'Tonight';
    if (t.waiting) return 'Next';
    if (t.held) return 'Needs memory';
    if (t.loading && (!t.loadKnown || t.loadOver)) return 'Loading';
    if (t.recipe) return `Step ${t.recipe.n} of ${t.recipe.of}`;
    if (t.over) return 'Still going';
    if (t.finishing || (t.remaining !== null && t.remaining < 1)) return 'Finishing';
    if (t.remaining === null) return 'Making';
    const f = figure(t.remaining);
    return f.unit === 'min' ? `${f.n} min left` : `${f.n} s left`;
  }

  /* The film strip. Each frame is an equal share of the whole job, so the number of lit frames is the part done and
     two glances a minute apart can be compared: a job of more steps than the strip has frames lights a frame for each
     equal share of them; a job timed only by the clock lights one per share of its usual time. Time alone exposes at
     most nine frames in ten, and a frame once lit is never put out while the same job runs. */
  function strip(size) {
    const G = size === 'large' ? {fw: 40, gap: 6, edge: 15, hole: [7, 4.6], rx: 6, show: 9, cap: 40, h: 72}
            : size === 'small' ? {fw: 11, gap: 2, edge: 9, hole: [3, 2], rx: 3, show: 4, cap: 4, h: 40}
            : {fw: 11, gap: 2, edge: 6.5, hole: [2.8, 1.8], rx: 2.5, show: 7, cap: 7, h: 28};  // the small ones never scroll
    const pitch = G.fw + G.gap, pad = G.gap, w = 2 * pad + G.show * pitch - G.gap, fh = G.h - 2 * G.edge;
    const s = root(w, G.h, 'c-strip c-' + size);
    const id = uid(), defs = sv('defs', {}, s);
    const cp = sv('clipPath', {id}, defs);
    const clipRect = sv('rect', {x: 0, y: 0, width: w, height: G.h, rx: G.rx}, cp);
    const sky = sv('linearGradient', {id: id + 'sky', x1: 0, y1: 0, x2: 0, y2: 1}, defs);  // an exposed frame: light sky over darker ground
    sv('stop', {offset: '0', class: 'sky-top'}, sky); sv('stop', {offset: '1', class: 'sky-low'}, sky);
    const baseRect = sv('rect', {class: 'base', x: .5, y: .5, width: w - 1, height: G.h - 1, rx: G.rx}, s);
    s.style.setProperty('--sky', `url(#${id}sky)`);
    const reel = sv('g', {class: 'reel'}, sv('g', {'clip-path': `url(#${id})`}, s));
    let frames = [], lands = [], n = -1;
    const state = {first: true};
    function build(count) {
      n = count; frames = []; lands = []; reel.replaceChildren();
      // The small strips are fixed tiles and fill their window with unexposed film. The large one is cut to the job's
      // own length when that is shorter than the window, so a four step picture is a strip of four frames, not four
      // frames and five empty sprocket slots.
      const len = size === 'large' ? Math.max(count, 3) : Math.max(count, G.show);
      if (size === 'large') {
        const wNow = 2 * pad + Math.min(len, G.show) * pitch - G.gap;
        s.setAttribute('viewBox', `0 0 ${wNow} ${G.h}`); clipRect.setAttribute('width', wNow); baseRect.setAttribute('width', wNow - 1);
        s.style.maxWidth = Math.round(420 * wNow / w) + 'px';
      }
      for (let i = 0; i < len; i++) {
        const x = pad + i * pitch;
        for (const fx of [.22, .78]) for (const y of [G.edge / 2, G.h - G.edge / 2]) {
          sv('rect', {class: 'hole', x: x + G.fw * fx - G.hole[0] / 2, y: y - G.hole[1] / 2, width: G.hole[0], height: G.hole[1], rx: 1}, reel);
        }
        if (i >= count) continue;
        frames.push(sv('rect', {class: 'frame', x, y: G.edge, width: G.fw, height: fh, rx: size === 'large' ? 2.5 : 1.2}, reel));
        const hz = fh * (.5 + ((i * 7) % 5) / 12);  // a horizon at a slightly different height in each frame
        lands.push(sv('rect', {class: 'land', x: x + 1, y: G.edge + hz, width: G.fw - 2, height: fh - hz - 1, rx: 1}, reel));
      }
    }
    let shown = 0, owner = null;
    function count(t) {
      if (t.steps && t.total >= 3) return Math.min(G.show, t.total);  // one or two steps say too little: those are timed
      // a picture's steps are known before the engine reports the first one, so every page draws the same strip for it,
      // whenever it started watching
      if (t.planned >= 3) return Math.min(G.show, t.planned);
      if (n > 0 && owner === t.id) return n;  // the same job keeps the strip it started with
      if (!t.estimate) return G.show;
      return Math.max(Math.min(6, G.show), Math.min(G.show, Math.round(t.estimate / 8)));
    }
    function update(t) {
      if (owner !== t.id) { owner = t.id; shown = 0; n = -1; }
      const c = count(t);
      if (c !== n) build(c);
      // While the engine finishes after its last step, the last frame stays the one being exposed rather than lit.
      let exposed = t.waiting ? 0 : t.steps && c === t.total ? Math.min(t.finishing ? t.step - 1 : t.step, c) : Math.floor(t.dial * c + 1e-9);
      exposed = t.waiting ? 0 : Math.max(exposed, shown); shown = exposed;
      const now = t.finishing && t.steps && c === t.total ? exposed : exposed - 1;
      frames.forEach((f, i) => { f.classList.toggle('lit', i < exposed); f.classList.toggle('now', i === now); });
      lands.forEach((l, i) => l.classList.toggle('lit', i < exposed));
      place(reel, 'translateX(0px)', state);
      s.classList.toggle('over', t.over); s.classList.toggle('waiting', t.waiting);
    }
    return {el: s, update};
  }

  /* The film leader. The hand sweeps real seconds and the wedge fills behind it once a minute, as on a leader;
     the number in the centre is the minutes left; the coloured rim is drawn only from steps the engine reports. */
  function leader(size) {
    const s = root(200, 200, 'c-leader c-' + size);
    const C = 2 * Math.PI * 97;
    sv('circle', {class: 'face', cx: 100, cy: 100, r: 97}, s);
    sv('path', {class: 'cross', d: 'M100 3V197M3 100H197'}, s);
    sv('circle', {class: 'ring', cx: 100, cy: 100, r: 74}, s);
    const wedge = sv('path', {class: 'wedge'}, s);
    const hand = sv('line', {class: 'hand', x1: 0, y1: 0, x2: 0, y2: -95}, sv('g', {transform: 'translate(100 100)'}, s));
    sv('circle', {class: 'plate', cx: 100, cy: 100, r: 54}, s);
    const arc = sv('circle', {class: 'arc off', cx: 100, cy: 100, r: 97, 'stroke-dasharray': C.toFixed(1), 'stroke-dashoffset': C.toFixed(1), transform: 'rotate(-90 100 100)'}, s);
    const num = sv('text', {class: 'num', x: 100, y: 114}, s);
    const cap = sv('text', {class: 'cap', x: 100, y: 133}, s);
    const state = {first: true};
    function centre(t) {
      if (t.waiting) return [String(t.position), 'in line'];
      if (t.over) return ['+' + clock(t.elapsed - t.estimate), 'over'];
      if (t.remaining === null || t.remaining <= 0) return [clock(t.elapsed), 'so far'];
      const f = figure(t.remaining);
      return [String(f.n), f.unit === 'min' ? (f.n === 1 ? 'minute left' : 'minutes left') : (f.n === 1 ? 'second left' : 'seconds left')];
    }
    function update(t) {
      const sec = t.waiting ? 0 : t.elapsed % 60, a = sec / 60 * 2 * Math.PI;
      wedge.setAttribute('d', sec < .5 ? '' : `M100 100L100 26A74 74 0 ${a > Math.PI ? 1 : 0} 1 ${(100 + 74 * Math.sin(a)).toFixed(2)} ${(100 - 74 * Math.cos(a)).toFixed(2)}Z`);
      place(hand, `rotate(${t.waiting ? 0 : t.elapsed * 6}deg)`, state);
      arc.classList.toggle('off', !t.steps || t.waiting);
      arc.setAttribute('stroke-dashoffset', (C * (1 - t.dial)).toFixed(1));  // the rim closes only when the engine says done
      const [big, small] = centre(t);
      num.textContent = big; cap.textContent = small;
      num.classList.toggle('long', big.length > 3);
      s.classList.toggle('over', t.over); s.classList.toggle('waiting', t.waiting);
    }
    return {el: s, update};
  }

  /* The record. The disc turns while the work is on; the tonearm comes down at the outer groove and travels in
     toward the label with the job, and stops short of it when only time, not steps, says where the job is. */
  function vinyl(size) {
    const s = root(240, 212, 'c-vinyl c-' + size);
    const disc = sv('g', {class: 'disc'}, sv('g', {transform: 'translate(100 112)'}, s));
    sv('circle', {class: 'platter', cx: 0, cy: 0, r: 90}, disc);
    for (const r of [84, 79, 74, 69, 64, 59, 54, 49, 44, 39]) sv('circle', {class: 'groove', cx: 0, cy: 0, r}, disc);
    sv('path', {class: 'shine', d: 'M0 0L-30 -84A89 89 0 0 1 22 -86Z'}, disc);
    sv('path', {class: 'shine', d: 'M0 0L30 84A89 89 0 0 1 -22 86Z'}, disc);
    sv('circle', {class: 'label', cx: 0, cy: 0, r: 30}, disc);
    sv('circle', {class: 'label-ring', cx: 0, cy: 0, r: 22}, disc);
    sv('path', {class: 'mark', d: 'M0 -27v8'}, disc);
    sv('circle', {class: 'spindle', cx: 0, cy: 0, r: 3.2}, disc);
    sv('circle', {class: 'pivot-base', cx: 205, cy: 40, r: 15}, s);
    const arm = sv('g', {class: 'arm'}, sv('g', {transform: 'translate(205 40)'}, s));
    sv('line', {class: 'arm-weight', x1: -24, y1: 0, x2: 0, y2: 0}, arm);
    sv('circle', {class: 'weight', cx: -25, cy: 0, r: 7.5}, arm);
    sv('path', {class: 'arm-tube', d: 'M0 0H84Q94 0 101 -3L110 -6'}, arm);  // a straight tube with the usual bend at the headshell
    sv('rect', {class: 'head', x: 102, y: -9, width: 20, height: 9, rx: 2, transform: 'rotate(-18 110 -5)'}, arm);
    sv('line', {class: 'stylus', x1: 116, y1: -3, x2: 118, y2: 0}, arm);
    sv('circle', {class: 'pivot', cx: 0, cy: 0, r: 5}, arm);
    const L = 118, PC = Math.hypot(105, 72), base = Math.atan2(72, -105) * 180 / Math.PI;
    const state = {first: true};
    function angle(dial) {  // where the needle meets a groove at this radius, by the law of cosines
      const rn = 86 - dial * 52;
      const th = Math.acos(Math.max(-1, Math.min(1, (L * L + PC * PC - rn * rn) / (2 * L * PC)))) * 180 / Math.PI;
      return base - th;
    }
    function update(t) {
      disc.classList.toggle('turning', !t.waiting);
      place(arm, `rotate(${(t.waiting ? 92 : angle(t.dial)).toFixed(2)}deg)`, state);
      s.classList.toggle('over', t.over); s.classList.toggle('waiting', t.waiting);
    }
    return {el: s, update};
  }

  /* The recording. The lamp is lit while the voice is being made; the waveform is this job's own shape, drawn in
     as the playhead passes it. */
  function onair(size) {
    const G = size === 'large' ? {w: 360, h: 112, bars: 72, bw: 3, lamp: [96, 30], top: 44, fs: 13}
            : size === 'small' ? {w: 56, h: 40, bars: 14, bw: 2.4, lamp: [30, 10], top: 15, fs: 5}
            : {w: 100, h: 28, bars: 25, bw: 2.4, lamp: [34, 10], top: 13, fs: 5.5};
    const s = root(G.w, G.h, 'c-onair c-' + size);
    const id = uid();
    sv('feGaussianBlur', {stdDeviation: size === 'large' ? 7 : 2}, sv('filter', {id, x: '-50%', y: '-50%', width: '200%', height: '200%'}, sv('defs', {}, s)));
    const lamp = sv('g', {class: 'lamp'}, s);
    sv('rect', {class: 'lamp-glow', x: 0, y: 0, width: G.lamp[0], height: G.lamp[1], rx: G.lamp[1] / 4, filter: `url(#${id})`}, lamp);
    sv('rect', {class: 'lamp-box', x: .5, y: .5, width: G.lamp[0] - 1, height: G.lamp[1] - 1, rx: G.lamp[1] / 4}, lamp);
    sv('text', {class: 'lamp-text', x: G.lamp[0] / 2, y: G.lamp[1] * .7, 'text-anchor': 'middle', 'font-size': G.fs}, lamp).textContent = 'ON AIR';
    const wave = sv('g', {class: 'wave'}, s);
    const H = G.h - G.top - 2, mid = G.top + H / 2, pitch = G.w / G.bars;
    const bars = [];
    let seeded = null;
    function seedBars(key) {  // the same job always draws the same shape
      seeded = key; let x = 7;
      for (const ch of key) x = (x * 31 + ch.charCodeAt(0)) >>> 0;
      const rnd = () => { x = (x * 1664525 + 1013904223) >>> 0; return x / 4294967296; };
      wave.replaceChildren(); bars.length = 0;
      for (let i = 0; i < G.bars; i++) {
        const env = .3 + .7 * Math.pow(Math.sin(Math.PI * (i + .5) / G.bars), .5);
        const h = Math.max(2, H * env * (.22 + .78 * rnd()));
        bars.push(sv('rect', {class: 'bar', x: i * pitch + (pitch - G.bw) / 2, y: mid - h / 2, width: G.bw, height: h, rx: G.bw / 2}, wave));
      }
    }
    const head = sv('g', {class: 'head'}, s);
    sv('line', {x1: 0, y1: G.top - 1, x2: 0, y2: G.h}, head);
    sv('path', {d: `M-3.5 ${G.top - 5}h7l-3.5 4.5z`}, head);
    const state = {first: true};
    function update(t) {
      if (t.id !== seeded) seedBars(t.id);
      lamp.classList.toggle('on', !t.waiting);
      const x = t.waiting ? 1 : Math.max(1, t.dial * G.w);
      bars.forEach((b, i) => b.classList.toggle('lit', (i + .5) * pitch <= x));
      place(head, `translateX(${x.toFixed(1)}px)`, state);
      s.classList.toggle('over', t.over); s.classList.toggle('waiting', t.waiting);
    }
    return {el: s, update};
  }

  const BUILD = {strip, leader, vinyl, onair};
  /* One indicator for a job of this lane: 'large' for the stage, 'small' for a tile in the strip of recent work,
     'mini' for a row in the line popover. Returns {el, update(t)} where t comes from Craft.read(job). */
  function make(lane, size) {
    const kind = kindFor(lane);
    const c = BUILD[kind](size || 'large');
    c.kind = kind; c.lane = lane; c.el.dataset.kind = kind;
    return c;
  }
  return {make, read, words, recipeWords, short, kindFor, reduced};
})();
