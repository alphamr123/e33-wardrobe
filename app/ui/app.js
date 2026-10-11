/* E33 Wardrobe UI. Plain JS, no framework, no network.
   Talks to the Python backend through call(); the contract is app/API.md. */
(function () {
  'use strict';

  const params = new URLSearchParams(location.search);
  const MOCK = params.has('mock');

  // ------------------------------------------------------------------ helpers
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '`': '&#96;' };
  const esc = v => (v === null || v === undefined ? '' : String(v)).replace(/[&<>"'`]/g, c => ESC[c]);
  const str = v => (v === null || v === undefined ? '' : String(v));
  const arr = v => (Array.isArray(v) ? v : []);
  const num = v => { const n = Number(v); return Number.isFinite(n) ? n : 0; };
  const obj = v => (v && typeof v === 'object' && !Array.isArray(v) ? v : {});
  const plural = (n, one, many) => `${n} ${n === 1 ? one : (many || one + 's')}`;
  const isFail = r => !!(r && typeof r === 'object' && !Array.isArray(r) && r.ok === false);
  const shortVer = v => str(v).split('-')[0];
  const hhmm = t => { const m = /^(\d{1,2}:\d{2})/.exec(str(t)); return m ? m[1] : str(t); };
  const IMG_RE = /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/;

  function swatch(src, cls) {
    return IMG_RE.test(str(src)) ? `<img class="${cls}" src="${src}" alt="">` : `<span class="${cls} noimg"></span>`;
  }
  function fmtSize(n) {
    n = num(n);
    if (n <= 0) return '';
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
    if (n < 1024 * 1024 * 1024) { const m = n / 1048576; return `${m < 10 ? m.toFixed(1) : m.toFixed(0)} MB`; }
    return `${(n / 1073741824).toFixed(2)} GB`;
  }
  function joinList(items) {
    items = arr(items).map(str).filter(Boolean);
    if (items.length <= 1) return items.join('');
    return items.slice(0, -1).join(', ') + ' or ' + items[items.length - 1];
  }
  const store = {
    get(k, d) { try { const v = localStorage.getItem('e33.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('e33.' + k, JSON.stringify(v)); } catch (e) { /* storage off */ } },
  };

  // ------------------------------------------------------------------ bridge
  // pywebview (window.pywebview.api, after `pywebviewready`), else the dev/test HTTP bridge
  // (POST /api/<method> with a JSON array), else mock.js when the URL has ?mock.
  let bridge = null;
  const pyReady = () => !!(window.pywebview && window.pywebview.api && typeof window.pywebview.api.get_state === 'function');
  function loadMock() {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = 'mock.js';
      s.onload = resolve;
      s.onerror = () => reject(new Error('mock.js not found'));
      document.head.appendChild(s);
    });
  }
  const bridgeReady = new Promise(resolve => {
    const use = kind => { if (!bridge) { bridge = kind; resolve(kind); } };
    if (pyReady()) { use('pywebview'); return; }
    window.addEventListener('pywebviewready', () => use('pywebview'));
    if (MOCK) {
      loadMock().then(() => { if (!pyReady()) use('mock'); }).catch(e => setMsg(e.message, 'error'));
      return;
    }
    if (/^https?:$/.test(location.protocol)) {
      const probe = async () => {
        if (bridge) return;
        if (pyReady()) { use('pywebview'); return; }
        try {
          const r = await fetch('/api/get_state', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '[]' });
          if (r.ok && /json/.test(r.headers.get('Content-Type') || '')) { use('http'); return; }
        } catch (e) { /* not the dev server */ }
        setTimeout(probe, 1000);
      };
      setTimeout(probe, window.pywebview ? 1500 : 250);
    }
    setTimeout(() => { if (!bridge) setMsg('Waiting for the app backend...', 'error'); }, 4000);
  });

  async function call(method, ...args) {
    await bridgeReady;
    try {
      let res;
      if (bridge === 'pywebview') {
        const api = window.pywebview && window.pywebview.api;
        if (!api || typeof api[method] !== 'function') return { ok: false, error: `The app has no "${method}" command.` };
        res = await api[method](...args);
      } else if (bridge === 'http') {
        const r = await fetch('/api/' + encodeURIComponent(method), {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(args),
        });
        const text = await r.text();
        try { res = text ? JSON.parse(text) : null; } catch (e) { return { ok: false, error: `${method}: HTTP ${r.status}` }; }
      } else {
        res = await window.E33Mock.call(method, args);
      }
      return res === undefined ? null : res;
    } catch (e) {
      return { ok: false, error: `${method}: ${(e && e.message) || e}` };
    }
  }

  // ------------------------------------------------------------------ app state
  const S = {
    tab: 'mods',
    state: null,
    settings: null,
    mods: [],
    details: {},             // mod id -> ModDetails | {error}
    selected: null,
    selRow: 0,
    selOpt: -1,
    jobs: [],
    hiddenJobs: new Set(),   // "Clear finished" (client side: the API has no call for it)
    selJob: null,
    changed: null,
    busy: false,
    monitor: null,
    selProblem: null,
    sort: store.get('sort', { key: 'name', dir: 1 }),
    gameError: null,
    installing: false,
  };
  const modById = id => S.mods.find(m => m.id === id) || null;
  const modByKey = key => S.mods.find(m => str(m.id) === key) || null;   // key: a data-id attribute

  // ------------------------------------------------------------------ status bar messages
  let msgTimer = null;
  function setMsg(text, kind) {
    const el = $('#sb-msg');
    if (!el) return;
    el.className = 'sb sb-msg' + (kind === 'error' ? ' error' : '');
    el.innerHTML = (kind === 'error' ? '<span class="ico small error"></span>' : '') + esc(text);
    el.title = str(text);
    clearTimeout(msgTimer);
    if (text !== 'Ready') msgTimer = setTimeout(() => setMsg('Ready'), kind === 'error' ? 20000 : 6000);
  }
  /** Shows a failed call's error in the status bar. Returns true when `res` is a failure. */
  function showError(res, what) {
    if (res === null || res === undefined) { setMsg(`${what || 'The app'}: no answer.`, 'error'); return true; }
    if (!isFail(res)) return false;
    if (res.error !== 'cancelled') setMsg((what ? what + ': ' : '') + (str(res.error) || 'Something went wrong.'), 'error');
    return true;
  }

  // ------------------------------------------------------------------ tabs
  function selectTab(name) {
    if (!['mods', 'log', 'setup'].includes(name)) return;
    S.tab = name;
    $$('.tab').forEach(t => { const on = t.dataset.tab === name; t.classList.toggle('active', on); t.setAttribute('aria-selected', on); });
    $$('.page').forEach(p => p.classList.toggle('active', p.id === 'page-' + name));
    hideCtx();
    if (name === 'log') {
      if ($('#log-autoscroll').checked) { const v = $('#logview'); v.scrollTop = v.scrollHeight; }
      lastMon = 0;
      tick();
    }
  }

  // ------------------------------------------------------------------ data loading
  async function refreshAll() {
    const [st, mods] = await Promise.all([call('get_state'), call('list_mods')]);
    if (st && !isFail(st) && typeof st === 'object') S.state = st; else showError(st, 'Reading the app state');
    if (Array.isArray(mods)) S.mods = mods.filter(m => m && typeof m === 'object' && m.id !== undefined && m.id !== null);
    else showError(mods, 'Reading the mod list');
    // keep the shown details until the new ones arrive (no flicker), drop the rest
    const keep = S.selected && S.details[S.selected];
    S.details = keep ? { [S.selected]: keep } : {};
    if (S.selected !== null && !modById(S.selected)) { S.selected = null; S.selRow = 0; S.selOpt = -1; }
    renderAll();
    if (S.selected !== null) loadDetails(S.selected);
  }

  async function loadDetails(id) {
    const d = await call('mod_details', id);
    if (S.selected !== id) return;
    if (!d || isFail(d) || typeof d !== 'object') S.details[id] = { error: (d && d.error) || 'Could not read the details.' };
    else S.details[id] = d;
    renderDetails();
  }

  async function loadMonitor() {
    const m = await call('monitor');
    if (m && !isFail(m) && typeof m === 'object') { S.monitor = m; S.monitorError = null; }
    else S.monitorError = (m && m.error) || 'No answer.';
    renderLog();
    renderStatus();
  }

  // ------------------------------------------------------------------ polling
  let pollTimer = null, ticking = false, tickAgain = false, fastUntil = 0, lastMon = 0, pollFailed = false;
  async function tick() {
    if (ticking) { tickAgain = true; return; }
    ticking = true;
    clearTimeout(pollTimer);
    try {
      const p = await call('poll');
      if (p && typeof p === 'object' && !isFail(p)) {
        pollFailed = false;
        S.busy = !!p.busy;
        S.jobs = arr(p.jobs).filter(j => j && typeof j === 'object');
        if (p.changed !== S.changed) {
          const first = S.changed === null;
          S.changed = p.changed;
          if (!first) await refreshAll();
        }
        renderTasks();
      } else if (!pollFailed) {
        pollFailed = true;
        showError(p || { ok: false, error: 'no answer' }, 'Checking tasks');
      }
      const now = Date.now();
      if (now - lastMon >= (S.tab === 'log' ? 1400 : 5000)) { lastMon = now; await loadMonitor(); }
    } finally {
      ticking = false;
    }
    const delay = tickAgain ? 0 : (S.busy || Date.now() < fastUntil) ? 500 : 1500;
    tickAgain = false;
    pollTimer = setTimeout(tick, delay);
  }
  function pollFast(ms) { fastUntil = Date.now() + (ms || 4000); tick(); }

  // ------------------------------------------------------------------ rendering: toolbar
  function renderToolbar() {
    const m = modById(S.selected);
    const can = !!m && m.state !== 'working';
    $$('[data-needs-mod]').forEach(b => { b.disabled = !can; });
    const rb = $('#btn-reinstall');
    if (rb) rb.textContent = m && m.state === 'not_installed' ? 'Install' : 'Reinstall';
  }

  // ------------------------------------------------------------------ rendering: mod list
  const STATES = {
    ready: ['ok', 'Installed'],
    not_installed: ['off', 'Not installed'],
    working: ['run', 'Working'],
    failed: ['bad', 'Failed'],
  };
  const stateInfo = s => STATES[s] || ['off', str(s) || 'Unknown'];

  function dropHint() {
    const f = arr(obj(obj(S.state).tools).formats);
    return `Drop ${f.length ? joinList(f) : 'zip, 7z or rar'} files here, or use Add mods.`;
  }

  function sortedMods() {
    const k = S.sort.key, d = S.sort.dir === -1 ? -1 : 1;
    const val = m => {
      if (k === 'characters' || k === 'replaces') return arr(m[k]).join(', ').toLowerCase();
      if (k === 'options' || k === 'size') return num(m[k]);
      if (k === 'state') return stateInfo(m.state)[1];
      return str(m.name || m.id).toLowerCase();
    };
    return S.mods.slice().sort((a, b) => {
      const x = val(a), y = val(b);
      const c = x < y ? -1 : x > y ? 1 : 0;
      return c * d || str(a.name || a.id).localeCompare(str(b.name || b.id));
    });
  }

  function renderModList() {
    const mods = sortedMods();
    $('#modlist tbody').innerHTML = mods.map(m => {
      const [cls, label] = stateInfo(m.state);
      const name = str(m.name || m.id);
      const chars = arr(m.characters).join(', ');
      const repl = arr(m.replaces).join(', ');
      const notes = num(m.notes);
      const rowCls = [m.id === S.selected ? 'sel' : '', m.state === 'not_installed' ? 'off' : ''].join(' ').trim();
      return `<tr data-id="${esc(m.id)}"${rowCls ? ` class="${rowCls}"` : ''}>`
        + `<td title="${esc(name)}">${esc(name)}</td>`
        + `<td title="${esc(chars)}">${chars ? esc(chars) : '<span class="dim">-</span>'}</td>`
        + `<td title="${esc(repl)}">${repl ? esc(repl) : '<span class="dim">-</span>'}</td>`
        + `<td class="num">${num(m.options) || '<span class="dim">-</span>'}</td>`
        + `<td class="num">${esc(fmtSize(m.size))}</td>`
        + `<td title="${esc(notes ? label + ', ' + plural(notes, 'note') : label)}"><span class="sq ${cls}"></span><span class="st-text">${esc(label)}</span>`
        + `${notes ? `<span class="ico small ${m.note_level === 'warn' ? 'warn' : 'info'} note-ico"></span>` : ''}</td></tr>`;
    }).join('');
    $$('#modlist th[data-sort]').forEach(th => {
      const old = th.querySelector('.arrow');
      if (old) old.remove();
      if (th.dataset.sort === S.sort.key) th.insertAdjacentHTML('beforeend', `<span class="arrow ${S.sort.dir === -1 ? 'down' : 'up'}"></span>`);
    });
    const empty = $('#modlist-empty');
    empty.hidden = mods.length > 0;
    empty.textContent = dropHint();
  }

  function selectMod(id, scroll) {
    if (S.selected !== id) { S.selected = id; S.selRow = 0; S.selOpt = -1; }
    renderModList();
    renderDetails();
    renderToolbar();
    if (id !== null && !S.details[id]) loadDetails(id);
    if (scroll) {
      const tr = $$('#modlist tbody tr').find(r => r.dataset.id === str(id));
      if (tr) tr.scrollIntoView({ block: 'nearest' });
    }
  }

  // ------------------------------------------------------------------ rendering: details
  function rowLabel(row, multi) {
    const label = str(row.label) || str(row.id);
    const ch = str(row.character);
    return multi && ch && !label.toLowerCase().startsWith(ch.toLowerCase()) ? `${ch} · ${label}` : label;
  }

  function renderDetails() {
    const body = $('#details-body');
    const m = modById(S.selected);
    if (!m) {
      body.innerHTML = `<div class="details-empty">${S.mods.length ? 'Select a mod in the list to see its details.' : 'No mods yet. Added mods are listed on the left.'}</div>`;
      renderToolbar();
      return;
    }
    const scrollTop = body.scrollTop;
    const optScroll = ($('#optlist') || {}).scrollTop || 0;
    const d = S.details[m.id];
    const info = d && !d.error ? d : m;
    const [cls, label] = stateInfo(info.state || m.state);
    const rows = d && !d.error ? arr(d.rows) : [];
    const chars = arr(info.characters).join(', ');
    const repl = arr(info.replaces).join(', ');
    const nOpts = num(info.options);
    const nRows = d && !d.error ? rows.length : num(m.rows);
    const skinHas = d && !d.error ? !!obj(d.skin).has : !!m.skin;
    const folder = d && !d.error ? str(d.folder) : '';

    let h = `<div class="d-head"><div class="d-title"><span class="d-name" title="${esc(info.name || m.id)}">${esc(info.name || m.id)}</span>`
      + `<span class="d-state"><span class="sq ${cls}"></span>${esc(label)}</span></div>`
      + `<div class="props">`
      + `<span class="k">Characters</span><span class="v" title="${esc(chars)}">${esc(chars) || '-'}</span>`
      + `<span class="k">Options</span><span class="v">${nOpts}${nRows ? ` in ${plural(nRows, 'row')}` : ''}</span>`
      + `<span class="k">Replaces</span><span class="v wide" title="${esc(repl)}">${esc(repl) || '-'}</span>`
      + `<span class="k">Size</span><span class="v">${esc(fmtSize(info.size || m.size)) || '-'}</span>`
      + `<span class="k">Skin</span><span class="v">${skinHas ? 'Own body textures' : "Game's own"}</span>`
      + (folder ? `<span class="k">Folder</span><span class="v wide selectable" title="${esc(folder)}">${esc(folder)}</span>` : '')
      + `</div></div>`;

    if (!d) {
      h += `<div class="details-empty">Reading details...</div>`;
    } else if (d.error) {
      h += `<div class="error-line"><span class="ico small error"></span><span>${esc(d.error)}</span></div>`;
    } else {
      h += renderRowsGroup(d, rows);
      h += renderSkinGroup(d);
      h += renderNotesGroup(d);
      h += renderOverlapsGroup(d);
    }
    body.innerHTML = h;
    body.scrollTop = scrollTop;
    const ol = $('#optlist');
    if (ol) {
      ol.scrollTop = optScroll;
      const tr = ol.querySelector('tbody tr.sel');
      if (tr && S.revealOpt) {
        const top = tr.offsetTop - ol.querySelector('thead').offsetHeight;
        if (top < ol.scrollTop || tr.offsetTop + tr.offsetHeight > ol.scrollTop + ol.clientHeight) ol.scrollTop = Math.max(0, top - 2 * tr.offsetHeight);
      }
    }
    S.revealOpt = false;
    renderToolbar();
  }

  function renderRowsGroup(d, rows) {
    let h = '<fieldset class="gb"><legend>Menu rows</legend>';
    if (!rows.length) return h + '<div class="empty-line">This mod has no rows in the in-game menu.</div></fieldset>';
    if (S.selRow >= rows.length || S.selRow < 0) S.selRow = 0;
    const multi = new Set(rows.map(r => str(r.character))).size > 1;
    const labels = rows.map(r => rowLabel(r, multi));
    // tabs when they fit on one line (about 6.6 px per character at 12 px, plus padding), else a list
    const avail = Math.max(300, ($('#details-body').clientWidth || 500) - 24);
    const need = labels.reduce((n, l, i) => n + (l.length + String(arr(rows[i].options).length).length + 1) * 6.6 + 20, 0);
    const useTabs = rows.length <= 8 && need <= avail;
    if (useTabs) {
      h += '<div class="minitabs" role="tablist">' + rows.map((r, i) =>
        `<button class="minitab${i === S.selRow ? ' active' : ''}" data-row="${i}" title="${esc(labels[i])}">${esc(labels[i])}<span class="cnt">${arr(r.options).length}</span></button>`
      ).join('') + '</div>';
    } else {
      h += `<div class="rowpick"><label for="row-select">Row:</label><select class="field" id="row-select">`
        + rows.map((r, i) => `<option value="${i}"${i === S.selRow ? ' selected' : ''}>${esc(labels[i])} (${arr(r.options).length})</option>`).join('')
        + `</select><span class="muted">${S.selRow + 1} of ${rows.length}</span></div>`;
    }
    const opts = arr(rows[S.selRow].options);
    if (S.selOpt >= opts.length) S.selOpt = -1;
    h += `<div class="lv${useTabs ? ' with-tabs' : ''}" id="optlist" tabindex="0"><table>`
      + '<colgroup><col class="c-sw"><col class="c-opt"><col class="c-chg"><col class="c-tex"><col class="c-tags"></colgroup>'
      + '<thead><tr><th></th><th>Option</th><th>Changes</th><th>Textures</th><th>Tags</th></tr></thead><tbody>';
    h += opts.map((o, i) => {
      o = obj(o);
      const bad = o.ok === false;
      const notes = arr(o.notes);
      const mark = bad ? '<span class="ico small error" style="margin-right:5px"></span>'
        : notes.length ? '<span class="ico small info" style="margin-right:5px"></span>' : '';
      const tagText = arr(o.tags).join(', ');
      const cls = [i === S.selOpt ? 'sel' : '', bad ? 'off' : ''].join(' ').trim();
      return `<tr data-opt="${i}"${cls ? ` class="${cls}"` : ''}>`
        + `<td class="sw-cell">${swatch(o.swatch, 'sw16')}</td>`
        + `<td title="${esc(o.label)}">${mark}${esc(o.label)}</td>`
        + (bad ? `<td title="${esc(o.error)}"><span class="step-err">Skipped</span></td>`
          : `<td title="${esc(o.changes)}">${esc(o.changes) || '<span class="dim">-</span>'}</td>`)
        + `<td title="${esc(o.textures)}">${esc(o.textures) || '<span class="dim">-</span>'}</td>`
        + `<td title="${esc(tagText)}">${esc(tagText)}</td></tr>`;
    }).join('');
    if (!opts.length) h += '<tr><td></td><td colspan="4" class="muted">No options in this row.</td></tr>';
    h += '</tbody></table></div>';
    h += `<div class="opt-detail" id="opt-detail">${optDetail(opts)}</div>`;
    return h + '</fieldset>';
  }

  function optDetail(opts) {
    const o = S.selOpt >= 0 ? obj(opts[S.selOpt]) : null;
    if (!o) {
      const flagged = opts.filter(x => x && (x.ok === false || arr(x.notes).length)).length;
      return flagged ? `${plural(flagged, 'option has', 'options have')} notes. Select one to read them.` : '';
    }
    const parts = [];
    if (o.ok === false) parts.push(`<div><span class="ico small error"></span><span class="c-bad">Skipped: ${esc(o.error || 'no reason given.')}</span></div>`);
    arr(o.notes).forEach(n => parts.push(`<div><span class="ico small info"></span>${esc(n)}</div>`));
    if (!parts.length) parts.push(`No notes for ${esc(o.label)}.`);
    return parts.join('');
  }

  function renderSkinGroup(d) {
    const sk = obj(d.skin);
    let h = '<fieldset class="gb"><legend>Skin</legend>';
    if (!sk.has) return h + `<div class="empty-line">${esc(sk.text) || "Uses the game's own body textures."}</div></fieldset>`;
    const sw = arr(sk.swatches).slice(0, 6).map(s => swatch(s, 'sw36')).join('');
    return h + `<div class="skin-row">${sw ? `<div class="skin-sw">${sw}</div>` : ''}<div class="skin-text">${esc(sk.text) || 'Brings its own body textures.'}</div></div></fieldset>`;
  }

  function renderNotesGroup(d) {
    const notes = arr(d.notes).map(obj);
    let h = '<fieldset class="gb"><legend>Notes</legend>';
    if (!notes.length) return h + '<div class="empty-line">No notes.</div></fieldset>';
    return h + '<ul class="lines">' + notes.map(n =>
      `<li><span class="ico small ${n.level === 'warn' ? 'warn' : n.level === 'error' ? 'error' : 'info'}"></span><span>${esc(n.text)}</span></li>`
    ).join('') + '</ul></fieldset>';
  }

  function renderOverlapsGroup(d) {
    const ov = arr(d.overlaps).map(obj);
    let h = '<fieldset class="gb"><legend>Overlaps</legend>';
    if (!ov.length) return h + '<div class="empty-line">No overlaps with other mods.</div></fieldset>';
    return h + '<ul class="lines">' + ov.map(o =>
      `<li><span class="ico small info"></span><span><span class="ovl-mod">${esc(o.mod)}</span>: ${esc(o.text)}</span></li>`
    ).join('') + '</ul></fieldset>';
  }

  // ------------------------------------------------------------------ rendering: tasks
  const KIND = { add: 'Add', reinstall: 'Reinstall', remove: 'Remove' };
  const JOB_STATUS = { waiting: ['off', 'Waiting'], working: ['run', 'Working'], done: ['ok', 'Done'], failed: ['bad', 'Failed'] };
  const STEP_WEIGHT = { unpack: 2, sort: 1, install: 7 };
  const STEP_WORD = { done: 'done', run: 'running', todo: 'to do', fail: 'failed' };
  let lastTasksKey = '';

  function jobProgress(j, steps) {
    if (j.status === 'done') return 1;
    if (j.status === 'waiting' || !steps.length) return 0;
    let total = 0, got = 0;
    steps.forEach(s => {
      const w = STEP_WEIGHT[s.key] || 1;
      total += w;
      if (s.state === 'done') got += w;
      else if (s.state === 'run' && typeof s.progress === 'number') got += w * Math.max(0, Math.min(1, s.progress));
    });
    return total ? got / total : 0;
  }

  function jobRow(j) {
    const steps = arr(j.steps).map(obj);
    const [scls, slabel] = JOB_STATUS[j.status] || ['off', str(j.status)];
    const cur = steps.find(s => s.state === 'run' || s.state === 'fail');
    let text = '', tags = [];
    if (j.status === 'waiting') {
      text = '<span class="muted">Waiting</span>';
    } else if (j.status === 'failed') {
      const f = steps.find(s => s.state === 'fail');
      text = `<span class="step-err">${f ? esc(f.label) + ': ' : ''}${esc(j.error || (f && f.detail) || 'Failed.')}</span>`;
    } else if (j.status === 'done') {
      const withTags = steps.find(s => arr(s.tags).length);
      const last = steps.slice().reverse().find(s => s.detail);
      if (withTags) { text = esc(withTags.detail || withTags.label); tags = arr(withTags.tags); }
      else if (last) text = `${esc(last.label)}: ${esc(last.detail)}`;
      else text = steps.length ? esc(steps[steps.length - 1].label) : 'Done';
    } else {
      const s = cur || steps.filter(x => x.state === 'done').pop();
      if (s) {
        text = `${esc(s.label)}${s.detail ? ': ' + esc(s.detail) : ''}`;
        if (s.key === 'sort' || (!cur && arr(s.tags).length)) tags = arr(s.tags);
      } else text = '<span class="muted">Starting</span>';
    }
    const squares = steps.length ? `<span class="steps">${steps.map(s => `<i class="${s.state === 'todo' ? '' : esc(s.state)}"></i>`).join('')}</span>` : '';
    const notes = arr(j.notes).map(str).filter(Boolean);     // not in API.md; the backend sends it
    const tip = steps.map(s => `${str(s.label)}: ${STEP_WORD[s.state] || str(s.state)}${s.detail ? ', ' + str(s.detail) : ''}`).join('\n')
      + (j.error ? `\n${str(j.error)}` : '') + (notes.length ? '\n' + notes.join('\n') : '');
    const frac = jobProgress(j, steps);
    const pcls = j.status === 'done' ? 'done' : j.status === 'failed' ? 'fail' : j.status === 'waiting' ? 'wait'
      : (j.status === 'working' && !steps.length ? 'busy' : '');
    const pct = Math.round(frac * 100);
    return `<tr data-job="${esc(j.id)}"${String(j.id) === String(S.selJob) ? ' class="sel"' : ''}>`
      + `<td title="${esc(j.name)}">${esc(j.name)}</td>`
      + `<td>${esc(KIND[j.kind] || j.kind)}</td>`
      + `<td class="num">${esc(fmtSize(j.size))}</td>`
      + `<td title="${esc(tip)}">${squares}${text}${tags.length ? ' ' + tags.map(t => `<span class="tag">${esc(t)}</span>`).join('') : ''}</td>`
      + `<td class="pbar-cell" title="${pct}%"><span class="pbar ${pcls}"><i style="width:${pct}%"></i></span></td>`
      + `<td${notes.length ? ` title="${esc(notes.join('\n'))}"` : ''}><span class="sq ${scls}"></span>${esc(slabel)}`
      + `${notes.length ? '<span class="ico small info note-ico"></span>' : ''}</td></tr>`;
  }

  function renderTasks() {
    const jobs = S.jobs.filter(j => !S.hiddenJobs.has(String(j.id)));
    const show = jobs.length > 0;
    $('#tasks').hidden = !show;
    $('#tasks-splitter').hidden = !show;
    if (!show) { lastTasksKey = ''; return; }
    const key = JSON.stringify(jobs) + '|' + S.selJob;
    if (key === lastTasksKey) return;
    lastTasksKey = key;
    const count = st => jobs.filter(j => j.status === st).length;
    const fin = count('done') + count('failed');
    const parts = [];
    if (count('working')) parts.push(`${count('working')} working`);
    if (count('waiting')) parts.push(`${count('waiting')} waiting`);
    if (fin) parts.push(`${fin} finished`);
    $('#tasks-count').textContent = parts.length ? '(' + parts.join(', ') + ')' : '';
    $('#btn-clear').disabled = fin === 0;
    $('#tasklist tbody').innerHTML = jobs.map(jobRow).join('');
  }

  async function clearFinished() {
    S.jobs.forEach(j => { if (j.status === 'done' || j.status === 'failed') S.hiddenJobs.add(String(j.id)); });
    renderTasks();
    const res = await call('clear_jobs');
    if (isFail(res)) showError(res, 'Clearing the task list');
  }

  // A bar above the mod list while setup isn't finished (game, UE4SS, in-game menu).
  function renderNotice() {
    const el = $('#mods-notice');
    if (!el) return;
    const st = S.state || {}, g = st.game || {}, u = st.ue4ss || {}, mn = st.menu || {};
    let text = '', act = '', label = '';
    if (!g.found) { text = 'The game folder is not set.'; act = 'goto-setup'; label = 'Setup...'; }
    else if (!u.installed) { text = 'UE4SS is not installed. The in-game menu needs it.'; act = 'goto-setup'; label = 'Setup...'; }
    else if (u.ok === false) { text = 'This UE4SS is too old for the in-game menu.'; act = 'goto-setup'; label = 'Setup...'; }
    else if (!mn.installed) { text = 'The in-game menu is not installed yet.'; act = 'install-menu'; label = 'Install'; }
    else if (mn.update) { text = `The in-game menu is ${str(mn.version)}; this app has ${str(mn.bundled)}.`; act = 'install-menu'; label = 'Update'; }
    el.hidden = !text;
    if (text) el.innerHTML = `<span class="ico small warn"></span><span class="notice-text">${esc(text)}</span>`
      + `<button class="btn small" data-act="${act}">${esc(label)}</button>`;
  }

  // ------------------------------------------------------------------ rendering: setup
  const TREE = [
    'C:\\Program Files (x86)\\Steam\\steamapps\\common\\',
    '  <span class="pick">Expedition 33\\</span>        <span class="here">&lt;- pick this folder</span>',
    '    Sandfall\\',
    '      Content\\',
    '        Paks\\',
  ].join('\n');

  const statusLine = (ico, text, extra) =>
    `<div class="status-line"><span class="ico ${ico}"></span><span>${esc(text)}</span>${extra ? `<span class="muted">${esc(extra)}</span>` : ''}</div>`;
  const kv = rows => '<div class="kv">' + rows.map(([k, v, path]) =>
    `<span class="k">${esc(k)}</span><span class="v${path ? ' path' : ''}" title="${esc(v)}">${esc(v) || '-'}</span>`).join('') + '</div>';
  const errorLine = text => `<div class="error-line"><span class="ico small error"></span><span>${esc(text)}</span></div>`;
  const SOURCE = { detected: 'Detected automatically', saved: 'Saved setting', picked: 'Picked by you' };

  function renderSetup() {
    const st = S.state;
    if (!st) {
      $('#setup-game').innerHTML = statusLine('idle', 'Reading the setup...');
      ['#setup-ue4ss', '#setup-menu', '#setup-library', '#setup-tools', '#setup-app'].forEach(s => { $(s).innerHTML = ''; });
      return;
    }
    const g = obj(st.game), u = obj(st.ue4ss), mn = obj(st.menu), tools = obj(st.tools);

    // Game
    let h = '';
    if (g.found) {
      h += statusLine('ok', g.store ? `Found (${g.store})` : 'Found');
      h += kv([['Folder', str(g.root), true], ['Paks', str(g.paks), true], ['Store', str(g.store) || 'Unknown'], ['Found by', SOURCE[g.source] || str(g.source)]]);
    } else {
      h += statusLine('error', 'The game folder was not found.');
      h += '<p class="para">Pick the folder the game is installed in. For example:</p>';
      h += `<div class="tree sunken">${TREE}</div>`;
      h += '<p class="para muted">Picking Sandfall or Paks inside it also works.</p>';
    }
    if (S.gameError) h += errorLine(S.gameError);
    h += '<div class="btnrow"><button class="btn" data-act="pick-game">Browse...</button>'
      + '<button class="btn" data-act="detect-game">Detect again</button>'
      + (g.found ? '<button class="btn" data-act="open-game">Open</button>' : '') + '</div>';
    $('#setup-game').innerHTML = h;

    // UE4SS
    h = '';
    if (!g.found) {
      h += statusLine('idle', 'Set the game folder first.');
    } else if (u.installed && u.ok !== false) {
      h += statusLine('ok', 'Installed');
      h += kv([['Version', u.version ? str(u.version) : 'Not known yet (start the game once)']]);
    } else {
      if (u.installed) {
        h += statusLine('warn', 'Installed, but it does not work with the menu');
        h += kv([['Version', str(u.version) || 'Unknown']]);
        h += `<p class="para">${esc(u.problem || "This UE4SS build can't run the in-game menu.")}</p>`;
      } else {
        h += statusLine('error', 'Not installed');
        h += '<p class="para">The in-game menu runs on UE4SS. Get the file "UE4SS - Experimental (Newer)" from its Nexus page and install it as the page describes.</p>';
      }
      h += '<div class="btnrow"><button class="btn" data-act="ue4ss-page">Open UE4SS page</button>'
        + '<button class="btn" data-act="check-again">Check again</button></div>';
    }
    $('#setup-ue4ss').innerHTML = h;

    // In-game menu
    h = '';
    const busy = S.installing ? ' disabled' : '';
    if (!g.found) {
      h += statusLine('idle', 'Set the game folder first.');
      h += kv([['In this app', str(mn.bundled) || '-']]);
    } else {
      if (!mn.installed) h += statusLine('warn', 'Not installed');
      else if (mn.update) h += statusLine('warn', 'Update available');
      else h += statusLine('ok', 'Installed, up to date');
      h += kv([['Installed', mn.installed ? (str(mn.version) || 'Unknown version') : 'No'], ['In this app', str(mn.bundled) || '-']]);
      if (!mn.installed) h += '<p class="para muted">In game, load a save and press Delete to open it.</p>';
      if (u.ok === false || !u.installed) h += '<p class="para muted">It starts once UE4SS works.</p>';
      const label = S.installing ? 'Installing...' : !mn.installed ? 'Install' : mn.update ? 'Update' : 'Reinstall';
      h += `<div class="btnrow"><button class="btn${!mn.installed || mn.update ? ' default' : ''}" data-act="install-menu"${busy}>${label}</button>`
        + (mn.installed ? '<button class="btn" data-act="open-menu">Open folder</button>' : '') + '</div>';
    }
    $('#setup-menu').innerHTML = h;

    // Mod library
    h = '';
    if (st.library) {
      h += kv([['Folder', str(st.library), true], ['Mods', String(S.mods.length)]]);
      h += '<div class="btnrow"><button class="btn" data-act="pick-library">Change...</button>'
        + '<button class="btn" data-act="open-library">Open</button></div>';
    } else {
      h += statusLine('idle', 'Set the game folder first.');
    }
    $('#setup-library').innerHTML = h;

    // Tools
    const formats = arr(tools.formats);
    h = kv([
      ['Archives', formats.length ? formats.join(', ') : 'None'],
      ['retoc', tools.retoc ? 'Found' : 'Missing'],
    ]);
    if (!tools.retoc) h += errorLine("retoc is missing, so mods can't be prepared for the menu. Reinstall the app.");
    $('#setup-tools').innerHTML = h;

    // App
    const watch = S.settings && typeof S.settings === 'object' ? S.settings.watch_game !== false : true;
    h = kv([['Version', str(st.version) || '-']]);
    h += `<label class="check"><input type="checkbox" id="opt-watch"${watch ? ' checked' : ''}> Follow the game's logs while it runs</label>`;
    h += '<div class="btnrow"><button class="btn" data-act="link" data-link="guide">User guide</button>'
      + '<button class="btn" data-act="link" data-link="nexus">Nexus page</button>'
      + '<button class="btn" data-act="link" data-link="github">GitHub</button></div>';
    $('#setup-app').innerHTML = h;
  }

  // ------------------------------------------------------------------ rendering: game log
  const SEV = { error: 'error', warn: 'warn', info: 'info' };
  let lastTailKey = '', lastLogKey = '';

  function renderLog() {
    const m = S.monitor;
    const probs = arr(m && m.problems).map(obj);
    if (probs.length && !probs.some(p => str(p.key) === S.selProblem)) S.selProblem = str(probs[0].key);
    if (!probs.length) S.selProblem = null;
    // the monitor is polled every 1.4 s: rebuild the lists only when something changed
    const key = JSON.stringify([m ? Object.assign({}, m, { tail: null }) : null, S.selProblem, S.monitorError]);
    if (key !== lastLogKey) { lastLogKey = key; renderLogLists(m, probs); }
    renderTail();
  }

  function renderLogLists(m, probs) {
    const ico = $('#log-ico'), txt = $('#log-status');
    let icon = 'idle', line;
    if (!m) line = S.monitorError ? `Can't read the game's logs: ${S.monitorError}` : "Reading the game's logs...";
    else if (m.watching === false) line = "Not following the game's logs. Switch it on in Setup.";
    else if (m.game_running) {
      icon = 'ok';
      const parts = [m.since ? `Game running since ${hhmm(m.since)}` : 'Game running'];
      parts.push(m.menu_active ? 'menu active' : 'menu not started yet');
      if (m.last_activity) parts.push(`last activity ${m.last_activity}`);
      line = parts.join(' · ');
    } else line = 'Game not running. Start it and this tab follows the logs.';
    ico.className = 'ico ' + icon;
    txt.textContent = line;
    txt.title = line;

    // problems
    $('#problemlist tbody').innerHTML = probs.map(p =>
      `<tr data-key="${esc(p.key)}"${str(p.key) === S.selProblem ? ' class="sel"' : ''}>`
      + `<td class="ico-cell"><span class="ico small ${SEV[p.level] || 'info'}"></span></td>`
      + `<td>${esc(p.last || p.first)}</td>`
      + `<td title="${esc(p.title)}">${esc(p.title)}</td>`
      + `<td class="num">${num(p.count) || 1}</td></tr>`
    ).join('');
    $('#problems-empty').hidden = probs.length > 0;
    const sel = probs.find(p => str(p.key) === S.selProblem);
    const pd = $('#problem-detail');
    if (sel) {
      const cnt = num(sel.count) || 1;
      const when = sel.first && sel.last && sel.first !== sel.last ? `${sel.first} to ${sel.last}` : `${sel.first || sel.last || ''}`;
      pd.innerHTML = `<div class="pd-head"><span class="pd-title">${esc(sel.title)}</span>`
        + `<span class="pd-when">${esc(when)}${cnt > 1 ? `, ${cnt} times` : ''}</span></div>`
        + (sel.detail ? `<div>${esc(sel.detail)}</div>` : '')
        + (sel.hint ? `<div class="pd-hint"><span class="muted">What to do:</span> ${esc(sel.hint)}</div>` : '');
      pd.classList.add('selectable');
    } else {
      pd.innerHTML = `<span class="muted">${m && m.game_running ? 'Problems the logs show are listed above.' : 'Problems the logs show while the game runs are listed above.'}</span>`;
      pd.classList.remove('selectable');
    }
    // badge on the tab
    const serious = probs.filter(p => p.level === 'error' || p.level === 'warn');
    const tab = $('.tab[data-tab="log"]');
    tab.innerHTML = 'Game log' + (serious.length ? `<span class="badge${probs.some(p => p.level === 'error') ? ' bad' : ''}">${serious.length}</span>` : '');

    // on screen
    const on = arr(m && m.on_screen).map(obj);
    $('#onscreenlist tbody').innerHTML = on.map(o => {
      const shown = num(o.shown), total = num(o.total);
      const cls = total && shown >= total ? '' : shown === 0 ? 'c-bad' : 'c-warn';
      return `<tr><td title="${esc(o.slot)}">${esc(o.slot)}</td><td title="${esc(o.variant)}">${esc(o.variant)}</td>`
        + `<td class="num"><span class="${cls}">${shown}/${total}</span></td><td>${o.worn ? 'Yes' : '<span class="dim">No</span>'}</td></tr>`;
    }).join('');
    $('#onscreen-empty').hidden = on.length > 0;
    $('#onscreen-empty').textContent = m && m.game_running ? 'Nothing from your mods on screen.' : 'Shown while the game runs.';
  }

  function renderTail() {
    const m = S.monitor;
    const lines = arr(m && m.tail).map(str);
    const filter = $('#log-filter').value.trim().toLowerCase();
    const key = lines.length + '|' + (lines[lines.length - 1] || '') + '|' + lines[0] + '|' + filter;
    if (key === lastTailKey) return;
    lastTailKey = key;
    const shown = filter ? lines.filter(l => l.toLowerCase().includes(filter)) : lines;
    const view = $('#logview');
    if (!lines.length) {
      view.innerHTML = `<span class="l-empty">${m && m.game_running ? 'No log lines yet.' : 'The session log shows here while the game runs.'}</span>`;
    } else if (!shown.length) {
      view.innerHTML = '<span class="l-empty">No lines match the filter.</span>';
    } else {
      view.innerHTML = shown.map(l => {
        const c = /watchdog|error|fail|crash/i.test(l) ? 'l-bad' : /warn|skipp|hidden|not visible|made for/i.test(l) ? 'l-warn' : '';
        return c ? `<span class="${c}">${esc(l)}</span>` : esc(l);
      }).join('\n');
    }
    $('#log-count').textContent = lines.length ? (filter ? `${shown.length} of ${plural(lines.length, 'line')}` : plural(lines.length, 'line')) : '';
    if ($('#log-autoscroll').checked) view.scrollTop = view.scrollHeight;
  }

  // ------------------------------------------------------------------ rendering: status bar
  function setSb(sel, text, cls, tip) {
    const el = $(sel);
    el.textContent = text;
    el.className = 'sb' + (cls ? ' ' + cls : '');
    el.title = tip || text;
    el.hidden = !text;
  }

  function renderStatus() {
    const st = S.state;
    if (!st) { ['#sb-game', '#sb-ue4ss', '#sb-menu', '#sb-mods', '#sb-running'].forEach(s => setSb(s, '')); return; }
    const g = obj(st.game), u = obj(st.ue4ss), mn = obj(st.menu);
    setSb('#sb-game', g.found ? `Game: ${g.store || 'found'}` : 'Game: not found', g.found ? '' : 'warn', g.found ? str(g.root) : 'Set the game folder in Setup');
    if (!g.found) setSb('#sb-ue4ss', 'UE4SS: -', '');
    else if (!u.installed) setSb('#sb-ue4ss', 'UE4SS: missing', 'bad');
    else if (u.ok === false) setSb('#sb-ue4ss', `UE4SS ${shortVer(u.version)} (too old)`.replace('  ', ' '), 'warn', str(u.problem));
    else setSb('#sb-ue4ss', u.version ? `UE4SS ${shortVer(u.version)}` : 'UE4SS', '', str(u.version));
    if (!g.found) setSb('#sb-menu', 'Menu: -', '');
    else if (!mn.installed) setSb('#sb-menu', 'Menu: not installed', 'warn');
    else setSb('#sb-menu', `Menu ${str(mn.version)}${mn.update ? ' (update)' : ''}`, mn.update ? 'warn' : '', mn.update ? `Version ${str(mn.bundled)} is in this app` : '');
    setSb('#sb-mods', plural(S.mods.length, 'mod'));
    const running = S.monitor ? !!S.monitor.game_running : !!st.game_running;
    setSb('#sb-running', running ? 'Game running' : 'Game not running');
  }

  function renderAll() {
    renderToolbar();
    renderNotice();
    renderModList();
    renderDetails();
    renderTasks();
    renderSetup();
    renderLog();
    renderStatus();
  }

  // ------------------------------------------------------------------ dialogs
  let modal = null;
  /** A small classic modal. buttons: [{label, value, default, cancel}]. Resolves {value, form}. */
  function dialog({ title, icon, html, buttons }) {
    if (modal) modal.finish(null);
    hideCtx();
    return new Promise(resolve => {
      const layer = $('#modal-layer');
      const prevFocus = document.activeElement;
      layer.innerHTML = `<div class="dlg" role="dialog" aria-modal="true" aria-label="${esc(title)}">`
        + `<div class="dlg-title"><span>${esc(title)}</span><button class="dlg-x" data-close title="Close" aria-label="Close"></button></div>`
        + `<div class="dlg-body">${icon ? `<span class="ico ${icon}"></span>` : ''}<div class="dlg-msg">${html}</div></div>`
        + `<div class="dlg-buttons">${buttons.map((b, i) => `<button class="btn${b.default ? ' default' : ''}" data-i="${i}">${esc(b.label)}</button>`).join('')}</div></div>`;
      layer.hidden = false;
      const finish = b => {
        const form = {};
        $$('input', layer).forEach(inp => {
          if (inp.type === 'radio') { if (inp.checked) form[inp.name] = inp.value; }
          else if (inp.type === 'checkbox') form[inp.name || inp.id] = inp.checked;
          else form[inp.name || inp.id] = inp.value;
        });
        layer.hidden = true;
        layer.innerHTML = '';
        layer.onclick = null;
        modal = null;
        if (prevFocus && prevFocus.focus) prevFocus.focus();
        resolve({ value: b ? b.value : null, form });
      };
      const cancelBtn = buttons.find(b => b.cancel) || null;
      const defBtn = buttons.find(b => b.default) || buttons[0];
      modal = { finish, cancel: () => finish(cancelBtn), accept: () => finish(defBtn) };
      layer.onclick = e => {
        const link = e.target.closest('[data-link]');
        if (link) { openUrl(link.dataset.link); return; }
        if (e.target.closest('[data-close]')) { modal.cancel(); return; }
        const t = e.target.closest('[data-i]');
        if (t) finish(buttons[+t.dataset.i]);
      };
      const def = layer.querySelector('.btn.default') || layer.querySelector('.dlg-buttons .btn');
      if (def) def.focus();
    });
  }

  async function askRemove(id) {
    const m = modById(id);
    if (!m || m.state === 'working') return;
    const r = await dialog({
      title: 'Remove mod',
      icon: 'warn',
      html: `<p>Remove <span class="dlg-name">${esc(m.name || m.id)}</span>?</p>`
        + '<div class="choices">'
        + '<label class="radio"><input type="radio" name="how" value="game" checked><span>Remove from the game only<br><span class="sub">The files stay in the library; Install puts it back.</span></span></label>'
        + '<label class="radio"><input type="radio" name="how" value="delete"><span>Also delete its files<br><span class="sub">Deletes the mod\'s folder in the library.</span></span></label>'
        + '</div>',
      buttons: [{ label: 'Remove', value: 'ok', default: true }, { label: 'Cancel', value: null, cancel: true }],
    });
    if (r.value !== 'ok') return;
    const res = await call('remove_mod', id, r.form.how === 'delete');
    if (showError(res, 'Remove')) return;
    setMsg(`Removing ${m.name || m.id}...`);
    pollFast();
  }

  async function reinstall(id) {
    const m = modById(id);
    if (!m || m.state === 'working') return;
    const res = await call('reinstall_mod', id);
    if (showError(res, m.state === 'not_installed' ? 'Install' : 'Reinstall')) return;
    setMsg(`${m.state === 'not_installed' ? 'Installing' : 'Reinstalling'} ${m.name || m.id}...`);
    pollFast();
  }

  function showHelp() {
    const v = str(obj(S.state).version);
    dialog({
      title: 'About E33 Wardrobe',
      icon: 'info',
      html: `<p><b>E33 Wardrobe${v ? ' ' + esc(v) : ''}</b></p>`
        + '<p>Add outfit mods here: drop archives on the window or use Add mods. Each mod gets rows in the in-game menu. In game, load a save and press Delete to open the menu.</p>'
        + '<p class="sub">Setup checks the game folder, UE4SS and the menu. Game log shows what the menu did while you play. Keys: F5 refreshes, Delete removes the selected mod.</p>'
        + '<div class="help-links"><button class="btn" data-link="guide">User guide</button><button class="btn" data-link="nexus">Nexus page</button><button class="btn" data-link="github">GitHub</button></div>',
      buttons: [{ label: 'Close', value: null, default: true, cancel: true }],
    });
  }

  // ------------------------------------------------------------------ actions
  async function afterAdd(res, what) {
    if (showError(res, what)) return res;
    const n = arr(res && res.jobs).length;
    setMsg(n ? `Added ${plural(n, 'task')} to the list.` : 'Nothing new to add.');
    if (S.tab !== 'mods') selectTab('mods');
    pollFast();
    return res;
  }
  async function addPaths(paths) {
    paths = arr(paths).map(str).filter(Boolean);
    if (!paths.length) return { ok: false, error: 'No paths.' };
    return afterAdd(await call('add_paths', paths), 'Add');
  }
  async function openPath(what) { showError(await call('open_path', what), 'Open'); }
  async function openUrl(name) { showError(await call('open_url', name), 'Open page'); }

  async function gameResult(res, okMsg) {
    if (res && res.state && typeof res.state === 'object') S.state = res.state;
    if (isFail(res)) { if (res.error !== 'cancelled') { S.gameError = str(res.error) || 'Something went wrong.'; setMsg(S.gameError, 'error'); } }
    else if (res) { S.gameError = null; setMsg(okMsg); }
    else showError(res, 'Game folder');
    await refreshAll();
  }

  async function installMenu() {
    if (S.installing) return;
    const mn = obj(obj(S.state).menu);
    S.installing = true;
    renderSetup();
    const res = await call('install_menu');
    S.installing = false;
    if (res && res.state && typeof res.state === 'object') S.state = res.state;
    if (!showError(res, 'In-game menu')) setMsg(mn.installed ? (mn.update ? 'In-game menu updated.' : 'In-game menu installed again.') : 'In-game menu installed.');
    renderAll();
  }

  async function checkAgain() {
    const st = await call('get_state');
    if (showError(st, 'Check')) return;
    S.state = st;
    const u = obj(st.ue4ss);
    setMsg(u.installed && u.ok !== false ? 'UE4SS works.' : u.installed ? 'UE4SS is still too old.' : 'UE4SS is still not found.');
    renderAll();
  }

  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back */ }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:0';
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    return ok;
  }

  async function copyProblems() {
    const t = await call('problems_text');
    if (typeof t !== 'string') { showError(t || { ok: false, error: 'no answer' }, 'Copy problems'); return; }
    if (!t.trim()) { setMsg('No problems to copy.'); return; }
    setMsg(await copyText(t) ? 'Problems copied to the clipboard.' : "Couldn't use the clipboard.", 'info');
  }

  async function saveWatch(on) {
    const s = Object.assign({}, obj(S.settings), { watch_game: !!on });
    const res = await call('save_settings', s);
    if (showError(res, 'Settings')) { renderSetup(); return; }
    S.settings = res && typeof res === 'object' && 'watch_game' in res ? res : s;
    lastMon = 0;
    tick();
  }

  async function refreshNow() {
    setMsg('Refreshing...');
    lastTasksKey = lastTailKey = lastLogKey = '';
    await refreshAll();
    await loadMonitor();
    setMsg('Ready');
  }

  const ACTIONS = {
    'add-files': async () => afterAdd(await call('pick_files'), 'Add mods'),
    'add-folder': async () => afterAdd(await call('pick_folder'), 'Add folder'),
    'reinstall': () => { if (S.selected !== null) reinstall(S.selected); },
    'remove': () => { if (S.selected !== null) askRemove(S.selected); },
    'open-library': () => openPath('library'),
    'pick-library': async () => {
      const res = await call('pick_library_folder');
      if (isFail(res)) { if (res.error !== 'cancelled') showError(res, 'Changing the library folder'); return; }
      await refreshAll();
      setMsg('Library folder changed.');
    },
    'goto-setup': () => selectTab('setup'),
    'open-mod': () => { if (S.selected !== null) openPath(S.selected); },
    'help': showHelp,
    'clear-finished': clearFinished,
    'copy-problems': copyProblems,
    'open-report': () => openPath('report'),
    'open-logs': () => openPath('menu'),
    'pick-game': async () => gameResult(await call('pick_game_folder'), 'Game folder set.'),
    'detect-game': async () => gameResult(await call('detect_game'), 'Game found.'),
    'open-game': () => openPath('game'),
    'ue4ss-page': () => openUrl('ue4ss'),
    'check-again': checkAgain,
    'install-menu': installMenu,
    'open-menu': () => openPath('menu'),
    'link': el => openUrl(el.dataset.link),
  };

  // ------------------------------------------------------------------ context menu
  function showCtx(x, y, items) {
    const menu = $('#ctxmenu');
    menu.innerHTML = items.map((it, i) => it === '-' ? '<div class="ms"></div>'
      : `<button class="mi" data-ci="${i}"${it.disabled ? ' disabled' : ''}>${esc(it.label)}</button>`).join('');
    menu.hidden = false;
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, innerWidth - r.width - 4) + 'px';
    menu.style.top = Math.min(y, innerHeight - r.height - 4) + 'px';
    menu.onclick = e => {
      const b = e.target.closest('[data-ci]');
      if (!b || b.disabled) return;
      hideCtx();
      items[+b.dataset.ci].run();
    };
  }
  function hideCtx() { const m = $('#ctxmenu'); if (m) m.hidden = true; }

  // ------------------------------------------------------------------ splitters
  function makeSplitter(handle, target, axis, key, min, maxFn) {
    const saved = store.get(key, null);
    if (saved) target.style[axis === 'x' ? 'width' : 'height'] = saved + 'px';
    handle.addEventListener('mousedown', e => {
      e.preventDefault();
      const start = axis === 'x' ? e.clientX : e.clientY;
      const size0 = axis === 'x' ? target.offsetWidth : target.offsetHeight;
      const move = ev => {
        const d = (axis === 'x' ? ev.clientX : ev.clientY) - start;
        const v = Math.max(min, Math.min(maxFn(), axis === 'x' ? size0 + d : size0 - d));
        target.style[axis === 'x' ? 'width' : 'height'] = v + 'px';
      };
      const up = () => {
        removeEventListener('mousemove', move);
        removeEventListener('mouseup', up);
        store.set(key, axis === 'x' ? target.offsetWidth : target.offsetHeight);
      };
      addEventListener('mousemove', move);
      addEventListener('mouseup', up);
    });
  }

  // ------------------------------------------------------------------ list keyboard navigation
  function moveIn(listSel, delta, pick) {
    const rows = $$(listSel + ' tbody tr').filter(r => r.dataset.id !== undefined || r.dataset.key !== undefined || r.dataset.opt !== undefined);
    if (!rows.length) return;
    let i = rows.findIndex(r => r.classList.contains('sel'));
    i = delta === Infinity ? rows.length - 1 : delta === -Infinity ? 0 : Math.max(0, Math.min(rows.length - 1, (i < 0 ? (delta > 0 ? -1 : rows.length) : i) + delta));
    pick(rows[i]);
    const r = $$(listSel + ' tbody tr')[rows.indexOf(rows[i])];
    if (r) r.scrollIntoView({ block: 'nearest' });
  }

  // ------------------------------------------------------------------ events
  function bind() {
    document.addEventListener('click', e => {
      if (!e.target.closest('#ctxmenu')) hideCtx();
      if (modal) return;
      const actEl = e.target.closest('[data-act]');
      if (actEl && !actEl.disabled) { const fn = ACTIONS[actEl.dataset.act]; if (fn) fn(actEl); return; }
      const tab = e.target.closest('.tab');
      if (tab) { selectTab(tab.dataset.tab); return; }
      const th = e.target.closest('#modlist th[data-sort]');
      if (th) {
        const k = th.dataset.sort;
        S.sort = S.sort.key === k ? { key: k, dir: -S.sort.dir } : { key: k, dir: 1 };
        store.set('sort', S.sort);
        renderModList();
        return;
      }
      const modRow = e.target.closest('#modlist tbody tr[data-id]');
      if (modRow) { const m = modByKey(modRow.dataset.id); if (m) selectMod(m.id); return; }
      const mt = e.target.closest('.minitab');
      if (mt) { S.selRow = +mt.dataset.row; S.selOpt = -1; renderDetails(); return; }
      const opt = e.target.closest('#optlist tbody tr[data-opt]');
      if (opt) { S.selOpt = +opt.dataset.opt; renderDetails(); $('#optlist') && $('#optlist').focus(); return; }
      const pr = e.target.closest('#problemlist tbody tr[data-key]');
      if (pr) { S.selProblem = pr.dataset.key; renderLog(); return; }
      const jr = e.target.closest('#tasklist tbody tr[data-job]');
      if (jr) {
        S.selJob = jr.dataset.job;
        const j = S.jobs.find(x => String(x.id) === S.selJob);
        if (j && j.mod_id !== null && j.mod_id !== undefined && modById(j.mod_id)) selectMod(j.mod_id, true);
        renderTasks();
      }
    });

    document.addEventListener('change', e => {
      if (e.target.id === 'row-select') { S.selRow = +e.target.value; S.selOpt = -1; renderDetails(); }
      else if (e.target.id === 'opt-watch') saveWatch(e.target.checked);
      else if (e.target.id === 'log-autoscroll' && e.target.checked) { const v = $('#logview'); v.scrollTop = v.scrollHeight; }
    });
    $('#log-filter').addEventListener('input', () => renderTail());

    document.addEventListener('contextmenu', e => {
      if (e.target.closest('input, textarea, .logview, .selectable, .tree, .path')) return;
      e.preventDefault();
      const row = e.target.closest('#modlist tbody tr[data-id]');
      if (!row || modal) return;
      const m = modByKey(row.dataset.id);
      if (!m) return;
      selectMod(m.id);
      const busy = m.state === 'working';
      showCtx(e.clientX, e.clientY, [
        { label: m.state === 'not_installed' ? 'Install' : 'Reinstall', disabled: busy, run: () => reinstall(m.id) },
        { label: 'Remove...', disabled: busy, run: () => askRemove(m.id) },
        '-',
        { label: 'Open folder', run: () => openPath(m.id) },
      ]);
    });

    document.addEventListener('keydown', e => {
      if (modal) {
        if (e.key === 'Escape') { e.preventDefault(); modal.cancel(); }
        else if (e.key === 'Enter' && !(document.activeElement && document.activeElement.tagName === 'BUTTON')) { e.preventDefault(); modal.accept(); }
        return;
      }
      if (e.key === 'Escape') hideCtx();
      if (e.key === 'F5' || (e.ctrlKey && (e.key === 'r' || e.key === 'R'))) { e.preventDefault(); refreshNow(); return; }
      const a = document.activeElement;
      if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return;
      if (e.key === 'Delete' && S.tab === 'mods' && S.selected !== null) { e.preventDefault(); askRemove(S.selected); return; }
      const nav = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10, Home: -Infinity, End: Infinity }[e.key];
      if (nav === undefined || !a) return;
      if (a.id === 'modlist') { e.preventDefault(); moveIn('#modlist', nav, r => { const m = modByKey(r.dataset.id); if (m) selectMod(m.id); }); }
      else if (a.id === 'problemlist') { e.preventDefault(); moveIn('#problemlist', nav, r => { S.selProblem = r.dataset.key; renderLog(); }); }
      else if (a.id === 'optlist') {
        e.preventDefault();
        moveIn('#optlist', nav, r => { S.selOpt = +r.dataset.opt; S.revealOpt = true; renderDetails(); const ol = $('#optlist'); if (ol) ol.focus(); });
      }
    });

    // drag and drop: show the overlay; pywebview hands the real paths to Python
    let depth = 0;
    const hasFiles = e => !!(e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files'));
    const overlay = show => { $('#drop-overlay').hidden = !show; };
    addEventListener('dragenter', e => { if (!hasFiles(e)) return; e.preventDefault(); depth++; overlay(true); }, true);
    addEventListener('dragover', e => { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = hasFiles(e) ? 'copy' : 'none'; }, true);
    addEventListener('dragleave', e => { if (!hasFiles(e)) return; depth = Math.max(0, depth - 1); if (!depth) overlay(false); }, true);
    addEventListener('drop', e => {
      e.preventDefault();
      depth = 0;
      overlay(false);
      if (!hasFiles(e)) return;
      setMsg('Adding...');
      if (bridge === 'mock') addPaths(Array.from(e.dataTransfer.files || []).map(f => f.name));
      else pollFast(6000);
    }, true);

    addEventListener('blur', hideCtx);
    addEventListener('resize', hideCtx);

    makeSplitter($('#mods-splitter'), $('#mods-left'), 'x', 'split.mods', 360,
      () => $('#mods-split').offsetWidth - 380);
    makeSplitter($('#tasks-splitter'), $('#tasks'), 'y', 'split.tasks', 90,
      () => Math.max(90, $('#page-mods').offsetHeight - 220));
  }

  // ------------------------------------------------------------------ start
  async function start() {
    bind();
    renderAll();
    setMsg('Connecting...');
    await bridgeReady;
    const [, settings] = await Promise.all([refreshAll(), call('get_settings')]);
    if (settings && typeof settings === 'object' && !isFail(settings)) S.settings = settings;
    renderSetup();
    const st = obj(S.state);
    if (st.first_run || !obj(st.game).found) selectTab('setup');
    await loadMonitor();
    setMsg('Ready');
    window.e33.ready = true;
    document.dispatchEvent(new Event('e33ready'));
    tick();
  }

  window.e33 = {
    devDrop: paths => addPaths(paths),
    call,
    ready: false,
    // used by mock screens and tests
    ui: {
      selectTab,
      selectMod: id => selectMod(id, true),
      selectRow: i => { S.selRow = i; S.selOpt = -1; renderDetails(); },
      selectOption: i => { S.selOpt = i; S.revealOpt = true; renderDetails(); },
      askRemove: id => askRemove(id === undefined ? S.selected : id),
      showHelp,
      showDrop: on => { $('#drop-overlay').hidden = !on; },
      refresh: refreshNow,
      state: () => S,
    },
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
