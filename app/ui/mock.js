/* Fake backend for previewing the UI without Python. Loaded by app.js only when the URL has ?mock.
   index.html?mock&screen=<name> presets a state (see SCREENS at the bottom). Same shapes as API.md. */
(function () {
  'use strict';

  const params = new URLSearchParams(location.search);
  const SCREEN = params.get('screen') || '';

  // ---------------------------------------------------------------- swatches (generated PNGs)
  function rng(seed) {
    let a = seed >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const COL = {
    black: ['#45454c', '#16161a'], white: ['#f3f0ea', '#bdb7aa'], crimson: ['#b8293e', '#5a0e1b'],
    navy: ['#34497c', '#121c36'], ivory: ['#efe5cc', '#b3a47e'], night: ['#332c58', '#100d20'],
    gold: ['#e3bd57', '#8a6a1c'], teal: ['#35958f', '#134744'], silver: ['#d0d4da', '#787e88'],
    leather: ['#7a5536', '#2e1e12'], red: ['#c9433a', '#661511'], emerald: ['#349460', '#11442a'],
    plum: ['#83417a', '#3a1634'], sand: ['#dcc8a0', '#8f7a52'], slate: ['#66717e', '#2c3138'],
    rose: ['#dc94a3', '#8c4656'], amber: ['#de9f30', '#7a4f0c'], olive: ['#83853f', '#3b3c16'],
    charcoal: ['#4d4f54', '#1c1d20'], lilac: ['#bba1da', '#6a5390'], copper: ['#c58049', '#6a3a18'],
    mint: ['#a6dcc4', '#4f8a72'], burgundy: ['#86233a', '#3a0b16'], cobalt: ['#3666c9', '#13306d'],
    pearl: ['#eeeaf2', '#aaa3b3'], smoke: ['#929296', '#4a4a4e'], flower: ['#eaa8c4', '#a24f75'],
    herald: ['#6a1a16', '#1a0505'], blue: ['#4275bd', '#1a3563'], skin1: ['#ecc8ad', '#b88a6c'],
    skin2: ['#dcae90', '#9c6b4f'], cream: ['#f1e6c8', '#c2ad7c'], wine: ['#6e1730', '#2a0712'],
  };
  const swCache = {};
  function swatch(colour, kind, seed) {
    const key = colour + '|' + kind + '|' + seed;
    if (swCache[key]) return swCache[key];
    const [c1, c2] = COL[colour] || COL.smoke;
    const N = 48, cv = document.createElement('canvas');
    cv.width = cv.height = N;
    const g = cv.getContext('2d');
    const gr = g.createLinearGradient(0, 0, N * 0.35, N);
    gr.addColorStop(0, c1);
    gr.addColorStop(1, c2);
    g.fillStyle = gr;
    g.fillRect(0, 0, N, N);
    const r = rng(seed || 7);
    if (kind === 'weave') {
      g.globalAlpha = 0.13; g.strokeStyle = '#000';
      for (let i = -N; i < N * 2; i += 4) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i - N, N); g.stroke(); }
    } else if (kind === 'stripe') {
      g.globalAlpha = 0.2; g.fillStyle = '#fff';
      for (let y = 3; y < N; y += 9) g.fillRect(0, y, N, 2);
    } else if (kind === 'trim') {
      g.globalAlpha = 0.85; g.fillStyle = COL.gold[0];
      g.fillRect(0, N - 10, N, 3); g.fillRect(0, 6, N, 2);
    } else if (kind === 'lace') {
      g.globalAlpha = 0.18; g.fillStyle = '#fff';
      for (let y = 4; y < N; y += 8) for (let x = (y / 8) % 2 ? 4 : 0; x < N; x += 8) { g.beginPath(); g.arc(x, y, 1.6, 0, 7); g.fill(); }
    } else if (kind === 'petal') {
      g.globalAlpha = 0.3; g.fillStyle = '#fff';
      for (let i = 0; i < 6; i++) { g.beginPath(); g.ellipse(r() * N, r() * N, 5, 2.5, r() * 3, 0, 7); g.fill(); }
    }
    g.globalAlpha = 1;
    const im = g.getImageData(0, 0, N, N), d = im.data;
    for (let i = 0; i < d.length; i += 4) { const n = (r() - 0.5) * (kind === 'skin' ? 5 : 13); d[i] += n; d[i + 1] += n; d[i + 2] += n; }
    g.putImageData(im, 0, 0);
    const sh = g.createRadialGradient(N * 0.3, N * 0.25, 2, N * 0.5, N * 0.5, N * 0.78);
    sh.addColorStop(0, 'rgba(255,255,255,.14)');
    sh.addColorStop(1, 'rgba(0,0,0,.28)');
    g.fillStyle = sh;
    g.fillRect(0, 0, N, N);
    return (swCache[key] = cv.toDataURL('image/png'));
  }

  function bigPicture(colour, kind, side) {
    const N = 64, src = new Image();
    const cv = document.createElement('canvas');
    cv.width = cv.height = Math.min(side, 1024);
    const g = cv.getContext('2d');
    const [c1, c2] = COL[colour] || COL.smoke;
    const gr = g.createLinearGradient(0, 0, cv.width * 0.4, cv.height);
    gr.addColorStop(0, c1); gr.addColorStop(1, c2);
    g.fillStyle = gr; g.fillRect(0, 0, cv.width, cv.height);
    g.globalAlpha = 0.16; g.fillStyle = '#fff';
    const step = Math.max(8, cv.width / 32);
    for (let y = step / 2; y < cv.height; y += step) for (let x = (y / step) % 2 ? step / 2 : 0; x < cv.width; x += step) { g.beginPath(); g.arc(x, y, step / 5, 0, 7); g.fill(); }
    g.globalAlpha = 0.5; g.strokeStyle = '#000'; g.lineWidth = Math.max(2, cv.width / 128);
    for (let k = 1; k < 4; k++) { g.beginPath(); g.moveTo(0, cv.height * k / 4); g.bezierCurveTo(cv.width / 3, cv.height * k / 4 - step, cv.width * 2 / 3, cv.height * k / 4 + step, cv.width, cv.height * k / 4); g.stroke(); }
    void N; void src; void kind;
    return cv.toDataURL('image/png');
  }

  // ---------------------------------------------------------------- mods
  let seed = 11;
  function opt(label, colour, changes, textures, tags, extra) {
    return Object.assign({
      label, changes, textures: textures || '', tags: tags || [],
      swatch: colour ? swatch(colour, (extra && extra.kind) || 'weave', seed++) : null,
      ok: true, error: null, notes: [],
    }, extra || {});
  }
  const ROOT = 'C:\\Program Files (x86)\\Steam\\steamapps\\common\\Expedition 33';
  const LIB = ROOT + '\\Sandfall\\Content\\Paks_ModLibrary';

  function lune() {
    const rows = [
      { label: 'Expedition', options: [
        opt('Long Coat', 'navy', 'Outfit mesh, 3 materials', 'Outfit 2K', ['physics']),
        opt('Short Coat', 'navy', 'Outfit mesh, 3 materials', 'Outfit 2K'),
        opt('No Cape', 'blue', 'Outfit mesh, 2 materials', 'Outfit 2K'),
        opt('Dark Leather', 'leather', '3 materials', 'Outfit 2K'),
        opt('White Trim', 'white', '3 materials', 'Outfit 2K', [], { kind: 'trim' }),
        opt('Gold Trim', 'navy', '3 materials', 'Outfit 2K', [], { kind: 'trim' }),
        opt('Battle Worn', 'charcoal', 'Outfit mesh, 3 materials', 'Body 4K, outfit 2K', ['physics', 'own shaders'],
          { notes: ['Uses its own cloth settings for the cape.'] }),
      ] },
      { label: 'Civilian Skirt', options: [
        opt('Pleated', 'slate', 'Outfit mesh, 1 material', 'Outfit 2K', [], { kind: 'stripe' }),
        opt('Long Skirt', 'slate', 'Outfit mesh, 1 material', 'Outfit 2K'),
        opt('Short Skirt', 'slate', 'Outfit mesh, 1 material', 'Outfit 2K'),
        opt('Navy', 'navy', '1 material', 'Outfit 1K'),
      ] },
      { label: 'Bikini A', options: [
        opt('Black', 'black', '2 materials', 'Outfit 1K'),
        opt('White', 'white', '2 materials', 'Outfit 1K'),
        opt('Red', 'red', '2 materials', 'Outfit 1K'),
        opt('Sarong', 'sand', 'Outfit mesh, 2 materials', 'Outfit 2K', ['physics'], { kind: 'stripe' }),
      ] },
      { label: 'Clea', options: [
        opt('Long Skirt', 'crimson', 'Outfit mesh, 2 materials', 'Body 4K, outfit 2K', ['own shaders']),
        opt('Shorter Skirt', 'crimson', 'Outfit mesh, 2 materials', 'Body 4K, outfit 2K', ['physics', 'own shaders']),
        opt('No Gloves', 'crimson', 'Outfit mesh, 2 materials', 'Body 4K, outfit 2K'),
        opt('Ivory', 'ivory', '2 materials', 'Outfit 2K', [], { kind: 'lace' }),
        opt('Night', 'night', '2 materials', 'Outfit 2K', [], { kind: 'lace' }),
        opt('Red Ribbon', 'crimson', 'Outfit mesh, 2 materials', 'Outfit 2K', [], { kind: 'trim' }),
      ] },
      { label: 'Sirene', options: [
        opt('Gown', 'teal', 'Outfit mesh, 4 materials', 'Outfit 2K', ['physics']),
        opt('Short Gown', 'teal', 'Outfit mesh, 4 materials', 'Outfit 2K'),
        opt('No Veil', 'teal', 'Outfit mesh, 3 materials', 'Outfit 2K'),
        opt('Silver', 'silver', '4 materials', 'Outfit 2K', [], { kind: 'lace' }),
        opt('Pearl', 'pearl', '4 materials', 'Outfit 2K', [], { kind: 'lace' }),
      ] },
    ];
    return {
      id: 'Lune Outfit Options', name: 'Lune Outfit Options', characters: ['Lune'],
      replaces: rows.map(r => r.label), size: 64802523, state: 'ready',
      rows: rows.map((r, i) => Object.assign(r, { id: `Lune Outfit Options/${840 + i} ${r.label}`, character: 'Lune' })),
      skin: { has: true, text: 'Brings its own body textures (4K) for Lune. They show only with this mod\'s outfits.',
        swatches: [swatch('skin1', 'skin', 3), swatch('skin2', 'skin', 4)] },
      overlaps: [{ mod: 'Altered Flower Suit', text: "Both change Lune's body textures. In game, the one picked last shows." }],
      notes: [
        { level: 'warn', text: '3 options bring their own shaders. The first switch to them can take a few seconds.' },
        { level: 'info', text: 'Clea and Sirene options show only while Lune wears those outfits. Auto Wear in the menu puts them on.' },
      ],
    };
  }

  function flower() {
    const mk = (ch, col) => ({ label: 'Flower', character: ch, id: `Altered Flower Suit/${ch} Flower`, options: [
      opt('Altered', col, 'Outfit mesh, 2 materials', ch === 'Sciel' ? 'Outfit 2K' : 'Body 2K, outfit 2K', [], { kind: 'petal' }),
      opt('Altered, short', col, 'Outfit mesh, 2 materials', 'Outfit 2K', ['physics'], { kind: 'petal' }),
      opt('Altered, dark', 'wine', '2 materials', 'Outfit 2K', [], { kind: 'petal' }),
    ] });
    return {
      id: 'Altered Flower Suit', name: 'Altered Flower Suit', characters: ['Lune', 'Maelle', 'Sciel'],
      replaces: ['Flower'], size: 123731968, state: 'ready',
      rows: [mk('Lune', 'flower'), mk('Maelle', 'rose'), mk('Sciel', 'lilac')],
      skin: { has: true, text: 'Brings its own body textures (2K) for Lune and Maelle. They show only with this mod\'s outfits.',
        swatches: [swatch('skin1', 'skin', 5), swatch('skin2', 'skin', 6)] },
      overlaps: [{ mod: 'Lune Outfit Options', text: "Both change Lune's body textures. In game, the one picked last shows." }],
      notes: [],
    };
  }

  function herald() {
    return {
      id: 'Infernal Herald', name: 'Infernal Herald', characters: ['Lune'], replaces: ['Potato bag'],
      size: 43304755, state: 'not_installed',
      rows: [{ id: 'Infernal Herald/Potato bag', label: 'Potato bag', character: 'Lune', options: [
        opt('Herald', 'herald', 'Outfit mesh, 3 materials', 'Outfit 4K', ['physics']),
        opt('Herald, no horns', 'herald', 'Outfit mesh, 3 materials', 'Outfit 4K', ['physics']),
        opt('Herald, ash', 'charcoal', '3 materials', 'Outfit 4K'),
      ] }],
      skin: { has: false, text: '', swatches: [] }, overlaps: [], notes: [],
    };
  }

  function claudia() {
    return {
      id: 'Claudia Set', name: 'Claudia Set', characters: ['Maelle'], replaces: ['Civilian'],
      size: 50226381, state: 'ready',
      rows: [{ id: 'Claudia Set/Civilian', label: 'Civilian', character: 'Maelle', options: [
        opt('Style A', 'cream', 'Outfit mesh, 2 materials', 'Outfit 2K'),
        opt('Style A, black', 'black', 'Outfit mesh, 2 materials', 'Outfit 2K'),
        opt('Style B', 'cream', 'Outfit mesh, 3 materials', 'Outfit 2K', ['physics'], { kind: 'stripe' }),
        opt('Style B, black', 'black', 'Outfit mesh, 3 materials', 'Outfit 2K', ['physics'], { kind: 'stripe' }),
        opt('Style B, no jacket', 'cream', 'Outfit mesh, 2 materials', 'Outfit 2K'),
        opt('Style C', 'olive', 'Outfit mesh, 2 materials', 'Outfit 2K'),
      ] }],
      skin: { has: false, text: '', swatches: [] }, overlaps: [], notes: [],
    };
  }

  function chic() {
    const colours = ['black', 'white', 'crimson', 'navy', 'emerald', 'plum', 'sand', 'ivory', 'slate', 'rose', 'teal',
      'amber', 'olive', 'charcoal', 'lilac', 'copper', 'mint', 'burgundy', 'cobalt', 'pearl', 'smoke', 'gold'];
    const name = c => c[0].toUpperCase() + c.slice(1);
    // texture-only colour options: no swatch saved and no sizes recorded (an earlier build)
    const luneColor = colours.slice(0, 9).map((c, i) => opt(`${i < 2 ? 'Lace dress' : 'Plain dress'}: ${name(c)}`, null,
      i < 2 ? '6 textures' : '4 textures', 'Outfit (size ?)', [], { _tex: i < 2 ? 6 : 4, _nosize: true, _texmiss: i === 0,
        notes: i === 0 ? ["One texture link in MI_Body_Lune-alt points to a file the mod doesn't include; the menu fills it in game."] : [] }));
    const scielOpts = ['sleeveless, barefoot', 'sleeveless, boots', 'sleeves, barefoot', 'sleeves, boots'].map((v, i) =>
      opt(`Lace dress: ${v}`, ['plum', 'navy', 'teal', 'charcoal'][i], 'Outfit mesh, 2 materials, 4 textures, Blueprint',
        'Body 2K, outfit 2K', ['physics'], { kind: 'lace', _bp: 'BP_CharacterSkin_ScielOutfit_Chic',
          notes: ["One link in BP_CharacterSkin_ScielOutfit_Chic points to /Game/Characters/Sciel/Chic/MI_Chic_Trim_Old, which is in neither the game nor the mod; the game leaves it empty, as with the original mod."] }));
    const scielColor = colours.slice(10, 21).map((c, i) => opt(name(c), c, i < 4 ? 'Outfit mesh, 1 material' : '1 material', 'Outfit 2K', [], { kind: i % 2 ? 'weave' : 'stripe' }));
    scielColor[9] = opt('Pearl', null, '', '', [], { ok: false, error: 'Its files hold no outfit mesh or textures.' });
    scielColor[10] = opt('Smoke', null, '', '', [], { ok: false, error: 'Its files hold no outfit mesh or textures.' });
    const missing = scielOpts.map(o => `Sciel outfit \u00b7 ${o.label} (BP_CharacterSkin_ScielOutfit_Chic: 1 link to /Game/Characters/Sciel/Chic/MI_Chic_Trim_Old)`);
    return {
      id: 'Chic Variants', name: 'Chic Variants', characters: ['Lune', 'Sciel'], replaces: ['Chic'],
      size: 223346688, state: 'ready',
      rows: [
        { id: 'Chic Variants/Lune color', label: 'Lune color', character: 'Lune', options: luneColor },
        { id: 'Chic Variants/Sciel outfit', label: 'Sciel outfit', character: 'Sciel', options: scielOpts },
        { id: 'Chic Variants/Sciel color', label: 'Sciel color', character: 'Sciel', options: scielColor },
      ],
      skin: { has: true, text: "Brings its own body textures (2K) for Sciel. They show only with this mod's outfits.",
        swatches: [swatch('skin1', 'skin', 8)] },
      overlaps: [{ mod: 'Lune Outfit Options', text: "Both change Lune's body textures: T_Lune_Body_BaseColor, T_Lune_Body_Normal and 1 more. In game, the one picked last shows.",
        files: ['/Game/Characters/Heros/Lune/Body/T_Lune_Body_BaseColor', '/Game/Characters/Heros/Lune/Body/T_Lune_Body_Normal',
          '/Game/Characters/Heros/Lune/Body/T_Lune_Body_ORM'] }],
      notes: [
        { level: 'warn', text: "2 of 24 options couldn't be prepared and aren't in the menu: Sciel color \u00b7 Pearl and Sciel color \u00b7 Smoke.",
          items: ['Sciel color \u00b7 Pearl', 'Sciel color \u00b7 Smoke'], what: 'options' },
        { level: 'info', text: "4 options link to files the mod doesn't include: Sciel outfit \u00b7 Lace dress: sleeveless, barefoot, Sciel outfit \u00b7 Lace dress: sleeveless, boots, Sciel outfit \u00b7 Lace dress: sleeves, barefoot and 1 more.",
          items: missing, what: 'options' },
        { level: 'warn', text: '"Chic Variants Old" has 3 of this mod\'s new files (T_Chic_Trim_D, T_Chic_Trim_N and MI_Chic_Trim). Two versions of one mod? Keep only one in the library.',
          items: ['/Game/Characters/Sciel/Chic/MI_Chic_Trim', '/Game/Characters/Sciel/Chic/T_Chic_Trim_D', '/Game/Characters/Sciel/Chic/T_Chic_Trim_N'], what: 'files',
          compare: 'Chic Variants Old' },
      ],
    };
  }

  function feline() {
    const one = (label, colour) => ({ label, character: 'Lune', id: `Feline Sorceress/${label}`,
      options: [opt('on', colour, 'Body mesh, 2 materials', 'Body 2K', ['physics'], { kind: 'weave' })] });
    return {
      id: 'Feline Sorceress', name: 'Feline Sorceress', characters: ['Lune'], replaces: ['Base body'], size: 238026752, state: 'ready',
      rows: [one('Lune Feline Sorceress Barefoot', 'night'), one('Lune Sorceress No Ears No Tail', 'night'), one('Lune Feline Sorceress', 'plum')],
      skin: { has: true, text: 'Brings its own body textures (2K) for Lune.', swatches: [swatch('skin2', 'skin', 9)] },
      overlaps: [], notes: [],
    };
  }

  function generic(id, state) {
    return {
      id, name: id, characters: ['Maelle'], replaces: ['Gommage'], size: 31457280, state: state || 'ready',
      rows: [{ id: id + '/Gommage', label: 'Gommage', character: 'Maelle', options: [
        opt('Default', 'blue', 'Outfit mesh, 2 materials', 'Outfit 2K'),
        opt('Dark', 'black', '2 materials', 'Outfit 2K'),
        opt('Light', 'ivory', '2 materials', 'Outfit 2K'),
        opt('Short', 'blue', 'Outfit mesh, 2 materials', 'Outfit 2K', ['physics']),
      ] }],
      skin: { has: false, text: '', swatches: [] }, overlaps: [], notes: [],
    };
  }

  const slug = t => String(t).replace(/[^A-Za-z0-9]+/g, '_').replace(/^_|_$/g, '');
  function enrich(d) {
    const base = `/Game/Mods/${slug(d.id)}`;
    const skin = [];
    d.rows.forEach(r => r.options.forEach((o, i) => {
      o.id = `${d.id}/${r.label}/${slug(o.label)}_P`;
      const stem = `${slug(r.character || '')}_${slug(o.label)}`;
      const files = [], images = [];
      if (o.ok !== false) {
        if (/outfit mesh/i.test(o.changes)) files.push({ path: `${base}/Meshes/SK_${slug(r.character)}_${slug(r.label)}_Skin`, type: 'Outfit mesh', game: true });
        const mats = Number((/(\d+) materials?/.exec(o.changes) || [0, 0])[1]);
        for (let k = 0; k < mats; k++) files.push({ path: `${base}/Materials/MI_${stem}_${k + 1}`, type: 'Material', game: k === 0 });
        const big = /4K/.test(o.textures) ? 4096 : /1K/.test(o.textures) ? 1024 : 2048;
        const nt = o._tex || (o.textures ? 2 : 0);
        const kinds = ['BaseColor', 'Normal', 'ORM', 'Mask', 'Emissive', 'Detail'];
        for (let k = 0; k < nt; k++) {
          const body = /Body/.test(o.textures) && k === 1;
          const path = body ? `/Game/Characters/Heros/${r.character}/Body/T_${r.character}_Body_BaseColor` : `${base}/Textures/T_${stem}_${kinds[k]}`;
          files.push({ path, type: body ? 'Body texture' : 'Texture', game: !!o._nosize || body });
          const im = { ref: `${o.id}|${path}`, name: path.split('/').pop(), path, kind: body ? 'Body' : 'Outfit',
            width: o._nosize ? 0 : big, height: o._nosize ? 0 : big, format: o._nosize ? '' : (k === 1 && !body ? 'BC5' : 'BC7'),
            swatch: k === 0 ? o.swatch : body ? (d.skin.swatches[0] || null) : null };
          images.push(im);
          if (body && im.swatch && !skin.some(x => x.path === path)) skin.push(im);
        }
        if (o._bp) files.push({ path: `/Game/Characters/Sciel/Chic/${o._bp}`, type: 'Blueprint', game: true });
        if ((o.tags || []).includes('physics')) files.push({ path: `${base}/Physics/PA_${stem}`, type: 'Physics', game: false });
      }
      images.sort((a, b) => (b.swatch ? 1 : 0) - (a.swatch ? 1 : 0));
      o.files = files;
      o.images = images;
      o.missing = o._bp ? [{ in: `/Game/Characters/Sciel/Chic/${o._bp}`, name: o._bp, links: 1, texture: false,
        names: ['/Game/Characters/Sciel/Chic/MI_Chic_Trim_Old'],
        found_in: [{ mod: 'Chic Variants Old', option: 'Chic Variants Old/Lace dress/Trim', label: 'Trim',
          package: '/Game/Characters/Sciel/Chic/MI_Chic_Trim_Old' }] }] : [];
      if (o._texmiss) o.missing.push({ in: '/Game/Characters/Lune/Body/MI_Body_Lune-alt', name: 'MI_Body_Lune-alt', links: 1, texture: true, names: [], found_in: [] });
      o.rules = [];
      delete o._tex; delete o._nosize; delete o._bp; delete o._texmiss;
    }));
    if (d.skin.has) d.skin.images = skin.length ? skin : d.skin.swatches.map((s, i) => ({ ref: '', name: `T_Body_${i + 1}`, path: '', kind: 'Body', width: 2048, height: 2048, format: 'BC7', swatch: s }));
    d.overlaps.forEach(o => { if (!o.files) o.files = ['/Game/Characters/Heros/Lune/Body/T_Lune_Body_BaseColor']; });
    return d;
  }
  function finish(d) {
    d.fixes = d.fixes || [];
    d.disabled = d.state === 'disabled';
    d.folder = LIB + '\\' + d.id;
    d.options = d.rows.reduce((n, r) => n + r.options.length, 0);
    return enrich(d);
  }
  function summary(d) {
    const sw = [];
    d.rows.forEach(r => r.options.forEach(o => { if (o.swatch && sw.length < 4 && !sw.includes(o.swatch)) sw.push(o.swatch); }));
    return {
      id: d.id, name: d.name, state: d.state, characters: d.characters, replaces: d.replaces,
      options: d.options, rows: d.rows.length, size: d.size, swatches: sw, notes: d.notes.length, skin: !!d.skin.has,
      note_level: d.notes.some(n => n.level === 'warn') ? 'warn' : d.notes.length ? 'info' : null,
    };
  }

  // ---------------------------------------------------------------- state
  const okState = () => ({
    version: '1.2.0', first_run: false,
    game: { found: true, root: ROOT, paks: ROOT + '\\Sandfall\\Content\\Paks', store: 'Steam', source: 'detected' },
    ue4ss: { installed: true, version: '3.0.1-1125-g527a483b', ok: true, problem: null },
    menu: { installed: true, version: '1.2.0', bundled: '1.2.0', update: false },
    library: LIB, game_running: false, tools: { retoc: true, formats: ['zip', '7z', 'rar'] },
  });

  const M = {
    state: okState(),
    settings: { library: LIB, watch_game: true },
    mods: [lune(), flower(), herald(), claudia(), chic(), Object.assign(generic('Chic Variants Old'), { characters: ['Lune', 'Sciel'], replaces: ['Chic'] }),
      feline()].map(finish),
    culprit: { active: false },
    jobs: [],
    changed: 1,
    nextJob: 1,
    monitor: { watching: true, game_running: false, since: null, menu_active: false, last_activity: null, ended: null, date: null, problems: [], on_screen: [], tail: [] },
    files: {},
  };

  // ---------------------------------------------------------------- jobs (simulated)
  function stepsFor(nOpts, rowsTags) {
    return [
      { key: 'unpack', label: 'Unpacked', state: 'todo', detail: '' },
      { key: 'sort', label: 'Sorted by outfit', state: 'todo', detail: '', tags: [] },
      { key: 'install', label: 'Preparing for the in-game menu', state: 'todo', detail: '', progress: 0 },
    ];
  }
  function newJob(name, kind, size, mod, extra) {
    const j = Object.assign({ id: M.nextJob++, name, size, kind, status: 'waiting', steps: [], error: null, mod_id: null,
      _live: true, _mod: mod }, extra || {});
    if (kind === 'remove') {
      j.steps = [{ key: 'remove', label: 'Removed from the in-game menu', state: 'todo', detail: '' }];
      if (j._delete) j.steps.push({ key: 'delete', label: 'Deleted from the library', state: 'todo', detail: '' });
      j.mod_id = mod.id;
    } else j.steps = stepsFor();
    M.jobs.push(j);
    return j;
  }
  function advance(now) {
    const j = M.jobs.find(x => x._live && (x.status === 'waiting' || x.status === 'working'));
    if (!j) return;
    if (j.status === 'waiting') { j.status = 'working'; j._t0 = now; if (j._mod && j.kind !== 'add') setModState(j._mod.id, 'working'); }
    const t = (now - j._t0) / 1000;
    const mod = j._mod;
    if (j.kind === 'remove') {
      j.steps.forEach((s, i) => { s.state = t > (i + 1) * 0.8 ? 'done' : t > i * 0.8 ? 'run' : 'todo'; });
      if (t > j.steps.length * 0.8) {
        j.status = 'done';
        if (j._delete) M.mods = M.mods.filter(m => m.id !== mod.id); else setModState(mod.id, 'not_installed');
        M.changed++;
      }
      return;
    }
    const [u, so, ins] = j.steps;
    if (j._fail) {
      u.state = t > 1.2 ? 'fail' : 'run';
      if (t > 1.2) { u.detail = ''; j.status = 'failed'; j.error = 'No outfit files in this archive (no .utoc files).'; ins.state = 'todo'; M.changed++; }
      return;
    }
    const n = mod.options, tUnpack = 1.6, tSort = 0.6, per = 0.22;
    u.state = t >= tUnpack ? 'done' : 'run';
    if (t >= tUnpack) u.detail = `${n} options found`;
    if (t >= tUnpack) {
      so.state = t >= tUnpack + tSort ? 'done' : 'run';
      if (t >= tUnpack + tSort) {
        so.detail = `${plural(mod.rows.length, 'row')} in the menu`;
        so.tags = mod.rows.map(r => `${mod.characters.length > 1 ? r.character + ' · ' : ''}${r.label} · ${r.options.length}`);
      }
    }
    if (t >= tUnpack + tSort) {
      const k = Math.min(n, Math.floor((t - tUnpack - tSort) / per) + 1);
      const flat = [];
      mod.rows.forEach(r => r.options.forEach(o => flat.push(`${r.label} · ${o.label}`)));
      ins.state = 'run';
      ins.progress = k / n;
      ins.detail = `Option ${k} of ${n}: ${flat[k - 1]}`;
      if ((t - tUnpack - tSort) / per >= n) {
        ins.state = 'done'; ins.progress = 1; ins.detail = `${n} of ${n} ready`;
        j.status = 'done';
        j.mod_id = mod.id;
        mod.state = 'ready';
        if (!M.mods.includes(mod)) M.mods.push(mod);
        M.changed++;
      }
    }
  }
  function plural(n, w) { return `${n} ${n === 1 ? w : w + 's'}`; }
  function setModState(id, st) { const m = M.mods.find(x => x.id === id); if (m && m.state !== st) { m.state = st; M.changed++; } }
  function cleanName(p) {
    let b = String(p).split(/[\\/]/).pop();
    b = b.replace(/\.(zip|7z|rar)$/i, '').replace(/-\d+(-\d+)*$/, '').replace(/[_]+/g, ' ').trim();
    return b || 'New Mod';
  }

  // ---------------------------------------------------------------- API
  const clone = v => (v === undefined ? null : JSON.parse(JSON.stringify(v)));
  const api = {
    get_state: () => M.state,
    set_game_folder: path => {
      if (!/expedition|sandfall|paks/i.test(String(path))) return { ok: false, error: "That folder doesn't contain the game. Pick the folder that has Sandfall in it.", state: M.state };
      M.state = Object.assign(okState(), { first_run: false });
      M.state.game.source = 'picked';
      M.changed++;
      return { ok: true, state: M.state };
    },
    pick_game_folder: () => api.set_game_folder(ROOT),
    detect_game: () => {
      if (!M.state.game.found) return { ok: false, error: "The game wasn't found in the Steam or Game Pass folders. Use Browse.", state: M.state };
      return { ok: true, state: M.state };
    },
    pick_files: () => api.add_paths(['C:\\Users\\me\\Downloads\\Gommage Dress-512-1-0-1751000000.zip']),
    pick_folder: () => api.add_paths(['C:\\Users\\me\\Downloads\\Gommage Dress']),
    add_paths: paths => {
      if (!Array.isArray(paths) || !paths.length) return { ok: false, error: 'Nothing to add.' };
      const ids = paths.map(p => {
        const name = String(p).split(/[\\/]/).pop();
        const id = cleanName(p);
        const fail = /hair|fail/i.test(name);
        let mod = M.mods.find(m => m.id === id);
        if (!mod) mod = finish(generic(id, 'working'));
        return newJob(name, 'add', mod.size, mod, { _fail: fail }).id;
      });
      return { ok: true, jobs: ids };
    },
    poll: () => {
      advance(Date.now());
      return { busy: M.jobs.some(j => j.status === 'waiting' || j.status === 'working'), changed: M.changed, jobs: M.jobs.map(j => {
        const o = {}; Object.keys(j).forEach(k => { if (k[0] !== '_') o[k] = j[k]; }); return o;
      }) };
    },
    list_mods: () => M.mods.map(summary),
    mod_details: id => {
      const m = M.mods.find(x => x.id === id);
      return m ? m : { ok: false, error: `No mod named "${id}".` };
    },
    reinstall_mod: id => {
      const m = M.mods.find(x => x.id === id);
      if (!m) return { ok: false, error: `No mod named "${id}".` };
      return { ok: true, jobs: [newJob(m.name, 'reinstall', m.size, m).id] };
    },
    remove_mod: (id, del) => {
      const m = M.mods.find(x => x.id === id);
      if (!m) return { ok: false, error: `No mod named "${id}".` };
      return { ok: true, jobs: [newJob(m.name, 'remove', m.size, m, { _delete: !!del }).id] };
    },
    reinstall_mods: ids => {
      const jobs = [], errors = [];
      (ids || []).forEach(id => { const r = api.reinstall_mod(id); if (r.ok) jobs.push(...r.jobs); else errors.push({ id, error: r.error }); });
      return jobs.length ? { ok: true, jobs, errors } : { ok: false, error: 'No mods given.', errors };
    },
    remove_mods: (ids, del) => {
      const jobs = [], errors = [];
      (ids || []).forEach(id => { const r = api.remove_mod(id, del); if (r.ok) jobs.push(...r.jobs); else errors.push({ id, error: r.error }); });
      return jobs.length ? { ok: true, jobs, errors } : { ok: false, error: 'No mods given.', errors };
    },
    texture_preview: (id, ref, px) => {
      const m = M.mods.find(x => x.id === id);
      if (!m) return { ok: false, error: `No mod named "${id}".` };
      let im = null;
      m.rows.forEach(r => r.options.forEach(o => o.images.forEach(i => { if (i.ref === ref) im = i; })));
      (m.skin.images || []).forEach(i => { if (i.ref && i.ref === ref) im = i; });
      if (!im) return { ok: false, error: 'That image is gone.' };
      const tw = im.width || 2048, side = Math.min(px || 1024, tw);
      const colour = Object.keys(COL)[(ref.length * 7) % Object.keys(COL).length];
      return { ok: true, url: bigPicture(colour, im.kind === 'Body' ? 'skin' : 'lace', side), width: side, height: side,
        tex_width: tw, tex_height: im.height || tw, format: im.format || 'BC7', name: im.name, path: im.path, source: 'texture',
        note: side < tw ? `Shown at ${side} x ${side}, a smaller copy (mip) of the ${tw} x ${tw} texture.` : '' };
    },
    monitor_file: which => {
      const f = M.files[which];
      return f ? Object.assign({ which, exists: true }, f) : { which, exists: false, watching: false, game_running: false, since: null,
        menu_active: false, last_activity: null, ended: null, date: null, problems: [], on_screen: [], tail: [], files: [], lines: 0 };
    },
    set_disabled: (id, on) => {
      const m = M.mods.find(x => x.id === id);
      if (!m) return { ok: false, error: `No mod named "${id}".` };
      m.state = on ? 'disabled' : 'ready'; m.disabled = !!on; M.changed++;
      return { ok: true };
    },
    rows_editor: id => {
      const m = M.mods.find(x => x.id === id);
      const defaults = (m._defaults || m.rows).map(r => ({ id: r.id, label: r.label, character: r.character, options: r.options.map(o => ({ id: o.id, label: o.label })) }));
      const rows = m._editor || defaults.map(r => ({ id: r.id, label: r.label, default: r.label, character: r.character, new: false,
        options: r.options.map(o => ({ id: o.id, label: o.label, default: o.label, hidden: false, home: r.id })) }));
      return { ok: true, mod: id, rows, defaults };
    },
    save_rows: (id, model) => { const m = M.mods.find(x => x.id === id); m._saved = model; M.changed++; return { ok: true }; },
    texture_choices: (id, vid, material, param) => {
      const kinds = [['skin1', 'Lune_Body_Basecolor-alt', 'BC7', 2048], ['skin2', 'Lune_Body_Color-alt', 'BC7', 2048], ['blue', 'Lune_Body_Normal-alt', 'BC5', 2048],
        ['olive', 'Lune_Body_ORM-alt', 'BC7', 2048], ['black', 'T_Lace_Black_D', 'BC7', 2048], ['white', 'T_Lace_White_D', 'BC7', 2048],
        ['smoke', 'T_Lace_Mask', 'BC4', 1024], ['crimson', 'T_Plain_Crimson_D', 'BC7', 2048], ['navy', 'T_Plain_Navy_D', 'BC7', 2048],
        ['rose', 'Lune_Nails-alt', 'BC7', 512], ['slate', 'Lune_Body_Detail-alt', 'BC7', 1024]];
      const choices = kinds.map(([c, n, f, w], i) => ({ ref: `${vid}|/Game/Characters/Lune/Body/${n}`, name: n, path: `/Game/Characters/Lune/Body/${n}`,
        kind: /Body/.test(n) ? 'Body' : 'Outfit', width: w, height: w, format: f, swatch: swatch(c, i === 6 ? 'stripe' : 'skin', 40 + i) }));
      return { ok: true, variant: vid, material: '/Game/Characters/Lune/Body/MI_Body_Lune-alt', param: param || '*', current: null, choices };
    },
    set_texture_rule: () => ({ ok: true }),
    material_choices: (id, vid, mesh, slot) => ({ ok: true, variant: vid, mesh, slot, current: null, choices: [
      { value: 'body', label: "The body's own material", sub: 'What the character wore before' },
      { value: 'hide', label: 'Hidden', sub: 'The slot shows nothing' },
      { value: '/Game/Mods/Bikini_Set/Materials/MI_Sciel_Bikini-alt', label: 'MI_Sciel_Bikini-alt', sub: 'A material of this option' },
      { value: '/Game/Mods/Bikini_Set/Materials/MI_Sciel_Bikini_Trim-alt', label: 'MI_Sciel_Bikini_Trim-alt', sub: 'A material of this option' }] }),
    set_material_rule: () => ({ ok: true }),
    bundle_plan: (id, vid) => ({ ok: true, variant: vid, sources: [{ mod: 'Chic Variants Old', option: 'Chic Variants Old/Lace dress/Trim', label: 'Lace dress · Trim',
      package: '/Game/Characters/Sciel/Chic/MI_Chic_Trim_Old',
      files: [{ path: '/Game/Characters/Sciel/Chic/MI_Chic_Trim_Old', what: 'Material (the missing file)', size: 14336 },
        { path: '/Game/Characters/Sciel/Chic/T_Chic_Trim_Old_D', what: 'Texture it uses, 2048 x 2048 BC7', size: 5592405 },
        { path: '/Game/Characters/Sciel/Chic/T_Chic_Trim_Old_N', what: 'Texture it uses, 2048 x 2048 BC5', size: 5592405 }],
      into: ['Sciel outfit · Lace dress: sleeveless, barefoot', 'Sciel outfit · Lace dress: sleeveless, boots',
        'Sciel outfit · Lace dress: sleeves, barefoot', 'Sciel outfit · Lace dress: sleeves, boots'] }] }),
    bundle: (id) => { const m = M.mods.find(x => x.id === id); return { ok: true, jobs: [newJob(m.name, 'reinstall', m.size, m).id] }; },
    undo_fix: (id, ref) => { const m = M.mods.find(x => x.id === id); m.fixes = m.fixes.filter(f => JSON.stringify(f.ref) !== JSON.stringify(ref)); M.changed++; return { ok: true, jobs: [] }; },
    undo_all_fixes: id => { const m = M.mods.find(x => x.id === id); m.fixes = []; M.changed++; return { ok: true, jobs: [] }; },
    check_mods: () => ({ ok: true, mods: M.mods.length, options: M.mods.reduce((n, m) => n + m.options, 0), problems: [
      { id: 'out|Chic Variants/Sciel color/Teal_P', level: 'error', mod: 'Chic Variants', variant: 'Chic Variants/Sciel color/Teal_P',
        where: 'Chic Variants · Sciel color · Teal', problem: 'Prepared file missing',
        detail: 'Chic_Variants_Sciel_color_Teal_P.utoc (or its .ucas) is gone from Paks\\~mods\\_E33Wardrobe\\Chic_Variants. In game this option shows nothing.',
        repair: 'Prepare this option again', action: { kind: 'options', mod: 'Chic Variants', rels: ['Sciel color/Teal_P'] } },
      { id: 'menu|stale', level: 'warn', mod: null, variant: null, where: 'In-game menu', problem: 'Prepared with an older menu list',
        detail: "The menu's list (variants.lua) is older than the wardrobe (wardrobe_registry.json).", repair: 'Update the list', action: { kind: 'menu' } }] }),
    repair: ids => ({ ok: true, jobs: [], menu: true, moved: [], errors: [] }),
    reconcile: () => ({ ok: true, moved: [], errors: [] }),
    repair_option: () => ({ ok: true, jobs: [] }),
    compare_mods: (a, b) => ({ ok: true, shared: ['/Game/Characters/Sciel/Chic/MI_Chic_Trim', '/Game/Characters/Sciel/Chic/T_Chic_Trim_D', '/Game/Characters/Sciel/Chic/T_Chic_Trim_N'],
      mods: [{ id: a, files: ['Chic Variants-412-3-3-1760100000.rar'], version: '3.3', uploaded: '2026-10-01', added: '2026-10-09 18:20', options: 24, rows: 3, size: 223346688, state: 'ready' },
        { id: b, files: ['Chic Variants-412-2-1-1748200000.rar'], version: '2.1', uploaded: '2026-05-25', added: '2026-09-28 21:02', options: 4, rows: 1, size: 31457280, state: 'ready' }] }),
    culprit: (action, value) => {
      const c = M.culprit;
      if (action === 'status') return Object.assign({ ok: true }, c);
      if ((action === 'finish' || action === 'forget') && M.culpritStuck) {
        const left = M.culpritStuck; if (action === 'forget') { M.culprit = { active: false }; M.culpritStuck = null; }
        const errors = left.map(m => `${m}: a file in its prepared folder is in use.`);
        return { ok: action === 'forget', error: errors.join(' '), active: action !== 'forget', kept_off: null, errors, dropped: [], left };
      }
      if (action === 'finish') { M.culprit = { active: false }; return { ok: true, active: false }; }
      return Object.assign({ ok: true }, c);
    },
    install_menu: () => {
      if (!M.state.game.found) return { ok: false, error: 'Set the game folder first.', state: M.state };
      M.state.menu = { installed: true, version: M.state.menu.bundled, bundled: M.state.menu.bundled, update: false };
      M.changed++;
      return { ok: true, state: M.state };
    },
    open_path: what => { console.log('[mock] open_path', what); return { ok: true }; },
    open_url: name => { console.log('[mock] open_url', name); return { ok: true }; },
    monitor: () => M.monitor,
    problems_text: () => M.monitor.problems.map(p => `[${p.level}] ${p.first}-${p.last} x${p.count} ${p.title}\n  ${p.detail}\n  ${p.hint}`).join('\n'),
    get_settings: () => M.settings,
    save_settings: s => { M.settings = Object.assign({}, M.settings, s); M.monitor.watching = M.settings.watch_game !== false; return M.settings; },
  };

  window.E33Mock = {
    M,
    call(method, args) {
      const fn = api[method];
      return new Promise(resolve => setTimeout(() => {
        if (!fn) { resolve({ ok: false, error: `Unknown method ${method}` }); return; }
        try { resolve(clone(fn.apply(null, args || []))); } catch (e) { resolve({ ok: false, error: String(e) }); }
      }, 10));
    },
  };

  // ---------------------------------------------------------------- presets for screenshots
  function staticJob(o) { const j = Object.assign({ error: null, mod_id: null, _live: false }, o); j.id = M.nextJob++; M.jobs.push(j); return j; }

  function presetTasks() {
    const lo = M.mods.find(m => m.id === 'Lune Outfit Options');
    lo.state = 'working';
    staticJob({ name: 'Claudia Set-1287-1-2-1751287000.zip', size: 50226381, kind: 'add', status: 'done', mod_id: 'Claudia Set',
      notes: ['Style C has no physics asset of its own; it uses the game\'s.'], steps: [
      { key: 'unpack', label: 'Unpacked', state: 'done', detail: '6 options found' },
      { key: 'sort', label: 'Sorted by outfit', state: 'done', detail: '1 row in the menu', tags: ['Civilian · 6'] },
      { key: 'install', label: 'Preparing for the in-game menu', state: 'done', detail: '6 of 6 ready', progress: 1 },
    ] });
    staticJob({ name: "Lune's Outfit Options-337-2-1-1750919736.7z", size: 64802523, kind: 'add', status: 'working', steps: [
      { key: 'unpack', label: 'Unpacked', state: 'done', detail: '26 options found' },
      { key: 'sort', label: 'Sorted by outfit', state: 'done', detail: '5 rows in the menu',
        tags: ['Expedition · 7', 'Civilian Skirt · 4', 'Bikini A · 4', 'Clea · 6', 'Sirene · 5'] },
      { key: 'install', label: 'Preparing for the in-game menu', state: 'run', detail: 'Option 17 of 26: Clea · Shorter Skirt', progress: 0.64 },
    ] });
    staticJob({ name: 'Hair Pack-702-1-0-1751300000.zip', size: 8650752, kind: 'add', status: 'failed',
      error: 'No outfit files in this archive (no .utoc files).', steps: [
        { key: 'unpack', label: 'Unpacked', state: 'fail', detail: '' },
        { key: 'sort', label: 'Sorted by outfit', state: 'todo', detail: '' },
        { key: 'install', label: 'Preparing for the in-game menu', state: 'todo', detail: '' },
      ] });
    staticJob({ name: 'Chic Variants-412-1-3-1751100000.rar', size: 223346688, kind: 'reinstall', status: 'waiting', steps: [
      { key: 'unpack', label: 'Unpacked', state: 'todo', detail: '' },
      { key: 'sort', label: 'Sorted by outfit', state: 'todo', detail: '' },
      { key: 'install', label: 'Preparing for the in-game menu', state: 'todo', detail: '' },
    ] });
  }

  function presetRunning() {
    M.state.game_running = true;
    M.monitor = {
      watching: true, game_running: true, since: '21:03:10', menu_active: true, last_activity: '21:10:44',
      problems: [
        { key: 'missing:chic-sciel-pearl', level: 'error', title: 'A variant could not be loaded: Chic Variants · Sciel · Pearl',
          detail: "The game didn't find the variant's mesh. Its files in ~mods may be older than the menu's list.",
          hint: 'Repair it, then press Reload in the menu.', first: '21:07:30', last: '21:07:30', count: 1,
          fix: { kind: 'repair', mod: 'Chic Variants', variant: 'Chic Variants/Sciel color/Pearl_P' } },
        { key: 'watchdog', level: 'warn', title: 'The game stopped responding for 9 s',
          detail: 'The menu was idle, so the pause came from the game itself. During a long loading screen this is normal.',
          hint: 'If it happens outside loading screens, note the time and attach report.txt to a bug report.',
          first: '21:05:01', last: '21:06:10', count: 3 },
        { key: 'empty-material:Sciel:body:MI_Body_Sciel', level: 'info', title: "Filled an empty material slot on Sciel's outfit",
          detail: "The mod's mesh has no material for slot body (material 1), so the menu used MI_Body_Sciel (the body's material for slot body).",
          hint: "The mod's mesh leaves this slot to the game; the menu uses the body's own material so it isn't grey. If it looks wrong, send report.txt.",
          first: '21:08:40', last: '21:08:40', count: 1,
          fix: { kind: 'material', mod: 'Chic Variants', variant: 'Chic Variants/Sciel outfit/Lace_dress_sleeves_boots_P', mesh: '/game/mods/chic/sk_sciel_chic_skin',
            slot: 1, slot_name: 'body', current: '/Game/Characters/Heros/Sciel/Body/MI_Body_Sciel' } },
        { key: 'hidden:sciel-chic', level: 'info', title: 'Sciel · Chic: Velvet is hidden by a later pick',
          detail: 'Altered Flower Suit changes the same pieces and was picked later.',
          hint: 'Use Bring to front on that row in the menu.', first: '21:08:12', last: '21:08:12', count: 1 },
      ],
      on_screen: [
        { slot: 'Lune · Clea', variant: 'Shorter Skirt', shown: 1, total: 1, worn: true },
        { slot: 'Lune · Expedition', variant: 'Long Coat', shown: 0, total: 2, worn: false },
        { slot: 'Maelle · Civilian', variant: 'Style B, black', shown: 3, total: 3, worn: true },
        { slot: 'Sciel · Chic', variant: 'Teal', shown: 1, total: 3, worn: true },
        { slot: 'Sciel · Flower', variant: 'Altered', shown: 0, total: 1, worn: false },
      ],
      tail: tailLines(),
      ended: '21:10:44', date: '2026-10-11',
    };
    problemLines(M.monitor);
  }

  function problemLines(m) {
    const by = { 'missing:chic-sciel-pearl': /Pearl/, watchdog: /WATCHDOG/, 'hidden:sciel-chic': /hidden by Sciel/ };
    m.problems.forEach(p => { p.lines = by[p.key] ? m.tail.filter(l => by[p.key].test(l)) : []; });
  }

  function presetLast() {
    presetRunning();
    M.state.game_running = false;
    Object.assign(M.monitor, { game_running: false, ended: '21:10:44', date: '2026-10-11' });
    M.files.previous = { watching: false, game_running: false, since: '19:40:02', menu_active: true, last_activity: '20:02:31',
      ended: '20:02:31', date: '2026-10-11', on_screen: [], files: ['...\\live_log_previous.txt'], lines: 3,
      problems: [{ key: 'load:T_Old', level: 'warn', title: "Couldn't load T_Old", detail: "/Game/Mods/Old/T_Old didn't load, so that piece stays the game's own.",
        hint: 'Reinstall the mod it belongs to in the app.', first: '19:52:10', last: '19:52:10', count: 1, lines: ['19:52:10 log: could not load /Game/Mods/Old/T_Old.T_Old'] }],
      tail: ['19:40:02 session start 2026-10-11 19:40:02', '19:52:10 log: could not load /Game/Mods/Old/T_Old.T_Old', '20:02:31 key DEL'] };
  }

  function tailLines() {
    const L = [
      '21:03:10 session start: E33Wardrobe 1.2.0, UE4SS 3.0.1-1125-g527a483b',
      '21:03:10 settings: scoping on, auto apply on, auto wear on, record on',
      '21:03:11 registry: 5 mods, 12 slots, 91 variants',
      '21:03:11 selection: 5 picks loaded',
      '21:03:41 level load: Lumiere',
      '21:03:44 spawn Lune (BP_Lune_C_0)',
      '21:03:44 spawn Maelle (BP_Maelle_C_0)',
      '21:03:44 spawn Sciel (BP_Sciel_C_0)',
      '21:03:45 pass (spawn): 6 change(s)',
      '21:03:45   Lune    mesh set: Clea · Shorter Skirt (worn in place of Clea)',
      '21:03:45   Lune    material 0: MI_Clea_Body (own)',
      '21:03:45   Lune    material 1: MI_Clea_Skirt (own)',
      '21:03:45   Maelle  mesh set: Claudia Set · Style B, black (worn in place of Civilian)',
      '21:03:45   Sciel   material 2: MI_Chic_Teal',
      '21:03:45   Sciel   texture BaseColor: T_Chic_Teal_D',
      '21:03:45 check Lune · Clea · Shorter Skirt: 1/1 pieces on screen',
      '21:03:45 check Lune · Expedition · Long Coat: 0/2, made for Expedition; Lune wears Clea',
      '21:03:45 check Maelle · Civilian · Style B, black: 3/3 pieces on screen',
      '21:03:45 check Sciel · Chic · Teal: 1/3, 2 hidden by Sciel · Flower',
      '21:04:58 level load: Lumiere (streaming)',
      '21:05:01 WATCHDOG: the game thread has not run for 9 s; mod state: idle',
      '21:05:10 spawn Lune (BP_Lune_C_1)',
      '21:05:10 pass (spawn): 3 change(s)',
      '21:05:31 WATCHDOG: the game thread has not run for 7 s; mod state: idle',
      '21:06:10 WATCHDOG: the game thread has not run for 6 s; mod state: idle',
      '21:07:30 error: mesh not found: /Game/Mods/E33W/ChicVariants/Sciel/Pearl/SK_Chic',
      '21:07:30 pass (menu pick): 0 change(s)',
      '21:08:12 click Outfits > Sciel · Flower > On',
      '21:08:12 pass (menu pick): 2 change(s)',
      '21:08:12   Sciel   mesh set: Altered Flower Suit · Altered',
      '21:08:12 check Sciel · Chic · Teal: hidden by Sciel · Flower (picked later)',
      '21:10:31 key DEL: menu open (tab Outfits, Lune)',
      '21:10:36 click Outfits > Lune · Clea > Choose',
      '21:10:40 click Choose > Long Skirt',
      '21:10:40 pass (menu pick): 3 change(s)',
      '21:10:40   Lune    mesh set: Clea · Long Skirt',
      '21:10:40   Lune    material 0: MI_Clea_Body (own)',
      '21:10:40   Lune    material 1: MI_Clea_Skirt_Long (own)',
      '21:10:43 click Choose > Shorter Skirt',
      '21:10:44 pass (menu pick): 3 change(s)',
      '21:10:44   Lune    mesh set: Clea · Shorter Skirt',
      '21:10:44   Lune    material 0: MI_Clea_Body (own)',
      '21:10:44   Lune    material 1: MI_Clea_Skirt (own)',
      '21:10:44 check Lune · Clea · Shorter Skirt: 1/1 pieces on screen',
    ];
    return L;
  }

  const SCREENS = {
    setup_not_found: () => {
      M.state = Object.assign(okState(), {
        first_run: true,
        game: { found: false, root: null, paks: null, store: null, source: null },
        ue4ss: { installed: false, version: null, ok: false, problem: null },
        menu: { installed: false, version: null, bundled: '1.2.0', update: false },
        library: null,
      });
      M.mods = [];
      return ui => ui.selectTab('setup');
    },
    setup_ok: () => ui => ui.selectTab('setup'),
    setup_ue4ss_old: () => {
      M.state.ue4ss = { installed: true, version: '3.0.1-394-g437a8ff', ok: false,
        problem: "UE4SS is too old for the in-game menu. Get 'UE4SS - Experimental (Newer)'." };
      M.state.menu = { installed: true, version: '1.1.0', bundled: '1.2.0', update: true };
      return ui => ui.selectTab('setup');
    },
    mods_list: () => ui => ui.selectTab('mods'),
    mods_empty: () => { M.mods = []; return ui => ui.selectTab('mods'); },
    mods_details: () => async ui => { ui.selectTab('mods'); ui.selectMod('Lune Outfit Options'); await wait(120); ui.selectRow(3); ui.selectOption(1); },
    mods_chic: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120); ui.selectRow(1); ui.selectOption(19); },
    tasks_running: () => { presetTasks(); return async ui => { ui.selectTab('mods'); ui.selectMod('Claudia Set'); await wait(120); }; },
    gamelog_running: () => { presetRunning(); return ui => ui.selectTab('log'); },
    gamelog_idle: () => ui => ui.selectTab('log'),
    confirm_remove: () => async ui => { ui.selectTab('mods'); ui.selectMod('Lune Outfit Options'); await wait(120); ui.selectRow(3); ui.askRemove(); },
    drop_overlay: () => ui => { ui.selectTab('mods'); ui.showDrop(true); },
    mods_bulk: () => async ui => {
      ui.selectTab('mods');
      ui.setColumns('mods', [24, 156, 90, 112, 60, 56, 92]);
      ui.selectMod('Chic Variants');
      ui.check(['Chic Variants', 'Claudia Set', 'Feline Sorceress']);
      await wait(150);
    },
    mods_expanded: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120);
      ui.selectRow(1); ui.selectOption(0); await wait(50); ui.expandAll(); await wait(50);
      document.querySelector('#details-body').scrollTop = 200;
    },
    mods_lune_color: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120); ui.selectRow(0); ui.selectOption(0); },
    ctx_details: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120); ui.selectRow(1); ui.selectOption(1); await wait(50);
      ui.showCtxAt('#optlist tbody tr[data-opt="1"]', 260, 330);
    },
    ctx_modlist: () => async ui => {
      ui.selectTab('mods'); ui.check(['Chic Variants', 'Claudia Set']); ui.selectMod('Chic Variants'); await wait(120);
      ui.showCtxAt('#modlist tbody tr[data-id="Chic Variants"]', 120, 150);
    },
    image_viewer: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120); ui.selectRow(1); ui.selectOption(0); await wait(50);
      ui.viewImage('opt', 0, 0); await wait(300);
    },
    confirm_bulk_remove: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants');
      ui.check(['Chic Variants', 'Claudia Set', 'Feline Sorceress', 'Infernal Herald']); await wait(120); ui.askRemoveMany();
    },
    gamelog_filter: () => { presetRunning(); return async ui => { ui.selectTab('log'); await wait(150); ui.filterProblem('watchdog'); }; },
    gamelog_last: () => { presetLast(); return async ui => { ui.setLogSource('this'); ui.selectTab('log'); await wait(150); }; },
    gamelog_previous: () => { presetLast(); return async ui => { ui.setLogSource('previous'); ui.selectTab('log'); await wait(250); ui.filterProblem('load:T_Old'); }; },
    fx_tools_menu: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.toolsMenu(); },
    fx_repair: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(120); ui.openRepair(); await wait(200); },
    fx_repair_log: () => { presetRunning(); return async ui => { ui.selectTab('log'); await wait(150); ui.filterProblem('missing:chic-sciel-pearl'); }; },
    fx_compare: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150);
      document.querySelector('#details-body').scrollTop = 9999; await wait(50); ui.openCompare('Chic Variants', 'Chic Variants Old'); await wait(150);
    },
    fx_note_compare: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); document.querySelector('#details-body').scrollTop = 9999; },
    fx_edit_rows: () => {
      const m = M.mods.find(x => x.id === 'Infernal Herald');
      m.state = 'ready';
      const r = m.rows[0];
      m._editor = [
        { id: r.id, label: 'Herald coat', default: r.label, character: 'Lune', new: false, options: [
          { id: r.options[0].id, label: 'Herald', default: 'Herald', hidden: false, home: r.id },
          { id: r.options[1].id, label: 'Herald, no horns', default: 'Herald, no horns', hidden: false, home: r.id },
          { id: r.options[2].id, label: 'Herald, ash', default: 'Herald, ash', hidden: true, home: r.id }] },
        { id: 'Infernal Herald/+1', label: 'Herald extras', default: null, character: 'Lune', new: true, options: [
          { id: 'Infernal Herald/Potato bag/Cape_P', label: 'Cape only', default: 'Cape only', hidden: false, home: r.id }] }];
      m._defaults = [{ id: r.id, label: r.label, character: 'Lune', options: r.options.concat([{ id: 'Infernal Herald/Potato bag/Cape_P', label: 'Cape only' }]) }];
      return async ui => {
        ui.selectTab('mods'); ui.selectMod('Infernal Herald'); await wait(150); ui.openEditRows('Infernal Herald'); await wait(150);
        document.querySelector('[data-ed="rename"]').click(); await wait(50);
      };
    },
    fx_disabled: () => {
      const m = M.mods.find(x => x.id === 'Claudia Set');
      m.state = 'disabled'; m.disabled = true;
      return async ui => { ui.selectTab('mods'); ui.selectMod('Claudia Set'); await wait(150); ui.showCtxAt('#modlist tbody tr[data-id="Claudia Set"]', 150, 168); };
    },
    fx_culprit: () => {
      ['Infernal Herald', 'Claudia Set', 'Chic Variants Old'].forEach(id => { const m = M.mods.find(x => x.id === id); m.state = 'disabled'; m.disabled = true; });
      M.culprit = { active: true, round: 2, rounds_about: 3, on: ['Altered Flower Suit', 'Chic Variants'], off: ['Claudia Set', 'Chic Variants Old'],
        cleared: ['Lune Outfit Options', 'Feline Sorceress'], before: ['Infernal Herald'], found: null, started: '2026-10-11 20:02',
        history: [{ round: 1, on: ['Altered Flower Suit', 'Chic Variants', 'Claudia Set', 'Chic Variants Old'], off: ['Lune Outfit Options', 'Feline Sorceress'], answer: 'still' }] };
      return async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.openCulprit(); await wait(150); };
    },
    fx_culprit_stuck: () => {
      ['Claudia Set', 'Chic Variants Old'].forEach(id => { const m = M.mods.find(x => x.id === id); m.state = 'disabled'; m.disabled = true; });
      M.culprit = { active: true, round: 2, rounds_about: 3, on: ['Altered Flower Suit', 'Chic Variants'], off: ['Claudia Set', 'Chic Variants Old'],
        cleared: ['Lune Outfit Options', 'Feline Sorceress'], before: [], found: null, started: '2026-10-11 20:02', history: [] };
      M.culpritStuck = ['Chic Variants Old'];
      return async ui => { ui.selectTab('mods'); await wait(150); document.querySelector('[data-act="culprit-stop"]').click(); await wait(250); };
    },
    fx_culprit_done: () => {
      const m = M.mods.find(x => x.id === 'Feline Sorceress'); m.state = 'disabled'; m.disabled = true;
      M.culprit = { active: true, round: 3, rounds_about: 3, on: [], off: [], cleared: ['Altered Flower Suit', 'Chic Variants', 'Claudia Set', 'Chic Variants Old', 'Lune Outfit Options'],
        before: [], found: 'Feline Sorceress', started: '2026-10-11 20:02', history: [
          { round: 1, on: ['Altered Flower Suit', 'Chic Variants', 'Claudia Set'], off: ['Chic Variants Old', 'Lune Outfit Options', 'Feline Sorceress'], answer: 'gone' },
          { round: 2, on: ['Chic Variants Old', 'Lune Outfit Options'], off: ['Feline Sorceress'], answer: 'gone' }] };
      return async ui => { ui.selectTab('mods'); ui.selectMod('Feline Sorceress'); await wait(150); ui.openCulprit(); await wait(150); };
    },
    fx_texture: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.selectRow(0); ui.selectOption(0); await wait(50);
      ui.openTextureRule('Chic Variants', 'Chic Variants/Lune color/Lace_dress_Black_P', '/game/characters/lune/body/mi_body_lune-alt', 'Color_MAIN',
        '/Game/Characters/Lune/Body/Lune_Body_Basecolor-alt');
      await wait(150);
    },
    fx_option_fixes: () => async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.selectRow(0); ui.selectOption(0); },
    fx_material: () => { presetRunning(); return async ui => {
      ui.selectTab('log'); await wait(150); ui.filterProblem('empty-material:Sciel:body:MI_Body_Sciel'); await wait(50);
      ui.openMaterialRule('Chic Variants', 'Chic Variants/Sciel outfit/Lace_dress_sleeves_boots_P', '/game/mods/chic/sk_sciel_chic_skin', 1, 'body',
        '/Game/Characters/Heros/Sciel/Body/MI_Body_Sciel');
      await wait(150);
    }; },
    fx_log_fix: () => { presetRunning(); return async ui => { ui.selectTab('log'); await wait(150); ui.filterProblem('empty-material:Sciel:body:MI_Body_Sciel'); }; },
    fx_bundle: () => async ui => {
      ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.selectRow(1); ui.selectOption(0); await wait(50);
      ui.openBundle('Chic Variants', 'Chic Variants/Sciel outfit/Lace_dress_sleeveless_barefoot_P'); await wait(150);
    },
    fx_fixes: () => {
      const m = M.mods.find(x => x.id === 'Chic Variants');
      m.fixes = [
        { kind: 'Texture rule', text: 'Color_MAIN in MI_Body_Lune-alt uses Lune_Body_Color-alt', sub: 'Lune color · Lace dress: Black.', ref: { kind: 'texture' } },
        { kind: 'Bundled', text: 'MI_Chic_Trim_Old and 2 files it uses', sub: "From Chic Variants Old (Lace dress/Trim), 10.7 MB, added 2026-10-11 20:14. The app's own copy: it stays when that mod is removed.", ref: { kind: 'bundle', id: 'b1' } },
        { kind: 'Menu rows', text: 'Rows and options edited', sub: '2 options renamed.', ref: { kind: 'rows' } }];
      return async ui => { ui.selectTab('mods'); ui.selectMod('Chic Variants'); await wait(150); ui.selectRow(1); };
    },
    help: () => ui => ui.showHelp(),
  };
  const wait = ms => new Promise(r => setTimeout(r, ms));

  const after = SCREENS[SCREEN] ? SCREENS[SCREEN]() : null;
  document.addEventListener('e33ready', async () => {
    if (after) { await after(window.e33.ui); await wait(150); }
    window.__e33_screen_ready = true;
  });
})();
