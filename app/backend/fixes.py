"""Fixes the user makes in the app: disable / enable, menu row edits, texture and material rules,
bundled files. They live in fixes.json in the menu folder (ue4ss\\Mods\\E33Wardrobe), written by
tools/e33fixes.py, which also rewrites variants.lua from the wardrobe registry plus the fixes
(write_menu). This module builds and reads the entries for the UI; shapes in app/API.md.
"""
import contextlib
import os
import re
import threading

from . import paths

ROW_KEYS = ('rows', 'new_rows', 'options', 'row_order', 'option_order')
_LOCK = threading.RLock()       # until tools/e33fixes.py has its own edit() lock


class FixError(Exception):
    """A plain sentence for the user."""


def tool():
    """tools/e33fixes.py, or FixError when it's missing."""
    paths.tools()                                   # puts tools/ on sys.path
    try:
        import e33fixes
    except ImportError:
        raise FixError('The fixes module (tools/e33fixes.py) is missing. Reinstall the app.')
    return e33fixes


def available():
    try:
        tool()
        return True
    except FixError:
        return False


def load(lua_dir):
    """fixes.json as a dict ({'version': 1, 'mods': {}} when missing or unreadable)."""
    if not lua_dir:
        return {'version': 1, 'mods': {}}
    try:
        return tool().load(lua_dir)
    except FixError:
        return {'version': 1, 'mods': {}}


def mod_entry(data, mod):
    return ((data or {}).get('mods') or {}).get(mod) or {}


def disabled_mods(data):
    return {m for m, e in ((data or {}).get('mods') or {}).items() if isinstance(e, dict) and e.get('disabled')}


def disabled_root(paks):
    try:
        return tool().disabled_root(paks)
    except FixError:
        return os.path.join(os.path.dirname(os.path.normpath(paks)), 'E33Wardrobe_Disabled')


@contextlib.contextmanager
def editing(lua_dir):
    """fixes.json for a read-modify-write under one lock, saved on exit: e33fixes.edit() (the lock
    the relocator and make_bundle share), else load + save under this module's lock."""
    T = tool()
    if hasattr(T, 'edit'):
        with T.edit(lua_dir) as data:
            yield data
        return
    with _LOCK:
        data = T.load(lua_dir)
        yield data
        T.save(lua_dir, data)


def edit(lua_dir, mod, change):
    """change(entry) in place under the fixes lock, then rewrite variants.lua. Returns the entry."""
    T = tool()
    with editing(lua_dir) as data:
        e = T.entry(data, mod, True)
        change(e)
        for k in [k for k, v in e.items() if v in ({}, [], None)]:
            del e[k]
        if not e:
            data.get('mods', {}).pop(mod, None)
    T.write_menu(lua_dir)
    return e


def _leaf(p):
    return (p or '').rstrip('/').rsplit('/', 1)[-1]


# ------------------------------------------------------------------------------ menu rows

def default_rows(described):
    """[(row id, label, character, [(variant id, label)])] of a describe() made without fixes."""
    return [(r['id'], r['label'], r.get('character'), [(o['id'], o['label']) for o in r['options']])
            for r in described['rows']]


