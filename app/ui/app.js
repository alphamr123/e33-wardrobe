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
  const isImg = v => IMG_RE.test(str(v));
  const leafOf = p => str(p).replace(/\/+$/, '').split('/').pop();

  /** A swatch picture, or nothing at all when there is none (no empty box). */
  function swatch(src, cls, attrs) {
    return isImg(src) ? `<img class="${cls}" src="${src}" alt=""${attrs || ''}>` : '';
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
  const texSize = i => (num(i.width) && num(i.height) ? `${num(i.width)} x ${num(i.height)}` : 'size not recorded')
    + (i.format ? ' ' + str(i.format) : '');
  const store = {
    get(k, d) { try { const v = localStorage.getItem('e33.' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('e33.' + k, JSON.stringify(v)); } catch (e) { /* storage off */ } },
    del(k) { try { localStorage.removeItem('e33.' + k); } catch (e) { /* storage off */ } },
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
    selected: null,          // the mod whose details show
    checked: new Set(),      // mods ticked for bulk actions (ids)
    anchor: null,            // last clicked mod, for Shift+click ranges
    modFilter: '',
    selRow: 0,
    selOpt: -1,
    expanded: new Set(),     // open "Show ..." lists in the details, by key
    jobs: [],
    hiddenJobs: new Set(),   // "Clear finished" (client side as well)
    selJob: null,
    changed: null,
    busy: false,
    monitor: null,
    logSource: store.get('logSource', 'this'),   // this | previous | ue4ss
    fileLog: null,           // {which, data} from monitor_file
    logFilter: null,         // {kind: 'problem', key, label} | {kind: 'slot', slot, label}
    selProblem: null,
    selOnscreen: null,
    sort: store.get('sort', { key: 'name', dir: 1 }),
    gameError: null,
    installing: false,
    lastCopy: null,          // the last text put on the clipboard (tests)
  };
  const modById = id => S.mods.find(m => m.id === id) || null;
  const modByKey = key => S.mods.find(m => str(m.id) === key) || null;   // key: a data-id attribute
  // ticked mods the list shows (a filter hides the others from bulk actions too), in list order
  const checkedMods = () => sortedMods().filter(m => S.checked.has(m.id) && matchesFilter(m));

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
      lastFile = 0;
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
    S.checked.forEach(id => { if (!modById(id)) S.checked.delete(id); });
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

  /** The log shown when it isn't the live monitor: monitor_file(previous | ue4ss | last). */
  function fileSource() {
    if (S.logSource === 'previous' || S.logSource === 'ue4ss') return S.logSource;
    return S.monitor && S.monitor.watching === false ? 'last' : null;
  }
  async function loadFileLog() {
    const which = fileSource();
    if (!which) return;
    const known = S.fileLog && S.fileLog.which === which && S.fileLog.data ? S.fileLog.data.version : null;
    const d = await call('monitor_file', which, known || null);
    if (fileSource() !== which) return;
    if (d && d.unchanged && known && d.version === known) return;          // same files as last time
    S.fileLog = { which, data: d && !isFail(d) && typeof d === 'object' ? d : null, error: isFail(d) ? str(d.error) : (d ? null : 'No answer.') };
    renderLog();
  }

  // ------------------------------------------------------------------ polling
  let pollTimer = null, ticking = false, tickAgain = false, fastUntil = 0, lastMon = 0, lastFile = 0, pollFailed = false;
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
      if (S.tab === 'log' && fileSource() && now - lastFile >= 5000) { lastFile = now; await loadFileLog(); }
    } finally {
      ticking = false;
    }
    const delay = tickAgain ? 0 : (S.busy || Date.now() < fastUntil) ? 500 : 1500;
    tickAgain = false;
    pollTimer = setTimeout(tick, delay);
  }
  function pollFast(ms) { fastUntil = Date.now() + (ms || 4000); tick(); }

  // ------------------------------------------------------------------ list columns: drag the header borders
  // Like a Windows list view: drag the right edge of a column header to resize it, double-click
  // it to fit the column to its text. The last column takes the space that is left. Widths are
  // kept per list (localStorage); right-click a header for "Reset column widths".
  const colKey = table => 'cols.' + table.dataset.cols;
  function addGrips(table) {
    const ths = $$('thead th', table);
    ths.forEach((th, i) => {
      if (i === ths.length - 1 || th.classList.contains('chk-cell') || th.querySelector('.col-grip')) return;
      th.insertAdjacentHTML('beforeend', '<span class="col-grip" title="Drag to resize, double-click to fit"></span>');
    });
  }
  function setWidths(table, widths) {
    const cols = $$('colgroup col', table);
    let sum = 0;
    cols.forEach((c, i) => {
      const w = Math.round(num(widths[i]));
      if (i === cols.length - 1) { c.style.width = 'auto'; sum += Math.max(40, w); }
      else { c.style.width = w + 'px'; sum += w; }
    });
    table.style.minWidth = sum + 'px';
  }
  function applyColumns(table) {
    if (!table || !table.dataset.cols) return;
    addGrips(table);
    const saved = store.get(colKey(table), null);
    const cols = $$('colgroup col', table);
    if (Array.isArray(saved) && saved.length === cols.length && saved.every(w => num(w) > 0)) setWidths(table, saved);
    else { cols.forEach(c => { c.style.width = ''; }); table.style.minWidth = ''; }
  }
  function currentWidths(table) { return $$('thead th', table).map(th => th.getBoundingClientRect().width); }
  let resizing = false, resizedAt = 0;
  function startResize(e, grip) {
    const th = grip.closest('th'), table = th.closest('table');
    const ths = $$('thead th', table), idx = ths.indexOf(th);
    const widths = currentWidths(table), w0 = widths[idx], x0 = e.clientX;
    const min = th.classList.contains('ico-col') ? 18 : 30;
    resizing = true;
    document.body.classList.add('col-resizing');
    const move = ev => { widths[idx] = Math.max(min, w0 + ev.clientX - x0); setWidths(table, widths); };
    const up = () => {
      removeEventListener('mousemove', move, true);
      removeEventListener('mouseup', up, true);
      document.body.classList.remove('col-resizing');
      resizing = false;
      resizedAt = Date.now();
      if (table.isConnected) store.set(colKey(table), currentWidths(table).map(Math.round));
    };
    addEventListener('mousemove', move, true);
    addEventListener('mouseup', up, true);
  }
  function fitColumn(grip) {
    const th = grip.closest('th'), table = th.closest('table');
    const ths = $$('thead th', table), idx = ths.indexOf(th);
    const meas = document.createElement('span');
    meas.className = 'measure';
    document.body.appendChild(meas);
    const widthOf = cell => {
      const cs = getComputedStyle(cell);
      meas.style.font = cs.font;
      meas.innerHTML = cell.innerHTML;
      $$('.col-grip', meas).forEach(g => g.remove());
      return meas.getBoundingClientRect().width + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + 4;
    };
    let w = widthOf(th);
    $$('tbody tr', table).slice(0, 400).forEach(tr => { const td = tr.children[idx]; if (td && td.colSpan === 1) w = Math.max(w, widthOf(td)); });
    meas.remove();
    const widths = currentWidths(table);
    widths[idx] = Math.max(30, Math.ceil(w));
    setWidths(table, widths);
    store.set(colKey(table), currentWidths(table).map(Math.round));
  }
  function resetColumns(table) {
    store.del(colKey(table));
    applyColumns(table);
  }

  // ------------------------------------------------------------------ rendering: toolbar
  function renderToolbar() {
    const m = modById(S.selected);
    const many = checkedMods();
    const n = many.length;
    const can = n ? many.some(x => x.state !== 'working') : (!!m && m.state !== 'working');
    $$('[data-needs-mod]').forEach(b => { b.disabled = !can; });
    const ri = n ? `Reinstall selected (${n})` : m && m.state === 'not_installed' ? 'Install' : 'Reinstall';
    const rm = n ? `Remove selected (${n})...` : 'Remove';
    const tbR = $('#tb-reinstall'), tbX = $('#tb-remove');
    if (tbR) { tbR.textContent = ri; tbR.title = n ? `Prepare the ${plural(n, 'ticked mod')} again` : 'Prepare the selected mod again'; }
    if (tbX) { tbX.textContent = rm; tbX.title = n ? `Remove the ${plural(n, 'ticked mod')} (Delete)` : 'Remove the selected mod (Delete)'; }
    // the buttons under the details act on the mod shown there, ticks or not
    const rb = $('#btn-reinstall'), xb = $('#btn-remove');
    const shown = !!m && m.state !== 'working';
    if (rb) { rb.textContent = m && m.state === 'not_installed' ? 'Install' : 'Reinstall'; rb.disabled = !shown; }
    if (xb) xb.disabled = !shown;
    const all = $('#tb-reinstall-all');
    if (all) all.disabled = !S.mods.some(x => x.state !== 'working');
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
  function matchesFilter(m) {
    const f = S.modFilter.trim().toLowerCase();
    if (!f) return true;
    return [m.name, m.id, arr(m.characters).join(' '), arr(m.replaces).join(' ')].some(v => str(v).toLowerCase().includes(f));
  }
  const shownMods = () => sortedMods().filter(matchesFilter);

  function renderModList() {
    const all = sortedMods();
    const mods = all.filter(matchesFilter);
    $('#modlist tbody').innerHTML = mods.map(m => {
      const [cls, label] = stateInfo(m.state);
      const name = str(m.name || m.id);
      const chars = arr(m.characters).join(', ');
      const repl = arr(m.replaces).join(', ');
      const notes = num(m.notes);
      const on = S.checked.has(m.id);
      const rowCls = [m.id === S.selected ? 'sel' : '', on ? 'chk' : '', m.state === 'not_installed' ? 'off' : ''].join(' ').trim();
      return `<tr data-id="${esc(m.id)}"${rowCls ? ` class="${rowCls}"` : ''}>`
        + `<td class="chk-cell"><input type="checkbox" tabindex="-1" data-chk${on ? ' checked' : ''} title="Select for Reinstall / Remove"></td>`
        + `<td title="${esc(name)}">${esc(name)}</td>`
        + `<td title="${esc(chars)}">${chars ? esc(chars) : '<span class="dim">-</span>'}</td>`
        + `<td title="${esc(repl)}">${repl ? esc(repl) : '<span class="dim">-</span>'}</td>`
        + `<td class="num">${num(m.options) || '<span class="dim">-</span>'}</td>`
        + `<td class="num" title="${esc(fmtSize(m.size))}">${esc(fmtSize(m.size))}</td>`
        + `<td title="${esc(notes ? label + ', ' + plural(notes, 'note') : label)}"><span class="sq ${cls}"></span><span class="st-text">${esc(label)}</span>`
        + `${notes ? `<span class="ico small ${m.note_level === 'warn' ? 'warn' : 'info'} note-ico"></span>` : ''}</td></tr>`;
    }).join('');
    $$('#modlist th[data-sort]').forEach(th => {
      const old = th.querySelector('.arrow');
      if (old) old.remove();
      if (th.dataset.sort === S.sort.key) th.insertBefore(Object.assign(document.createElement('span'), { className: `arrow ${S.sort.dir === -1 ? 'down' : 'up'}` }), th.querySelector('.col-grip'));
    });
    const empty = $('#modlist-empty');
    empty.hidden = mods.length > 0;
    empty.textContent = all.length ? 'No mod matches the filter.' : dropHint();
    const ca = $('#chk-all');
    const nOn = mods.filter(m => S.checked.has(m.id)).length;
    ca.checked = mods.length > 0 && nOn === mods.length;
    ca.indeterminate = nOn > 0 && nOn < mods.length;
    const n = mods.filter(m => S.checked.has(m.id)).length;
    $('#mod-count').textContent = (S.modFilter.trim() ? `${mods.length} of ${plural(all.length, 'mod')}` : plural(all.length, 'mod'))
      + (n ? `, ${n} selected` : '');
  }

  function selectMod(id, scroll) {
    if (S.selected !== id) { S.selected = id; S.selRow = 0; S.selOpt = -1; }
    if (id !== null) S.anchor = id;
    renderModList();
    renderDetails();
    renderToolbar();
    if (id !== null && !S.details[id]) loadDetails(id);
    if (scroll) {
      const tr = $$('#modlist tbody tr').find(r => r.dataset.id === str(id));
      if (tr) tr.scrollIntoView({ block: 'nearest' });
    }
  }
  function setChecked(ids, on) {
    ids.forEach(id => { if (on) S.checked.add(id); else S.checked.delete(id); });
    renderModList();
    renderToolbar();
  }
  /** Shift+click: tick every shown mod from the anchor to this one. */
  function checkRange(id) {
    const ids = shownMods().map(m => m.id);
    let a = ids.indexOf(S.anchor), b = ids.indexOf(id);
    if (a < 0) a = b;
    if (b < 0) return;
    setChecked(ids.slice(Math.min(a, b), Math.max(a, b) + 1), true);
  }

  // ------------------------------------------------------------------ rendering: details
  function rowLabel(row, multi) {
    const label = str(row.label) || str(row.id);
    const ch = str(row.character);
    return multi && ch && !label.toLowerCase().startsWith(ch.toLowerCase()) ? `${ch} · ${label}` : label;
  }
  const isMulti = rows => new Set(arr(rows).map(r => str(r.character))).size > 1;

  /** A "Show 11 options" toggle with its hidden list (a classic tree box). key: kept open across renders. */
  function xlist(key, items, noun, mono) {
    items = arr(items).map(str).filter(Boolean);
    if (!items.length) return '';
    const open = S.expanded.has(key);
    return `<button class="xtoggle" data-x="${esc(key)}" aria-expanded="${open}"><span class="xbox">${open ? '\u2212' : '+'}</span>`
      + `${open ? 'Hide' : 'Show'} ${plural(items.length, noun)}</button>`
      + (open ? `<ul class="xlist sunken selectable${mono ? ' mono' : ''}">${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>` : '');
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
    const optScrollX = ($('#optlist') || {}).scrollLeft || 0;
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

    let h = `<div class="d-head"><div class="d-title"><span class="d-name selectable" title="${esc(info.name || m.id)}">${esc(info.name || m.id)}</span>`
      + `<span class="d-state"><span class="sq ${cls}"></span>${esc(label)}</span></div>`
      + `<div class="props">`
      + `<span class="k">Characters</span><span class="v selectable" title="${esc(chars)}">${esc(chars) || '-'}</span>`
      + `<span class="k">Options</span><span class="v selectable">${nOpts}${nRows ? ` in ${plural(nRows, 'row')}` : ''}</span>`
      + `<span class="k">Replaces</span><span class="v wide selectable" title="${esc(repl)}">${esc(repl) || '-'}</span>`
      + `<span class="k">Size</span><span class="v selectable">${esc(fmtSize(info.size || m.size)) || '-'}</span>`
      + `<span class="k">Skin</span><span class="v selectable">${skinHas ? 'Own body textures' : "Game's own"}</span>`
      + (folder ? `<span class="k">Folder</span><span class="v wide selectable" data-copy-path="${esc(folder)}" title="${esc(folder)}">${esc(folder)}</span>` : '')
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
      applyColumns(ol.querySelector('table'));
      ol.scrollTop = optScroll;
      ol.scrollLeft = optScrollX;
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
    const multi = isMulti(rows);
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
    h += `<div class="lv${useTabs ? ' with-tabs' : ''}" id="optlist" tabindex="0"><table data-cols="opts">`
      + '<colgroup><col class="c-sw"><col class="c-opt"><col class="c-chg"><col class="c-tex"><col class="c-tags"></colgroup>'
      + '<thead><tr><th class="ico-col"></th><th>Option</th><th>Changes</th><th>Textures</th><th>Tags</th></tr></thead><tbody>';
    h += opts.map((o, i) => {
      o = obj(o);
      const bad = o.ok === false;
      const notes = arr(o.notes);
      const mark = bad ? '<span class="ico small error" style="margin-right:5px"></span>'
        : notes.length ? '<span class="ico small info" style="margin-right:5px"></span>' : '';
      const tagText = arr(o.tags).join(', ');
      const cls = [i === S.selOpt ? 'sel' : '', bad ? 'off' : ''].join(' ').trim();
      const texTip = arr(o.images).length ? arr(o.images).map(im => `${str(im.name)}: ${texSize(im)}`).join('\n') : str(o.textures);
      return `<tr data-opt="${i}"${cls ? ` class="${cls}"` : ''}>`
        + `<td class="sw-cell">${swatch(o.swatch, 'sw16 zoomable', ` data-view-opt="${i}" title="View (click)"`)}</td>`
        + `<td title="${esc(o.label)}">${mark}${esc(o.label)}</td>`
        + (bad ? `<td title="${esc(o.error)}"><span class="step-err">Skipped</span></td>`
          : `<td title="${esc(o.changes)}">${esc(o.changes) || '<span class="dim">-</span>'}</td>`)
        + `<td title="${esc(texTip)}">${esc(o.textures) || '<span class="dim">-</span>'}</td>`
        + `<td title="${esc(tagText)}">${esc(tagText)}</td></tr>`;
    }).join('');
    if (!opts.length) h += '<tr><td></td><td colspan="4" class="muted">No options in this row.</td></tr>';
    h += '</tbody></table></div>';
    h += `<div class="opt-detail" id="opt-detail">${optDetail(d, rows[S.selRow], opts)}</div>`;
    return h + '</fieldset>';
  }

  function optDetail(d, row, opts) {
    const o = S.selOpt >= 0 ? obj(opts[S.selOpt]) : null;
    if (!o) {
      const flagged = opts.filter(x => x && (x.ok === false || arr(x.notes).length)).length;
      return `<div class="muted">${flagged ? `${plural(flagged, 'option has', 'options have')} notes. Select one to read them.` : 'Select an option to see its files and textures.'}</div>`;
    }
    const key = `${d.id}|${S.selRow}|${S.selOpt}`;
    const parts = [];
    if (o.ok === false) parts.push(`<div class="od-line"><span class="ico small error"></span><span class="c-bad selectable">Skipped: ${esc(o.error || 'no reason given.')}</span></div>`);
    arr(o.notes).forEach(n => parts.push(`<div class="od-line"><span class="ico small info"></span><span class="selectable">${esc(n)}</span></div>`));
    if (!parts.length) parts.push(`<div class="od-line muted">No notes for ${esc(o.label)}.</div>`);
    const imgs = arr(o.images).map(obj);
    if (imgs.length) {
      const pics = imgs.map((im, i) => isImg(im.swatch)
        ? `<img class="sw36 zoomable" src="${im.swatch}" alt="" data-view-img="${i}" title="${esc(im.name)}: ${esc(texSize(im))} (click to view)">` : '').join('');
      const list = imgs.map((im, i) => `<li><a class="tex-link" data-view-img="${i}" title="View ${esc(im.name)}">${esc(im.name)}</a>`
        + `<span class="muted"> ${esc(texSize(im))}${im.kind ? ', ' + esc(str(im.kind).toLowerCase()) : ''}</span></li>`).join('');
      const nosize = imgs.some(im => !num(im.width));
      parts.push(`<div class="od-sub">Textures${pics ? '' : ' <span class="muted">(no swatches saved)</span>'}</div>`
        + `<div class="od-tex">${pics ? `<div class="od-pics">${pics}</div>` : ''}<ul class="od-texlist selectable">${list}</ul></div>`
        + (nosize ? '<div class="od-line muted">Sizes weren\'t recorded when this option was prepared. Reinstall the mod to record them, or click a name to read that texture.</div>' : ''));
    }
    arr(o.missing).map(obj).filter(x => arr(x.names).length > 2).forEach((x, i) => {   // up to 2 are in the note
      parts.push(`<div class="od-sub">Missing files linked from ${esc(x.name)} `
        + `<span class="muted selectable">(${esc(x.in)})</span>${xlist(`${key}|miss|${i}`, x.names, 'missing file', true)}</div>`);
    });
    const files = arr(o.files).map(obj);
    if (files.length) {
      parts.push(`<div class="od-sub">${xlist(key + '|files', files.map(f => `${f.type}: ${f.path}${f.game ? '  (replaces a game file)' : ''}`), 'file', true)}</div>`);
    }
    return parts.join('');
  }

  function renderSkinGroup(d) {
    const sk = obj(d.skin);
    let h = '<fieldset class="gb"><legend>Skin</legend>';
    if (!sk.has) return h + `<div class="empty-line">${esc(sk.text) || "Uses the game's own body textures."}</div></fieldset>`;
    const imgs = arr(sk.images).map(obj).filter(im => isImg(im.swatch));
    const sw = imgs.length
      ? imgs.slice(0, 6).map((im, i) => `<img class="sw36 zoomable" src="${im.swatch}" alt="" data-view-skin="${i}" title="${esc(im.name)}: ${esc(texSize(im))} (click to view)">`).join('')
      : arr(sk.swatches).slice(0, 6).map((s, i) => swatch(s, 'sw36 zoomable', ` data-view-skin="${i}" title="Click to view"`)).join('');
    return h + `<div class="skin-row">${sw ? `<div class="skin-sw">${sw}</div>` : ''}<div class="skin-text selectable">${esc(sk.text) || 'Brings its own body textures.'}`
      + (imgs.length ? `<div class="muted">${esc(imgs.slice(0, 6).map(im => im.name).join(', '))}${imgs.length > 6 ? ` and ${imgs.length - 6} more` : ''}</div>` : '')
      + `</div></div></fieldset>`;
  }

  function renderNotesGroup(d) {
    const notes = arr(d.notes).map(obj);
    let h = '<fieldset class="gb"><legend>Notes</legend>';
    if (!notes.length) return h + '<div class="empty-line">No notes.</div></fieldset>';
    return h + '<ul class="lines">' + notes.map((n, i) =>
      `<li data-note="${i}"><span class="ico small ${n.level === 'warn' ? 'warn' : n.level === 'error' ? 'error' : 'info'}"></span>`
      + `<span class="ln-body"><span class="selectable">${esc(n.text)}</span>`
      + xlist(`${d.id}|note|${i}`, n.items, n.what === 'files' ? 'file' : 'option', n.what === 'files') + '</span></li>'
    ).join('') + '</ul></fieldset>';
  }

  function renderOverlapsGroup(d) {
    const ov = arr(d.overlaps).map(obj);
    let h = '<fieldset class="gb"><legend>Overlaps</legend>';
    if (!ov.length) return h + '<div class="empty-line">No overlaps with other mods.</div></fieldset>';
    return h + '<ul class="lines">' + ov.map((o, i) =>
      `<li data-overlap="${i}"><span class="ico small info"></span><span class="ln-body"><span class="selectable"><span class="ovl-mod">${esc(o.mod)}</span>: ${esc(o.text)}</span>`
      + xlist(`${d.id}|ovl|${i}`, o.files, 'file', true) + '</span></li>'
    ).join('') + '</ul></fieldset>';
  }

  // ------------------------------------------------------------------ plain text for the clipboard
  function optionText(row, o, multi) {
    o = obj(o);
    const lines = [`${row ? rowLabel(row, multi) + ' · ' : ''}${str(o.label)}`];
    if (o.ok === false) lines.push(`  Skipped: ${str(o.error)}`);
    else {
      if (o.changes) lines.push(`  Changes: ${o.changes}`);
      if (o.textures) lines.push(`  Textures: ${o.textures}`);
    }
    if (arr(o.tags).length) lines.push(`  Tags: ${arr(o.tags).join(', ')}`);
    arr(o.images).forEach(im => lines.push(`  Texture: ${str(im.name)} (${texSize(im)})${im.path ? '  ' + im.path : ''}`));
    arr(o.notes).forEach(n => lines.push(`  Note: ${n}`));
    arr(o.missing).forEach(x => arr(obj(x).names).forEach(n => lines.push(`  Missing (linked from ${str(x.name)}): ${n}`)));
    arr(o.files).forEach(f => lines.push(`  File: ${f.type}: ${f.path}${f.game ? ' (replaces a game file)' : ''}`));
    return lines.join('\n');
  }
  function detailsText(d, m) {
    d = obj(d);
    const L = [str(d.name || (m && m.name) || d.id)];
    const multi = isMulti(d.rows);
    L.push(`Characters: ${arr(d.characters).join(', ') || '-'}`);
    L.push(`Replaces: ${arr(d.replaces).join(', ') || '-'}`);
    L.push(`Options: ${num(d.options)} in ${plural(arr(d.rows).length, 'row')}`);
    L.push(`Size: ${fmtSize(d.size) || '-'}`);
    L.push(`Status: ${stateInfo(d.state)[1]}`);
    if (d.folder) L.push(`Folder: ${d.folder}`);
    const sk = obj(d.skin);
    L.push(`Skin: ${sk.has ? str(sk.text) || 'Own body textures' : "Game's own"}`);
    arr(sk.images).forEach(im => L.push(`  ${str(im.name)} (${texSize(im)})  ${str(im.path)}`));
    L.push('', 'Menu rows');
    arr(d.rows).forEach(r => {
      L.push(`${rowLabel(r, multi)} (${plural(arr(r.options).length, 'option')})`);
      arr(r.options).forEach(o => L.push(optionText(null, o).split('\n').map(x => '  ' + x).join('\n')));
    });
    L.push('', 'Notes');
    if (!arr(d.notes).length) L.push('  None.');
    arr(d.notes).forEach(n => { L.push(`  [${str(n.level)}] ${str(n.text)}`); arr(n.items).forEach(i => L.push(`    ${i}`)); });
    L.push('', 'Overlaps');
    if (!arr(d.overlaps).length) L.push('  None.');
    arr(d.overlaps).forEach(o => { L.push(`  ${str(o.mod)}: ${str(o.text)}`); arr(o.files).forEach(f => L.push(`    ${f}`)); });
    return L.join('\n') + '\n';
  }
  function modRowText(m) {
    return [m.name || m.id, arr(m.characters).join(', '), arr(m.replaces).join(', '), num(m.options), fmtSize(m.size), stateInfo(m.state)[1]].join('\t');
  }
  function problemText(p) {
    p = obj(p);
    const when = p.first && p.last && p.first !== p.last ? `${p.first} to ${p.last}` : str(p.first || p.last);
    const L = [`[${str(p.level).toUpperCase()}] ${when}${num(p.count) > 1 ? `, ${p.count} times` : ''}: ${str(p.title)}`];
    if (p.detail) L.push('  ' + p.detail);
    if (p.hint) L.push('  What to do: ' + p.hint);
    arr(p.lines).forEach(l => L.push('  Log: ' + l));
    return L.join('\n');
  }
  const selectionText = () => { const s = window.getSelection && window.getSelection(); return s ? s.toString() : ''; };

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
  const LOG_FILE = { previous: 'live_log_previous.txt', ue4ss: 'UE4SS.log', last: 'live_log.txt' };
  let lastTailKey = '', lastLogKey = '';

  /** What the Game log tab shows: the live monitor, or a log read from disk. */
  function logData() {
    const which = fileSource();
    if (!which) return S.monitor;
    return S.fileLog && S.fileLog.which === which ? S.fileLog.data : null;
  }

  function renderLog() {
    const m = logData();
    const probs = arr(m && m.problems).map(obj);
    if (probs.length && !probs.some(p => str(p.key) === S.selProblem)) S.selProblem = str(probs[0].key);
    if (!probs.length) S.selProblem = null;
    const f = S.logFilter;
    if (f && f.kind === 'problem' && !probs.some(p => str(p.key) === f.key)) S.logFilter = null;
    // the monitor is polled every 1.4 s: rebuild the lists only when something changed
    const key = JSON.stringify([m ? Object.assign({}, m, { tail: null }) : null, S.selProblem, S.selOnscreen, S.monitorError,
      S.logSource, fileSource(), S.logFilter, S.fileLog && S.fileLog.error, obj(S.monitor).game_running]);
    if (key !== lastLogKey) { lastLogKey = key; renderLogLists(m, probs); }
    renderBadge();
    renderTail();
  }
  /** The count on the Game log tab: the live monitor's errors and warnings, whatever log is shown. */
  let lastBadge = null;
  function renderBadge() {
    const live = arr(S.monitor && S.monitor.problems).map(obj);
    const serious = live.filter(p => p.level === 'error' || p.level === 'warn').length;
    const bad = live.some(p => p.level === 'error');
    const html = 'Game log' + (serious ? `<span class="badge${bad ? ' bad' : ''}">${serious}</span>` : '');
    if (html !== lastBadge) { lastBadge = html; $('.tab[data-tab="log"]').innerHTML = html; }
  }

  function logStatus(m) {
    const which = fileSource();
    const span = d => {
      const a = d.since ? hhmm(d.since) : '', b = d.ended ? hhmm(d.ended) : '';
      return (a && b && a !== b ? `${a} to ${b}` : a || b) + (d.date ? `, ${d.date}` : '');
    };
    if (which) {
      if (!m) return ['idle', S.fileLog && S.fileLog.error && S.fileLog.which === which ? `Can't read ${LOG_FILE[which]}: ${S.fileLog.error}` : `Reading ${LOG_FILE[which]}...`];
      if (!m.exists) {
        return ['idle', which === 'previous' ? 'No previous session yet (live_log_previous.txt is written at the next game start).'
          : which === 'ue4ss' ? 'No UE4SS.log yet. It is written when the game starts with UE4SS.' : 'No session log yet.'];
      }
      if (which === 'previous') return ['idle', `Previous session (live_log_previous.txt): ${span(m)}`];
      if (which === 'ue4ss') return ['idle', `UE4SS.log of the last game start: ${span(m)}${obj(S.monitor).game_running ? ' (still being written)' : ''}`];
      return ['idle', `Not following the game's logs (Setup). Showing the last session from disk (ended ${hhmm(m.ended) || '?'}${m.date ? ', ' + m.date : ''}).`];
    }
    if (!m) return ['idle', S.monitorError ? `Can't read the game's logs: ${S.monitorError}` : "Reading the game's logs..."];
    if (m.game_running) {
      const parts = [m.since ? `Game running since ${hhmm(m.since)}` : 'Game running'];
      parts.push(m.menu_active ? 'menu active' : 'menu not started yet');
      if (m.last_activity) parts.push(`last activity ${m.last_activity}`);
      return ['ok', parts.join(' · ')];
    }
    if (m.ended) return ['idle', `Game not running \u2014 last session, ended ${hhmm(m.ended)}${m.date ? ', ' + m.date : ''}`];
    return ['idle', 'Game not running. Start it and this tab follows the logs.'];
  }

  function renderLogLists(m, probs) {
    const [icon, line] = logStatus(m);
    $('#log-ico').className = 'ico ' + icon;
    $('#log-status').textContent = line;
    $('#log-status').title = line;
    const leg = $('#onscreen-legend');
    if (leg) leg.textContent = m && m.game_running && !fileSource() ? 'On screen now' : 'On screen when the log ended';
    const src = $('#log-source');
    if (src.value !== S.logSource) src.value = S.logSource;

    // problems
    const pf = S.logFilter && S.logFilter.kind === 'problem' ? S.logFilter.key : null;
    $('#problemlist tbody').innerHTML = probs.map(p =>
      `<tr data-key="${esc(p.key)}" class="${[str(p.key) === S.selProblem ? 'sel' : '', str(p.key) === pf ? 'filt' : ''].join(' ').trim()}">`
      + `<td class="ico-cell"><span class="ico small ${SEV[p.level] || 'info'}"></span></td>`
      + `<td title="${esc(p.first && p.last && p.first !== p.last ? `${p.first} to ${p.last}` : (p.last || p.first))}">${esc(p.last || p.first)}</td>`
      + `<td title="${esc(p.title)}${arr(p.lines).length ? '\n(click to show its log lines)' : ''}">${esc(p.title)}</td>`
      + `<td class="num">${num(p.count) || 1}</td></tr>`
    ).join('');
    $('#problems-empty').hidden = probs.length > 0;
    $('#problems-empty').textContent = m && (m.exists === false) ? 'Nothing to show.' : 'No problems found.';
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
      pd.innerHTML = `<span class="muted">${m && m.game_running ? 'Problems the logs show are listed above.' : 'Problems the logs show are listed above. Click one to see its log lines.'}</span>`;
      pd.classList.remove('selectable');
    }

    // on screen
    const on = arr(m && m.on_screen).map(obj);
    const sf = S.logFilter && S.logFilter.kind === 'slot' ? S.logFilter.slot : null;
    $('#onscreenlist tbody').innerHTML = on.map(o => {
      const shown = num(o.shown), total = num(o.total);
      const cls = total && shown >= total ? '' : shown === 0 ? 'c-bad' : 'c-warn';
      const rc = [str(o.slot) === S.selOnscreen ? 'sel' : '', str(o.slot) === sf ? 'filt' : ''].join(' ').trim();
      return `<tr data-slot="${esc(o.slot)}" data-variant="${esc(o.variant)}"${rc ? ` class="${rc}"` : ''}><td title="${esc(o.slot)}">${esc(o.slot)}</td><td title="${esc(o.variant)}">${esc(o.variant)}</td>`
        + `<td class="num"><span class="${cls}">${shown}/${total}</span></td><td>${o.worn ? 'Yes' : '<span class="dim">No</span>'}</td></tr>`;
    }).join('');
    $('#onscreen-empty').hidden = on.length > 0;
    $('#onscreen-empty').textContent = S.logSource === 'ue4ss' ? 'UE4SS.log has no on-screen lines; pick This session.'
      : m && m.game_running ? 'Nothing from your mods on screen.' : m && (m.ended || m.since) ? 'Nothing from your mods was on screen at the end.' : 'Shown while the game runs.';
  }

  const lineClass = l => (/watchdog|error|fail|crash|grey/i.test(l) ? 'l-bad' : /warn|skipp|hidden|not visible|made for|empty \(/i.test(l) ? 'l-warn' : '');

  /** The lines the Session log shows: all, or the ones of the problem / on-screen row clicked. */
  function visibleLines() {
    const m = logData();
    const lines = arr(m && m.tail).map(str);
    const f = S.logFilter;
    let base = lines;
    if (f && f.kind === 'problem') base = arr(obj(arr(m && m.problems).find(p => str(p.key) === f.key)).lines).map(str);
    else if (f && f.kind === 'slot') base = lines.filter(l => l.includes(f.slot));
    const text = $('#log-filter').value.trim().toLowerCase();
    return { all: lines, base, shown: text ? base.filter(l => l.toLowerCase().includes(text)) : base, text };
  }

  function renderTail() {
    const m = logData();
    const { all, base, shown, text } = visibleLines();
    const f = S.logFilter;
    const key = [all.length, all[all.length - 1] || '', all[0], text, JSON.stringify(f), base.length, base[base.length - 1] || '',
      fileSource(), !!(m && m.game_running)].join('|');
    const bar = $('#log-itemfilter');
    bar.hidden = !f;
    if (f) { $('#log-itemfilter-name').textContent = f.label; $('#log-itemfilter-name').title = f.label; }
    if (key === lastTailKey) return;
    lastTailKey = key;
    const view = $('#logview');
    if (f && !base.length) {
      view.innerHTML = `<span class="l-empty">${f.kind === 'problem' ? 'No log lines were kept for this problem.' : 'No lines in this log mention it.'}</span>`;
    } else if (!all.length && !f) {
      view.innerHTML = `<span class="l-empty">${fileSource() ? 'This log is empty.' : m && m.game_running ? 'No log lines yet.' : 'The session log shows here while the game runs, and the last session after it ended.'}</span>`;
    } else if (!shown.length) {
      view.innerHTML = '<span class="l-empty">No lines match the filter.</span>';
    } else {
      view.innerHTML = shown.map(l => { const c = lineClass(l); return c ? `<span class="${c}">${esc(l)}</span>` : esc(l); }).join('\n');
    }
    const what = f ? (f.kind === 'problem' ? 'for this problem' : 'about this row') : '';
    $('#log-count').textContent = (f ? `${plural(base.length, 'line')} ${what}` : all.length ? plural(all.length, 'line') : '')
      + (text && (f ? base.length : all.length) ? `, ${shown.length} match` : '');
    if ($('#log-autoscroll').checked) view.scrollTop = view.scrollHeight;
    else if (f) view.scrollTop = 0;
  }

  function setLogFilter(f) {
    S.logFilter = f;
    lastTailKey = '';
    renderLog();
  }
  function filterProblem(key) {
    const p = arr(obj(logData()).problems).find(x => str(x.key) === key);
    if (!p) return;
    S.selProblem = key;
    if (S.logFilter && S.logFilter.kind === 'problem' && S.logFilter.key === key) setLogFilter(null);
    else setLogFilter({ kind: 'problem', key, label: str(p.title) });
  }
  function filterSlot(slot, variant) {
    S.selOnscreen = slot;
    if (S.logFilter && S.logFilter.kind === 'slot' && S.logFilter.slot === slot) setLogFilter(null);
    else setLogFilter({ kind: 'slot', slot, label: variant ? `${slot} = ${variant}` : slot });
  }
  function setLogSource(v) {
    if (!['this', 'previous', 'ue4ss'].includes(v)) v = 'this';
    S.logSource = v;
    store.set('logSource', v);
    S.logFilter = null;
    S.selProblem = null;
    S.selOnscreen = null;
    lastTailKey = lastLogKey = '';
    renderLog();
    lastFile = Date.now();
    loadFileLog();
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
  function dialog({ title, icon, html, buttons, wide }) {
    if (modal) modal.finish(null);
    hideCtx();
    return new Promise(resolve => {
      const layer = $('#modal-layer');
      const prevFocus = document.activeElement;
      layer.innerHTML = `<div class="dlg${wide ? ' wide' : ''}" role="dialog" aria-modal="true" aria-label="${esc(title)}">`
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

  const DELETE_CHOICE = (their) => '<div class="choices">'
    + `<label class="check"><input type="checkbox" name="del"><span>Also delete ${their} files from the library<br>`
    + `<span class="sub">Without this, the files stay in the library and Install puts ${their === 'its' ? 'it' : 'them'} back.</span></span></label></div>`;

  async function askRemove(id) {
    const m = modById(id);
    if (!m || m.state === 'working') return;
    const r = await dialog({
      title: 'Remove mod',
      icon: 'warn',
      html: `<p>Remove <span class="dlg-name">${esc(m.name || m.id)}</span> from the game?</p>` + DELETE_CHOICE('its'),
      buttons: [{ label: 'Remove', value: 'ok', default: true }, { label: 'Cancel', value: null, cancel: true }],
    });
    if (r.value !== 'ok') return;
    const res = await call('remove_mod', id, !!r.form.del);
    if (showError(res, 'Remove')) return;
    setMsg(`Removing ${m.name || m.id}...`);
    pollFast();
  }

  async function askRemoveMany(ids) {
    const mods = ids.map(modById).filter(m => m && m.state !== 'working');
    if (!mods.length) return;
    if (mods.length === 1) { askRemove(mods[0].id); return; }
    const r = await dialog({
      title: 'Remove mods',
      icon: 'warn',
      html: `<p>Remove these ${mods.length} mods from the game?</p>`
        + `<ul class="dlg-list sunken selectable">${mods.map(m => `<li>${esc(m.name || m.id)}</li>`).join('')}</ul>` + DELETE_CHOICE('their'),
      buttons: [{ label: `Remove ${mods.length} mods`, value: 'ok', default: true }, { label: 'Cancel', value: null, cancel: true }],
    });
    if (r.value !== 'ok') return;
    const res = await call('remove_mods', mods.map(m => m.id), !!r.form.del);
    if (showError(res, 'Remove')) return;
    mods.forEach(m => S.checked.delete(m.id));
    bulkMessage(res, 'Removing');
    renderModList();
    renderToolbar();
    pollFast();
  }

  function bulkMessage(res, verb) {
    const n = arr(res && res.jobs).length, errs = arr(res && res.errors);
    if (errs.length) setMsg(`${verb} ${plural(n, 'mod')}. Not queued: ${errs.map(e => `${str(e.id)} (${str(e.error).replace(/\.$/, '')})`).join('; ')}.`, 'error');
    else setMsg(`${verb} ${plural(n, 'mod')}...`);
  }

  async function reinstall(id) {
    const m = modById(id);
    if (!m || m.state === 'working') return;
    const res = await call('reinstall_mod', id);
    if (showError(res, m.state === 'not_installed' ? 'Install' : 'Reinstall')) return;
    setMsg(`${m.state === 'not_installed' ? 'Installing' : 'Reinstalling'} ${m.name || m.id}...`);
    pollFast();
  }

  async function reinstallMany(ids) {
    const mods = ids.map(modById).filter(m => m && m.state !== 'working');
    if (!mods.length) return;
    if (mods.length === 1) { reinstall(mods[0].id); return; }
    const res = await call('reinstall_mods', mods.map(m => m.id));
    if (showError(res, 'Reinstall')) return;
    bulkMessage(res, 'Reinstalling');
    pollFast();
  }

  async function reinstallAll() {
    const mods = S.mods.filter(m => m.state !== 'working');
    if (!mods.length) return;
    const r = await dialog({
      title: 'Reinstall all mods',
      icon: 'info',
      html: `<p>Prepare all ${plural(mods.length, 'mod')} for the in-game menu again?</p><p class="sub">Each one is a task in the list below. Large mods take a few minutes each. Close the game first.</p>`,
      buttons: [{ label: 'Reinstall all', value: 'ok', default: true }, { label: 'Cancel', value: null, cancel: true }],
    });
    if (r.value !== 'ok') return;
    const res = await call('reinstall_mods', mods.map(m => m.id));
    if (showError(res, 'Reinstall all')) return;
    bulkMessage(res, 'Reinstalling');
    pollFast();
  }

  function showHelp() {
    const v = str(obj(S.state).version);
    dialog({
      title: 'About E33 Wardrobe',
      icon: 'info',
      html: `<p><b>E33 Wardrobe${v ? ' ' + esc(v) : ''}</b></p>`
        + '<p>Add outfit mods here: drop archives on the window or use Add mods. Each mod gets rows in the in-game menu. In game, load a save and press Delete to open the menu.</p>'
        + '<p class="sub">Setup checks the game folder, UE4SS and the menu. Game log shows what the menu did while you play, and the last session after the game closed. '
        + 'Tick mods (or Ctrl+click, Shift+click) to reinstall or remove several. Right-click for Copy. Keys: F5 refreshes, Delete removes, Space ticks, Ctrl+C copies.</p>'
        + '<div class="help-links"><button class="btn" data-link="guide">User guide</button><button class="btn" data-link="nexus">Nexus page</button><button class="btn" data-link="github">GitHub</button></div>',
      buttons: [{ label: 'Close', value: null, default: true, cancel: true }],
    });
  }

  // ------------------------------------------------------------------ image viewer
  // A classic window over the app: the picture, zoom (Fit, 100%, mouse wheel), drag to pan,
  // Previous / Next through the mod's pictures, Esc closes. Shows the small swatch at once, then
  // the texture itself from texture_preview().
  let viewer = null, viewerReq = 0;      // viewerReq: the newest texture_preview call (stale answers are dropped)
  function viewerItems(d) {
    const out = [], seen = new Set();
    const add = (im, where) => {
      im = obj(im);
      if (!isImg(im.swatch) && !im.ref) return;
      const k = str(im.path) + '|' + str(im.swatch).slice(-40);
      if (seen.has(k)) return;
      seen.add(k);
      out.push(Object.assign({ where }, im));
    };
    arr(obj(d.skin).images).forEach(im => add(im, 'Skin'));
    const multi = isMulti(d.rows);
    arr(d.rows).forEach(r => arr(r.options).forEach(o => arr(o.images).forEach(im => { if (isImg(im.swatch)) add(im, `${rowLabel(r, multi)} · ${str(o.label)}`); })));
    return out;
  }
  function openViewer(d, start, extra) {
    let items = viewerItems(d);
    if (extra) {
      const k = str(extra.path) + '|' + str(extra.swatch).slice(-40);
      let i = items.findIndex(x => str(x.path) + '|' + str(x.swatch).slice(-40) === k);
      if (i < 0) { items = [Object.assign({}, extra)].concat(items); i = 0; }
      start = i;
    }
    if (!items.length) { setMsg('This mod has no pictures to show.'); return; }
    hideCtx();
    const layer = $('#viewer-layer');
    layer.innerHTML = '<div class="viewer" role="dialog" aria-modal="true" aria-label="Image">'
      + '<div class="dlg-title"><span id="v-title">Image</span><button class="dlg-x" data-v="close" title="Close (Esc)" aria-label="Close"></button></div>'
      + '<div class="viewer-bar">'
      + '<button class="btn small" data-v="prev" title="Previous picture (Left)">&lt; Previous</button>'
      + '<button class="btn small" data-v="next" title="Next picture (Right)">Next &gt;</button>'
      + '<span class="v-pos muted" id="v-pos"></span><span class="tb-sep"></span>'
      + '<button class="btn small" data-v="fit" title="Fit in the window (0)">Fit</button>'
      + '<button class="btn small" data-v="100" title="Actual pixels (1)">100%</button>'
      + '<button class="btn small v-sq" data-v="out" title="Zoom out (-)">-</button>'
      + '<button class="btn small v-sq" data-v="in" title="Zoom in (+)">+</button>'
      + '<span class="v-zoom" id="v-zoom"></span><span class="tb-fill"></span>'
      + '<button class="btn small" data-v="bigger" id="v-bigger" hidden></button></div>'
      + '<div class="viewer-stage" id="v-stage"><img id="v-img" alt="" draggable="false"><div class="v-wait" id="v-wait" hidden></div></div>'
      + '<div class="viewer-info selectable" id="v-info"></div></div>';
    layer.hidden = false;
    viewer = { d, items, i: Math.max(0, Math.min(items.length - 1, start || 0)), scale: 1, x: 0, y: 0, w: 0, h: 0, fit: true, res: null };
    const stage = $('#v-stage');
    stage.addEventListener('wheel', e => {
      e.preventDefault();
      const r = stage.getBoundingClientRect();
      zoomAt(viewer.scale * (e.deltaY < 0 ? 1.25 : 0.8), e.clientX - r.left, e.clientY - r.top);
    }, { passive: false });
    stage.addEventListener('mousedown', e => {
      if (e.button !== 0) return;
      e.preventDefault();
      const x0 = e.clientX, y0 = e.clientY, px = viewer.x, py = viewer.y;
      stage.classList.add('panning');
      const move = ev => { if (!viewer) return; viewer.x = px + ev.clientX - x0; viewer.y = py + ev.clientY - y0; viewer.fit = false; placeImg(); };
      const up = () => { removeEventListener('mousemove', move, true); removeEventListener('mouseup', up, true); stage.classList.remove('panning'); };
      addEventListener('mousemove', move, true);
      addEventListener('mouseup', up, true);
    });
    layer.onclick = e => {
      const b = e.target.closest('[data-v]');
      if (!b || b.disabled) return;
      viewerCmd(b.dataset.v);
    };
    showViewerItem();
  }
  function viewerCmd(c) {
    if (!viewer) return;
    const st = $('#v-stage');
    if (c === 'close') closeViewer();
    else if (c === 'prev' || c === 'next') {
      const n = viewer.items.length;
      viewer.i = (viewer.i + (c === 'next' ? 1 : n - 1)) % n;
      showViewerItem();
    } else if (c === 'fit') { viewer.fit = true; placeImg(); }
    else if (c === '100') zoomAt(1, st.clientWidth / 2, st.clientHeight / 2);
    else if (c === 'in') zoomAt(viewer.scale * 1.25, st.clientWidth / 2, st.clientHeight / 2);
    else if (c === 'out') zoomAt(viewer.scale * 0.8, st.clientWidth / 2, st.clientHeight / 2);
    else if (c === 'bigger') loadViewerPicture(2048);
  }
  function closeViewer() {
    if (!viewer) return;
    viewer = null;
    const layer = $('#viewer-layer');
    layer.hidden = true;
    layer.innerHTML = '';
    layer.onclick = null;
  }
  function zoomAt(s, cx, cy) {
    if (!viewer || !viewer.w) return;
    s = Math.max(0.05, Math.min(32, s));
    viewer.x = cx - (cx - viewer.x) * (s / viewer.scale);
    viewer.y = cy - (cy - viewer.y) * (s / viewer.scale);
    viewer.scale = s;
    viewer.fit = false;
    placeImg();
  }
  function placeImg() {
    if (!viewer) return;
    const img = $('#v-img'), st = $('#v-stage');
    if (!viewer.w) { img.style.display = 'none'; return; }
    img.style.display = '';
    if (viewer.fit) {
      const s = Math.min(st.clientWidth / viewer.w, st.clientHeight / viewer.h);
      viewer.scale = Math.max(0.05, Math.min(viewer.w < 256 ? 8 : 1, s));
      viewer.x = (st.clientWidth - viewer.w * viewer.scale) / 2;
      viewer.y = (st.clientHeight - viewer.h * viewer.scale) / 2;
    }
    img.style.width = viewer.w * viewer.scale + 'px';
    img.style.height = viewer.h * viewer.scale + 'px';
    img.style.left = Math.round(viewer.x) + 'px';
    img.style.top = Math.round(viewer.y) + 'px';
    img.classList.toggle('pixels', viewer.scale >= 2);
    $('#v-zoom').textContent = Math.round(viewer.scale * 100) + '%';
  }
  function setViewerPicture(url, w, h) {
    const img = $('#v-img');
    viewer.w = w;
    viewer.h = h;
    img.src = url;
    placeImg();
  }
  function viewerInfo() {
    const it = viewer.items[viewer.i], r = viewer.res;
    const parts = [];
    const tw = r && r.tex_width ? r.tex_width : it.width, th = r && r.tex_height ? r.tex_height : it.height;
    const fmt = (r && r.format) || it.format;
    parts.push(`<b>${esc(it.name || 'Picture')}</b>`);
    if (it.path) parts.push(esc(it.path));
    parts.push(`<span class="nw">${esc((num(tw) && num(th) ? `${tw} x ${th}` : 'size not recorded') + (fmt ? ' ' + fmt : ''))}</span>`);
    if (it.where) parts.push(`<span class="nw">${esc(it.where)}</span>`);
    let note = '';
    if (viewer.loading) note = 'Reading the texture from the prepared pak...';
    else if (r && r.ok === false) note = `Can't show the texture: ${str(r.error)}`;
    else if (r && r.note) note = str(r.note);
    else if (r && r.source === 'texture') note = `Shown at full size, ${r.width} x ${r.height}.`;
    $('#v-info').innerHTML = `<div>${parts.join('<span class="v-sep"> · </span>')}</div>` + (note ? `<div class="${r && r.ok === false ? 'c-warn' : 'muted'}">${esc(note)}</div>` : '');
    const big = $('#v-bigger');
    const can = r && r.source === 'texture' && Math.max(num(r.width), num(r.height)) < Math.min(2048, Math.max(num(tw), num(th)));
    big.hidden = !can;
    if (can) big.textContent = `Load ${Math.min(2048, Math.max(num(tw), num(th)))} px`;
  }
  function showViewerItem() {
    const it = viewer.items[viewer.i];
    $('#v-title').textContent = `Image - ${str(it.name) || 'picture'}`;
    $('#v-pos').textContent = `${viewer.i + 1} of ${viewer.items.length}`;
    $$('[data-v="prev"], [data-v="next"]').forEach(b => { b.disabled = viewer.items.length < 2; });
    viewer.res = null;
    viewer.fit = true;
    viewer.loading = false;
    $('#v-wait').hidden = true;
    if (isImg(it.swatch)) {
      const probe = new Image();
      probe.onload = () => {
        if (viewer && viewer.items[viewer.i] === it && !(viewer.res && viewer.res.ok && viewer.res.source === 'texture')) {
          setViewerPicture(it.swatch, probe.naturalWidth, probe.naturalHeight);
        }
      };
      probe.src = it.swatch;
    } else { viewer.w = 0; placeImg(); }
    loadViewerPicture(1024);
  }
  async function loadViewerPicture(px) {
    const it = viewer.items[viewer.i];
    const req = ++viewerReq;
    const v = viewer;
    if (!it.ref) { viewer.loading = false; $('#v-wait').hidden = true; viewer.res = { ok: true, source: 'swatch', note: 'Only this small swatch is saved for it.' }; viewerInfo(); return; }
    viewer.loading = true;
    $('#v-wait').hidden = false;
    $('#v-wait').textContent = 'Loading...';
    viewerInfo();
    const d = viewer.d;
    const res = await call('texture_preview', d.id, it.ref, px);
    if (viewer !== v || viewerReq !== req) return;
    viewer.loading = false;
    $('#v-wait').hidden = true;
    viewer.res = res && typeof res === 'object' ? res : { ok: false, error: 'No answer.' };
    if (viewer.res.ok && isImg(viewer.res.url)) {
      viewer.fit = true;
      setViewerPicture(viewer.res.url, num(viewer.res.width) || 64, num(viewer.res.height) || 64);
    }
    viewerInfo();
  }
  /** Open the viewer for a picture of the shown mod: an option's (opt index, image index) or the skin's. */
  function viewImage(kind, a, b) {
    const d = S.details[S.selected];
    if (!d || d.error) return;
    if (kind === 'skin') {
      const imgs = arr(obj(d.skin).images).map(obj).filter(im => isImg(im.swatch));
      const im = imgs[a] || { name: 'Skin swatch', swatch: arr(obj(d.skin).swatches)[a], where: 'Skin' };
      openViewer(d, 0, Object.assign({ where: 'Skin' }, im));
      return;
    }
    const row = arr(d.rows)[S.selRow];
    const o = obj(arr(row && row.options)[a]);
    const imgs = arr(o.images).map(obj);
    let im = imgs[b || 0];
    if (!im && isImg(o.swatch)) im = { name: str(o.label), swatch: o.swatch };
    if (!im) { setMsg(`${str(o.label)} has no pictures.`); return; }
    openViewer(d, 0, Object.assign({ where: `${rowLabel(row, isMulti(d.rows))} · ${str(o.label)}` }, im));
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

  /** Clipboard: navigator.clipboard where allowed, else a hidden textarea and execCommand (WebView2). */
  async function copyText(text) {
    S.lastCopy = text;
    try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* fall back */ }
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;left:-9999px;top:0';
    const prev = document.activeElement;
    document.body.appendChild(ta);
    ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    ta.remove();
    if (prev && prev.focus) prev.focus();
    return ok;
  }
  async function copyAndSay(text, what) {
    text = str(text);
    if (!text) { setMsg('Nothing to copy.'); return; }
    const n = text.split('\n').filter(Boolean).length;
    setMsg(await copyText(text) ? `Copied ${what || (n > 1 ? plural(n, 'line') : 'to the clipboard')}.` : "Couldn't use the clipboard.");
  }

  async function copyProblems() {
    if (fileSource()) {
      const d = logData();
      const probs = arr(d && d.problems);
      if (!probs.length) { setMsg('No problems to copy.'); return; }
      copyAndSay(`E33 Wardrobe: problems in ${LOG_FILE[fileSource()]}\n\n` + probs.map(problemText).join('\n\n') + '\n', 'the problems');
      return;
    }
    const t = await call('problems_text');
    if (typeof t !== 'string') { showError(t || { ok: false, error: 'no answer' }, 'Copy problems'); return; }
    if (!t.trim()) { setMsg('No problems to copy.'); return; }
    copyAndSay(t, 'the problems');
  }
  async function copyAllDetails(id) {
    const m = modById(id);
    let d = S.details[id];
    if (!d || d.error) { d = await call('mod_details', id); if (showError(d, 'Copy')) return; }
    copyAndSay(detailsText(d, m), `the details of ${str(m ? m.name || m.id : id)}`);
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
    lastFile = 0;
    await loadFileLog();
    setMsg('Ready');
  }

  const bulkIds = () => checkedMods().map(m => m.id);
  const ACTIONS = {
    'add-files': async () => afterAdd(await call('pick_files'), 'Add mods'),
    'add-folder': async () => afterAdd(await call('pick_folder'), 'Add folder'),
    'reinstall': () => { const ids = bulkIds(); if (ids.length) reinstallMany(ids); else if (S.selected !== null) reinstall(S.selected); },
    'remove': () => { const ids = bulkIds(); if (ids.length) askRemoveMany(ids); else if (S.selected !== null) askRemove(S.selected); },
    'reinstall-shown': () => { if (S.selected !== null) reinstall(S.selected); },
    'remove-shown': () => { if (S.selected !== null) askRemove(S.selected); },
    'reinstall-all': reinstallAll,
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
    'log-show-all': () => setLogFilter(null),
  };

  // ------------------------------------------------------------------ context menu
  function showCtx(x, y, items) {
    const menu = $('#ctxmenu');
    items = items.filter((it, i) => it !== '-' || (i > 0 && items[i - 1] !== '-' && i < items.length - 1));
    menu.innerHTML = items.map((it, i) => it === '-' ? '<div class="ms"></div>'
      : `<button class="mi" data-ci="${i}"${it.disabled ? ' disabled' : ''}>${esc(it.label)}</button>`).join('');
    menu.hidden = false;
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.max(2, Math.min(x, innerWidth - r.width - 4)) + 'px';
    menu.style.top = Math.max(2, Math.min(y, innerHeight - r.height - 4)) + 'px';
    menu.onclick = e => {
      const b = e.target.closest('[data-ci]');
      if (!b || b.disabled) return;
      hideCtx();
      items[+b.dataset.ci].run();
    };
  }
  function hideCtx() { const m = $('#ctxmenu'); if (m) m.hidden = true; }

  function modMenu(m) {
    const busy = m.state === 'working';
    const many = checkedMods();
    const items = [];
    if (many.length > 1 && S.checked.has(m.id)) {
      items.push({ label: `Reinstall selected (${many.length})`, run: () => reinstallMany(many.map(x => x.id)) });
      items.push({ label: `Remove selected (${many.length})...`, run: () => askRemoveMany(many.map(x => x.id)) });
      items.push('-');
    }
    items.push({ label: m.state === 'not_installed' ? 'Install' : 'Reinstall', disabled: busy, run: () => reinstall(m.id) });
    items.push({ label: 'Remove...', disabled: busy, run: () => askRemove(m.id) });
    items.push('-');
    items.push({ label: 'Open folder', run: () => openPath(m.id) });
    items.push('-');
    const sel = selectionText();
    if (sel) items.push({ label: 'Copy', run: () => copyAndSay(sel) });
    items.push({ label: many.length > 1 && S.checked.has(m.id) ? `Copy ${many.length} rows` : 'Copy row', run: () => copyAndSay((many.length > 1 && S.checked.has(m.id) ? many : [m]).map(modRowText).join('\n')) });
    items.push({ label: 'Copy name', run: () => copyAndSay(str(m.name || m.id), 'the name') });
    items.push({ label: 'Copy all details', run: () => copyAllDetails(m.id) });
    return items;
  }

  function detailsMenu(e) {
    const m = modById(S.selected);
    const d = S.details[S.selected];
    if (!m) return null;
    const sel = selectionText();
    const items = [{ label: 'Copy', disabled: !sel, run: () => copyAndSay(sel) }];
    if (d && !d.error) {
      const multi = isMulti(d.rows);
      const row = arr(d.rows)[S.selRow];
      const optTr = e.target.closest('#optlist tbody tr[data-opt]');
      const oi = optTr ? +optTr.dataset.opt : S.selOpt;
      const o = row && oi >= 0 ? obj(arr(row.options)[oi]) : null;
      const noteLi = e.target.closest('li[data-note]'), ovlLi = e.target.closest('li[data-overlap]');
      const pathEl = e.target.closest('[data-copy-path]');
      let paths = [], pathsLabel = '';
      if (noteLi) { paths = arr(obj(arr(d.notes)[+noteLi.dataset.note]).items); pathsLabel = obj(arr(d.notes)[+noteLi.dataset.note]).what === 'files' ? 'Copy file paths' : 'Copy the list'; }
      else if (ovlLi) { paths = arr(obj(arr(d.overlaps)[+ovlLi.dataset.overlap]).files); pathsLabel = 'Copy file paths'; }
      else if (pathEl) { paths = [pathEl.dataset.copyPath]; pathsLabel = 'Copy folder path'; }
      else if (o) { paths = arr(o.files).map(f => f.path); pathsLabel = `Copy file paths (${paths.length})`; }
      if (o) items.push({ label: 'Copy option text', run: () => copyAndSay(optionText(row, o, multi), `the option ${str(o.label)}`) });
      if (pathsLabel) items.push({ label: pathsLabel, disabled: !paths.length, run: () => copyAndSay(paths.join('\n')) });
      if (o && arr(o.images).length) items.push({ label: 'View pictures', run: () => viewImage('opt', oi, 0) });
      items.push('-');
      items.push({ label: 'Copy all details', run: () => copyAllDetails(m.id) });
    }
    items.push('-');
    items.push({ label: 'Open folder', run: () => openPath(m.id) });
    return items;
  }

  function logMenu(e) {
    const d = logData();
    const sel = selectionText();
    const pr = e.target.closest('#problemlist tbody tr[data-key]');
    const os = e.target.closest('#onscreenlist tbody tr[data-slot]');
    const items = [];
    if (pr) {
      const p = arr(d && d.problems).find(x => str(x.key) === pr.dataset.key);
      S.selProblem = pr.dataset.key;
      lastLogKey = '';
      renderLog();
      if (sel) items.push({ label: 'Copy', run: () => copyAndSay(sel) });
      items.push({ label: 'Copy problem', run: () => copyAndSay(problemText(p), 'the problem') });
      items.push({ label: 'Copy all problems', run: copyProblems });
      items.push('-');
      items.push({ label: S.logFilter && S.logFilter.key === pr.dataset.key ? 'Show all log lines' : 'Show its log lines', run: () => filterProblem(pr.dataset.key) });
      return items;
    }
    if (os) {
      const row = arr(d && d.on_screen).find(x => str(x.slot) === os.dataset.slot) || {};
      items.push({ label: 'Copy row', run: () => copyAndSay(`${str(row.slot)} = ${str(row.variant)}: ${num(row.shown)}/${num(row.total)}${row.worn ? ', worn' : ''}`) });
      items.push({ label: S.logFilter && S.logFilter.slot === os.dataset.slot ? 'Show all log lines' : 'Show its log lines', run: () => filterSlot(os.dataset.slot, os.dataset.variant) });
      return items;
    }
    if (e.target.closest('#logview, #log-itemfilter')) {
      const v = visibleLines();
      items.push({ label: 'Copy', disabled: !sel, run: () => copyAndSay(sel) });
      items.push({ label: `Copy shown lines (${v.shown.length})`, disabled: !v.shown.length, run: () => copyAndSay(v.shown.join('\n')) });
      if (v.shown.length !== v.all.length) items.push({ label: `Copy all lines (${v.all.length})`, disabled: !v.all.length, run: () => copyAndSay(v.all.join('\n')) });
      if (S.logFilter) { items.push('-'); items.push({ label: 'Show all lines', run: () => setLogFilter(null) }); }
      return items;
    }
    if (e.target.closest('#problem-detail') && sel) return [{ label: 'Copy', run: () => copyAndSay(sel) }];
    return null;
  }

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
    const rows = $$(listSel + ' tbody tr').filter(r => r.dataset.id !== undefined || r.dataset.key !== undefined || r.dataset.opt !== undefined || r.dataset.slot !== undefined);
    if (!rows.length) return;
    let i = rows.findIndex(r => r.classList.contains('sel'));
    i = delta === Infinity ? rows.length - 1 : delta === -Infinity ? 0 : Math.max(0, Math.min(rows.length - 1, (i < 0 ? (delta > 0 ? -1 : rows.length) : i) + delta));
    pick(rows[i]);
    const r = $$(listSel + ' tbody tr')[rows.indexOf(rows[i])];
    if (r) r.scrollIntoView({ block: 'nearest' });
  }

  /** Ctrl+C without a text selection: the focused list's selected row(s). */
  function copyFocused() {
    const a = document.activeElement;
    const id = a && a.id;
    if (id === 'modlist') {
      const many = checkedMods();
      const list = many.length ? many : [modById(S.selected)].filter(Boolean);
      if (list.length) copyAndSay(list.map(modRowText).join('\n'));
      return true;
    }
    if (id === 'optlist') {
      const d = S.details[S.selected], row = d && arr(d.rows)[S.selRow];
      const o = row && arr(row.options)[S.selOpt];
      if (o) copyAndSay(optionText(row, o, isMulti(d.rows)), `the option ${str(o.label)}`);
      return true;
    }
    if (id === 'problemlist') {
      const p = arr(obj(logData()).problems).find(x => str(x.key) === S.selProblem);
      if (p) copyAndSay(problemText(p), 'the problem');
      return true;
    }
    if (id === 'logview') { copyAndSay(visibleLines().shown.join('\n')); return true; }
    return false;
  }

  // ------------------------------------------------------------------ events
  let lastOptClick = {};
  function bind() {
    document.addEventListener('mousedown', e => {
      const grip = e.target.closest('.col-grip');
      if (grip && e.button === 0) { e.preventDefault(); e.stopPropagation(); startResize(e, grip); }
    }, true);
    document.addEventListener('dblclick', e => {
      const grip = e.target.closest('.col-grip');
      if (grip) { e.preventDefault(); fitColumn(grip); }
    });

    document.addEventListener('click', e => {
      if (!e.target.closest('#ctxmenu')) hideCtx();
      if (modal || viewer) return;
      if (resizing || Date.now() - resizedAt < 250 || e.target.closest('.col-grip')) return;
      const actEl = e.target.closest('[data-act]');
      if (actEl && !actEl.disabled) { const fn = ACTIONS[actEl.dataset.act]; if (fn) fn(actEl); return; }
      const tab = e.target.closest('.tab');
      if (tab) { selectTab(tab.dataset.tab); return; }
      if (e.target.id === 'chk-all') {
        const ids = shownMods().map(m => m.id);
        setChecked(ids, !ids.every(id => S.checked.has(id)));
        return;
      }
      const th = e.target.closest('#modlist th[data-sort]');
      if (th) {
        const k = th.dataset.sort;
        S.sort = S.sort.key === k ? { key: k, dir: -S.sort.dir } : { key: k, dir: 1 };
        store.set('sort', S.sort);
        renderModList();
        return;
      }
      const x = e.target.closest('.xtoggle');
      if (x) { const k = x.dataset.x; if (S.expanded.has(k)) S.expanded.delete(k); else S.expanded.add(k); renderDetails(); return; }
      const vimg = e.target.closest('[data-view-img]');
      if (vimg) { viewImage('opt', S.selOpt, +vimg.dataset.viewImg); return; }
      const vopt = e.target.closest('[data-view-opt]');
      if (vopt) { S.selOpt = +vopt.dataset.viewOpt; renderDetails(); viewImage('opt', S.selOpt, 0); return; }
      const vskin = e.target.closest('[data-view-skin]');
      if (vskin) { viewImage('skin', +vskin.dataset.viewSkin); return; }
      const modRow = e.target.closest('#modlist tbody tr[data-id]');
      if (modRow) {
        const m = modByKey(modRow.dataset.id);
        if (!m) return;
        if (e.target.closest('[data-chk]')) { S.anchor = m.id; setChecked([m.id], !S.checked.has(m.id)); $('#modlist').focus(); return; }
        if (e.shiftKey) { const anchor = S.anchor; checkRange(m.id); selectMod(m.id); S.anchor = anchor || m.id; return; }
        if (e.ctrlKey || e.metaKey) { setChecked([m.id], !S.checked.has(m.id)); selectMod(m.id); return; }
        selectMod(m.id);
        return;
      }
      const mt = e.target.closest('.minitab');
      if (mt) { S.selRow = +mt.dataset.row; S.selOpt = -1; renderDetails(); return; }
      const opt = e.target.closest('#optlist tbody tr[data-opt]');
      if (opt) {
        // a second click on the same option soon after: open its picture (the first click re-renders
        // the list, so the browser's dblclick may not reach the new row)
        const i = +opt.dataset.opt, now = Date.now();
        if (lastOptClick.i === i && now - lastOptClick.t < 450) { lastOptClick = {}; viewImage('opt', i, 0); return; }
        lastOptClick = { i, t: now };
        if (S.selOpt !== i) { S.selOpt = i; renderDetails(); }
        if ($('#optlist')) $('#optlist').focus();
        return;
      }
      const pr = e.target.closest('#problemlist tbody tr[data-key]');
      if (pr) { filterProblem(pr.dataset.key); return; }
      const os = e.target.closest('#onscreenlist tbody tr[data-slot]');
      if (os) { filterSlot(os.dataset.slot, os.dataset.variant); return; }
      const jr = e.target.closest('#tasklist tbody tr[data-job]');
      if (jr) {
        S.selJob = jr.dataset.job;
        const j = S.jobs.find(x => String(x.id) === S.selJob);
        if (j && j.mod_id !== null && j.mod_id !== undefined && modById(j.mod_id)) selectMod(j.mod_id, true);
        renderTasks();
      }
    });
    // Shift+click must not select text across the list
    document.addEventListener('mousedown', e => { if (e.shiftKey && e.target.closest('#modlist tbody')) e.preventDefault(); });

    document.addEventListener('change', e => {
      if (e.target.id === 'row-select') { S.selRow = +e.target.value; S.selOpt = -1; renderDetails(); }
      else if (e.target.id === 'opt-watch') saveWatch(e.target.checked);
      else if (e.target.id === 'log-source') setLogSource(e.target.value);
      else if (e.target.id === 'log-autoscroll' && e.target.checked) { const v = $('#logview'); v.scrollTop = v.scrollHeight; }
    });
    $('#log-filter').addEventListener('input', () => renderTail());
    $('#mod-filter').addEventListener('input', e => { S.modFilter = e.target.value; renderModList(); });

    document.addEventListener('contextmenu', e => {
      if (e.target.closest('input[type=text], textarea, select')) return;       // the system menu: cut, paste
      e.preventDefault();
      if (modal || viewer) return;
      const th = e.target.closest('.lv thead th');
      if (th) {
        const table = th.closest('table');
        showCtx(e.clientX, e.clientY, [{ label: 'Reset column widths', disabled: !store.get(colKey(table), null), run: () => resetColumns(table) }]);
        return;
      }
      const row = e.target.closest('#modlist tbody tr[data-id]');
      if (row) {
        const m = modByKey(row.dataset.id);
        if (!m) return;
        if (S.selected !== m.id) selectMod(m.id);
        showCtx(e.clientX, e.clientY, modMenu(m));
        return;
      }
      if (e.target.closest('#details-body')) {
        const optTr = e.target.closest('#optlist tbody tr[data-opt]');
        if (optTr && +optTr.dataset.opt !== S.selOpt) { S.selOpt = +optTr.dataset.opt; renderDetails(); }
        const items = detailsMenu(e);
        if (items) showCtx(e.clientX, e.clientY, items);
        return;
      }
      if (e.target.closest('#page-log')) {
        const items = logMenu(e);
        if (items) showCtx(e.clientX, e.clientY, items);
        return;
      }
      const sel = selectionText();
      if (sel) showCtx(e.clientX, e.clientY, [{ label: 'Copy', run: () => copyAndSay(sel) }]);
    });

    document.addEventListener('keydown', e => {
      if (viewer) {
        const k = { Escape: 'close', ArrowLeft: 'prev', ArrowRight: 'next', '+': 'in', '=': 'in', '-': 'out', '0': 'fit', '1': '100' }[e.key];
        if (k) { e.preventDefault(); viewerCmd(k); }
        else if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C') && selectionText()) { e.preventDefault(); copyAndSay(selectionText()); }
        return;
      }
      if (modal) {
        if (e.key === 'Escape') { e.preventDefault(); modal.cancel(); }
        else if (e.key === 'Enter' && !(document.activeElement && document.activeElement.tagName === 'BUTTON')) { e.preventDefault(); modal.accept(); }
        return;
      }
      if (e.key === 'Escape') {
        const ctxOpen = !$('#ctxmenu').hidden;
        hideCtx();
        if (ctxOpen) return;
        if (S.tab === 'log' && S.logFilter) { e.preventDefault(); setLogFilter(null); return; }
        if (S.tab === 'mods' && S.checked.size && document.activeElement && document.activeElement.id === 'modlist') { setChecked([...S.checked], false); return; }
      }
      if (e.key === 'F5' || (e.ctrlKey && (e.key === 'r' || e.key === 'R'))) { e.preventDefault(); refreshNow(); return; }
      const a = document.activeElement;
      const typing = a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.type !== 'checkbox';
      if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C') && !typing) {
        const sel = selectionText();
        if (sel) { e.preventDefault(); copyAndSay(sel); return; }
        if (copyFocused()) { e.preventDefault(); return; }
      }
      if (typing) return;
      if ((e.ctrlKey || e.metaKey) && (e.key === 'a' || e.key === 'A') && a && a.id === 'modlist') { e.preventDefault(); setChecked(shownMods().map(m => m.id), true); return; }
      if (e.key === ' ' && a && a.id === 'modlist' && S.selected !== null) { e.preventDefault(); setChecked([S.selected], !S.checked.has(S.selected)); return; }
      if (e.key === 'Delete' && S.tab === 'mods') {
        const ids = bulkIds();
        if (ids.length) { e.preventDefault(); askRemoveMany(ids); return; }
        if (S.selected !== null) { e.preventDefault(); askRemove(S.selected); return; }
      }
      const nav = { ArrowDown: 1, ArrowUp: -1, PageDown: 10, PageUp: -10, Home: -Infinity, End: Infinity }[e.key];
      if (nav === undefined || !a) return;
      if (a.id === 'modlist') {
        e.preventDefault();
        moveIn('#modlist', nav, r => { const m = modByKey(r.dataset.id); if (m) { selectMod(m.id); if (e.shiftKey) setChecked([m.id], true); } });
      } else if (a.id === 'problemlist') {
        e.preventDefault();
        moveIn('#problemlist', nav, r => {
          S.selProblem = r.dataset.key;
          if (S.logFilter && S.logFilter.kind === 'problem') { const p = arr(obj(logData()).problems).find(x => str(x.key) === r.dataset.key); S.logFilter = { kind: 'problem', key: r.dataset.key, label: str(p && p.title) }; lastTailKey = ''; }
          renderLog();
        });
      } else if (a.id === 'onscreenlist') {
        e.preventDefault();
        moveIn('#onscreenlist', nav, r => {
          S.selOnscreen = r.dataset.slot;
          if (S.logFilter && S.logFilter.kind === 'slot') { S.logFilter = { kind: 'slot', slot: r.dataset.slot, label: `${r.dataset.slot} = ${r.dataset.variant}` }; lastTailKey = ''; }
          renderLog();
        });
      } else if (a.id === 'optlist') {
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
    addEventListener('resize', () => { hideCtx(); if (viewer && viewer.fit) placeImg(); });

    makeSplitter($('#mods-splitter'), $('#mods-left'), 'x', 'split.mods', 360,
      () => $('#mods-split').offsetWidth - 380);
    makeSplitter($('#tasks-splitter'), $('#tasks'), 'y', 'split.tasks', 90,
      () => Math.max(90, $('#page-mods').offsetHeight - 220));
    $$('table[data-cols]').forEach(applyColumns);
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
    if (fileSource()) await loadFileLog();
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
      askRemoveMany: ids => askRemoveMany(ids || bulkIds()),
      check: (ids, on) => setChecked(arr(ids), on !== false),
      expand: key => { S.expanded.add(key); renderDetails(); },
      expandAll: () => { $$('.xtoggle').forEach(x => S.expanded.add(x.dataset.x)); renderDetails(); },
      viewImage,
      filterProblem,
      filterSlot,
      setLogSource,
      setColumns: (key, widths) => { store.set('cols.' + key, widths); $$(`table[data-cols="${key}"]`).forEach(applyColumns); },
      showCtxAt: (sel, x, y) => {
        const el = $(sel);
        if (!el) return false;
        const r = el.getBoundingClientRect();
        el.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: x === undefined ? r.left + 10 : x, clientY: y === undefined ? r.top + 8 : y }));
        return true;
      },
      copyAllDetails: id => copyAllDetails(id === undefined ? S.selected : id),
      lastCopy: () => S.lastCopy,
      showHelp,
      showDrop: on => { $('#drop-overlay').hidden = !on; },
      refresh: refreshNow,
      state: () => S,
    },
  };

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