def apply_rows(rows, e):
    """describe() rows as the in-game menu shows them after the entry's edits: renamed rows and
    options, new rows, moved options, order. Hidden options stay, marked 'hidden'. Edited items
    carry 'was' (the label before) / 'moved_from' (the row label before)."""
    if not e or not any(e.get(k) for k in ROW_KEYS):
        return rows
    by_id = {}
    out = []
    for r in rows:
        r = dict(r, options=[dict(o) for o in r['options']])
        lab = ((e.get('rows') or {}).get(r['id']) or {}).get('label')
        if lab and lab != r['label']:
            r['was'], r['label'] = r['label'], lab
        by_id[r['id']] = r
        out.append(r)
    for nr in e.get('new_rows') or []:
        if isinstance(nr, dict) and nr.get('id') and nr['id'] not in by_id:
            r = {'id': nr['id'], 'label': nr.get('label') or 'New row', 'character': nr.get('character'), 'options': [],
                 'new': True}
            by_id[r['id']] = r
            out.append(r)
    opts = e.get('options') or {}
    for r in list(out):
        for o in list(r['options']):
            fx = opts.get(o['id']) or {}
            if fx.get('label') and fx['label'] != o['label']:
                o['was'], o['label'] = o['label'], fx['label']
            if fx.get('hidden'):
                o['hidden'] = True
            dest = fx.get('row')
            if dest and dest != r['id'] and dest in by_id:
                r['options'].remove(o)
                o['moved_from'] = r.get('was') or r['label']
                by_id[dest]['options'].append(o)
    for rid, order in (e.get('option_order') or {}).items():
        r = by_id.get(rid)
        if r and isinstance(order, list):
            pos = {v: i for i, v in enumerate(order)}
            r['options'].sort(key=lambda o: pos.get(o['id'], len(pos)))
    order = e.get('row_order')
    if isinstance(order, list) and order:
        pos = {v: i for i, v in enumerate(order)}
        out.sort(key=lambda r: pos.get(r['id'], len(pos)))
    return [r for r in out if r['options']]


def editor_model(described, e):
    """The Edit rows dialog's tree: every row (also empty ones) with its options, current labels,
    the labels before, hidden flags."""
    base = default_rows(described)
    rows = [{'id': rid, 'label': lab, 'default': lab, 'character': ch, 'new': False,
             'options': [{'id': vid, 'label': ol, 'default': ol, 'hidden': False} for vid, ol in opts]}
            for rid, lab, ch, opts in base]
    by_id = {r['id']: r for r in rows}
    e = e or {}
    for rid, r in (e.get('rows') or {}).items():
        if rid in by_id and (r or {}).get('label'):
            by_id[rid]['label'] = r['label']
    for nr in e.get('new_rows') or []:
        if isinstance(nr, dict) and nr.get('id') and nr['id'] not in by_id:
            by_id[nr['id']] = {'id': nr['id'], 'label': nr.get('label') or 'New row', 'default': None,
                               'character': nr.get('character'), 'new': True, 'options': []}
            rows.append(by_id[nr['id']])
    home = {o['id']: r for r in rows for o in r['options']}
    for vid, fx in (e.get('options') or {}).items():
        r = home.get(vid)
        if not r:
            continue
        o = next(x for x in r['options'] if x['id'] == vid)
        if fx.get('label'):
            o['label'] = fx['label']
        o['hidden'] = bool(fx.get('hidden'))
        dest = fx.get('row')
        if dest and dest in by_id and dest != r['id']:
            r['options'].remove(o)
            by_id[dest]['options'].append(o)
    for rid, order in (e.get('option_order') or {}).items():
        if rid in by_id and isinstance(order, list):
            pos = {v: i for i, v in enumerate(order)}
            by_id[rid]['options'].sort(key=lambda o: pos.get(o['id'], len(pos)))
    order = e.get('row_order')
    if isinstance(order, list) and order:
        pos = {v: i for i, v in enumerate(order)}
        rows.sort(key=lambda r: pos.get(r['id'], len(pos)))
    default_home = {vid: rid for rid, _l, _c, opts in base for vid, _ol in opts}
    for r in rows:
        for o in r['options']:
            o['home'] = default_home.get(o['id'], r['id'])        # the row it is in without edits
    return {'mod': described['id'], 'rows': rows,
            'defaults': [{'id': rid, 'label': lab, 'character': ch, 'options': [{'id': v, 'label': ol} for v, ol in opts]}
                         for rid, lab, ch, opts in base]}


_NEW_ID = re.compile(r'/\+(\d+)$')


def rows_entry(described, model):
    """The fixes.json keys for the Edit rows dialog's result (model: {rows: [{id, label, new,
    character, options: [{id, label, hidden}]}]} in display order). Unknown ids are dropped."""
    mod = described['id']
    base = default_rows(described)
    default_label = {rid: lab for rid, lab, _c, _o in base}
    default_home = {vid: rid for rid, _l, _c, opts in base for vid, _ol in opts}
    default_opt = {vid: ol for _r, _l, _c, opts in base for vid, ol in opts}
    char_of_row = {rid: ch for rid, _l, ch, _o in base}
    for r in (model or {}).get('rows') or []:
        if r.get('new'):
            char_of_row[str(r.get('id') or '')] = r.get('character') if isinstance(r.get('character'), str) else None
    out = {'rows': {}, 'new_rows': [], 'options': {}, 'row_order': [], 'option_order': {}}
    seen_rows = []
    for r in (model or {}).get('rows') or []:
        rid = str(r.get('id') or '')
        label = str(r.get('label') or '').strip()
        if r.get('new'):
            if not rid.startswith(mod + '/+') or not _NEW_ID.search(rid):
                continue
            out['new_rows'].append({'id': rid, 'label': label or 'New row',
                                    'character': r.get('character') if isinstance(r.get('character'), str) else None})
        elif rid in default_label:
            if label and label != default_label[rid]:
                out['rows'][rid] = {'label': label}
        else:
            continue
        seen_rows.append(rid)
        order = []
        for o in r.get('options') or []:
            vid = str(o.get('id') or '')
            if vid not in default_home:
                continue
            fx = {}
            ol = str(o.get('label') or '').strip()
            if ol and ol != default_opt[vid]:
                fx['label'] = ol
            if rid != default_home[vid]:
                mine, theirs = char_of_row.get(default_home[vid]), char_of_row.get(rid)
                if mine and theirs and mine != theirs:
                    raise FixError(f'"{ol or default_opt[vid]}" is for {mine}; the row "{label}" is for {theirs}. '
                                   "An option can only move to a row of the same character (the menu dresses one "
                                   'character per row).')
                fx['row'] = rid
            if o.get('hidden'):
                fx['hidden'] = True
            if fx:
                out['options'][vid] = fx
            order.append(vid)
        natural = [vid for vid, _ol in next((b[3] for b in base if b[0] == rid), [])] if not r.get('new') else []
        natural = [v for v in natural if v in order] + [v for v in order if v not in natural]
        if order != natural:
            out['option_order'][rid] = order
    natural_rows = [b[0] for b in base] + [n['id'] for n in out['new_rows']]
    natural_rows = [x for x in natural_rows if x in seen_rows]
    if seen_rows != natural_rows:
        out['row_order'] = seen_rows
    return out


# ------------------------------------------------------------------------------ the Fixes list

def fix_items(e, described=None):
    """[{kind, text, sub, ref}] for the details' Fixes group; ref goes back to undo_fix()."""
    e = e or {}
    names = {}
    if described:
        for r in described.get('rows') or []:
            for o in r['options']:
                names[o['id']] = f"{r.get('was') or r['label']} · {o.get('was') or o['label']}"
    items = []
    if any(e.get(k) for k in ROW_KEYS):
        opts = e.get('options') or {}
        parts = []
        n = len(e.get('rows') or {})
        if n:
            ex = next(iter(e['rows'].values())).get('label')
            parts.append(f'{n} row{"s" if n != 1 else ""} renamed' + (f' (to "{ex}")' if n == 1 and ex else ''))
        if e.get('new_rows'):
            parts.append(f"{len(e['new_rows'])} new row{'s' if len(e['new_rows']) != 1 else ''}")
        for key, word in (('label', 'renamed'), ('row', 'moved'), ('hidden', 'hidden')):
            k = sum(1 for o in opts.values() if o.get(key))
            if k:
                parts.append(f'{k} option{"s" if k != 1 else ""} {word}')
        if e.get('row_order') or e.get('option_order'):
            parts.append('order changed')
        items.append({'kind': 'Menu rows', 'text': 'Rows and options edited', 'sub': ', '.join(parts) + '.',
                      'ref': {'kind': 'rows'}})
    for vid, rules in sorted((e.get('textures') or {}).items()):
        for key, val in sorted((rules or {}).items()):
            mat, _, param = key.partition('|')
            what = "the game's own texture" if val == 'game' else _leaf(val)
            items.append({'kind': 'Texture rule',
                          'text': (f'Empty texture links in {_leaf(mat)} use {what}' if param == '*'
                                   else f'{param} in {_leaf(mat)} uses {what}'),
                          'sub': names.get(vid, vid.split('/', 1)[-1]) + '.',
                          'ref': {'kind': 'texture', 'variant': vid, 'key': key}})
    for vid, rules in sorted((e.get('materials') or {}).items()):
        for key, val in sorted((rules or {}).items()):
            mesh, _, slot = key.partition('|')
            what = {'body': "the body's own material", 'hide': 'nothing (hidden)'}.get(val, _leaf(val))
            items.append({'kind': 'Material rule', 'text': f'Slot {slot} of {_leaf(mesh)} shows {what}',
                          'sub': names.get(vid, vid.split('/', 1)[-1]) + '.',
                          'ref': {'kind': 'material', 'variant': vid, 'key': key}})
    for b in e.get('bundles') or []:
        req = [_leaf(p) for p in b.get('requested') or []]
        extra = max(0, len(b.get('packages') or []) - len(req))
        size = b.get('size') or 0
        items.append({'kind': 'Bundled',
                      'text': ', '.join(req) + (f' and {extra} file{"s" if extra != 1 else ""} it uses' if extra else ''),
                      'sub': f"From {b.get('from_mod')}"
                             + (f" ({b['from_option'].split('/', 1)[-1]})" if b.get('from_option') else '')
                             + (f', {size / 1048576:.1f} MB' if size else '') + f", added {b.get('added', '')}. "
                             "The app's own copy: it stays when that mod is removed.",
                      'ref': {'kind': 'bundle', 'id': b.get('id')}})
    return items


def undo(lua_dir, mod, ref):
    """Undo one fix. Returns True when the mod must be prepared again (a bundle was removed)."""
    kind = (ref or {}).get('kind')
    if kind == 'bundle':
        tool().remove_bundle(lua_dir, mod, ref.get('id'))
        tool().write_menu(lua_dir)
        return True

    def change(e):
        if kind == 'rows':
            for k in ROW_KEYS:
                e.pop(k, None)
        elif kind in ('texture', 'material'):
            group = e.get('textures' if kind == 'texture' else 'materials') or {}
            rules = group.get(ref.get('variant')) or {}
            rules.pop(ref.get('key'), None)
            if not rules:
                group.pop(ref.get('variant'), None)
        else:
            raise FixError('Unknown fix.')
    edit(lua_dir, mod, change)
    return False


def undo_all(lua_dir, mod):
    """Every fix of a mod except disabled. Returns the bundle ids removed (the mod must be prepared again)."""
    T = tool()
    e = mod_entry(T.load(lua_dir), mod)
    bundles = [b.get('id') for b in e.get('bundles') or []]
    for b in bundles:
        T.remove_bundle(lua_dir, mod, b)

    def change(x):
        for k in ROW_KEYS + ('textures', 'materials', 'bundles'):
            x.pop(k, None)
    edit(lua_dir, mod, change)
    return bundles


def set_rule(lua_dir, mod, group, variant, key, value):
    """textures / materials rule; value None removes it."""
    def change(e):
        g = e.setdefault(group, {})
        rules = g.setdefault(variant, {})
        if value is None:
            rules.pop(key, None)
        else:
            rules[key] = value
        if not rules:
            g.pop(variant, None)
    edit(lua_dir, mod, change)
