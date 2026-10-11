"""Check & repair: what the app made for each mod is still there and the in-game menu's list is
current. Repairs only rebuild what the app made (prepared files, variants.lua); downloads in the
library are never changed.

    check(view, lua_dir) -> {mods, options, problems: [Problem]}   (app/API.md)
"""
import os

from . import library


def _lua_quote(s):
    return '"' + s.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def prepared_dir(mod):
    """The mod's folder name under ~mods\\_E33Wardrobe, from its registry outputs."""
    for s in mod.get('slots', []):
        for v in s.get('variants', []):
            if v.get('output'):
                return os.path.basename(os.path.dirname(v['output'].replace('\\', os.sep)))
    return None


def misplaced(view):
    """Mods whose prepared folder is on the wrong side of Disable: [Problem] (move_back / move_out)."""
    out = []
    if not view.out_root or not view.disabled_dir:
        return out
    for mod in view.registry:
        name, d = mod['name'], prepared_dir(mod)
        if not d:
            continue
        live = os.path.isdir(os.path.join(view.out_root, d))
        parked = os.path.isdir(os.path.join(view.disabled_dir, d))
        if name not in view.disabled and parked and not live:
            out.append({'id': 'parked|' + name, 'level': 'error', 'mod': name, 'variant': None, 'where': name,
                        'problem': 'Its files are in the disabled folder',
                        'detail': f"The mod is enabled, but its prepared folder {d} is in Content\\E33Wardrobe_Disabled, so "
                                  'the game can\'t load it.', 'repair': 'Move them back into the game',
                        'action': {'kind': 'move_back', 'mod': name}})
        elif name in view.disabled and live:
            out.append({'id': 'loaded|' + name, 'level': 'warn', 'mod': name, 'variant': None, 'where': name,
                        'problem': 'Still loaded by the game',
                        'detail': f'The mod is disabled, but its prepared folder {d} is still in Paks\\~mods\\_E33Wardrobe, '
                                  'so the game loads it.', 'repair': 'Move them out of the game',
                        'action': {'kind': 'move_out', 'mod': name}})
    return out


def check(view, lua_dir):
    problems = misplaced(view)
    wrong_side = {p['mod'] for p in problems}
    n_mods = n_opts = 0
    reg_path = os.path.join(lua_dir, 'wardrobe_registry.json') if lua_dir else None
    lua_path = os.path.join(lua_dir, 'Scripts', 'variants.lua') if lua_dir else None
    try:
        with open(lua_path, encoding='utf-8', errors='replace') as f:
            lua_text = f.read()
    except (OSError, TypeError):
        lua_text = None
    for mod in view.registry:
        name = mod['name']
        if name in view.disabled or name in wrong_side:
            continue
        n_mods += 1
        folder = view.folder(name)
        rep = view.report(name)
        missing = []
        for s in mod.get('slots', []):
            for v in s.get('variants', []):
                n_opts += 1
                out = view.resolve_output(v.get('output'), parked=False)
                rel = v['id'].split('/', 1)[1] if '/' in v['id'] else ''
                if not out or not os.path.isfile(out[:-5] + '.ucas'):
                    missing.append((v, rel, os.path.basename(v.get('output') or '') or 'its file'))
        out_dir = os.path.basename(os.path.dirname(missing[0][0].get('output') or '')) if missing else ''
        for v, rel, fname in missing:
            label = library.option_label(os.path.basename(rel)) if rel else name
            problems.append({
                'id': 'out|' + v['id'], 'level': 'error', 'mod': name, 'variant': v['id'],
                'where': f'{name} \u00b7 {label}' if rel else name, 'problem': 'Prepared file missing',
                'detail': f'{fname} (or its .ucas) is gone from Paks\\~mods\\_E33Wardrobe\\{out_dir}. In game this '
                          'option shows nothing.',
                'repair': 'Prepare this option again' if folder else "Can't: the mod's folder is missing from the library",
                'action': {'kind': 'options', 'mod': name, 'rels': [rel]} if folder else None})
        shared = (rep.get(f'{name}/(shared)') or {}).get('output')
        if shared and not view.resolve_output(shared, parked=False):
            problems.append({
                'id': 'shared|' + name, 'level': 'error', 'mod': name, 'variant': None, 'where': name,
                'problem': 'Shared pak missing',
                'detail': f"{os.path.basename(shared)} holds the files the mod's options share. Without it some options "
                          'show grey or nothing.',
                'repair': 'Prepare the mod again' if folder else "Can't: the mod's folder is missing from the library",
                'action': {'kind': 'mod', 'mod': name} if folder else None})
        if lua_text is not None and _lua_quote(name) not in lua_text:
            problems.append({
                'id': 'menu|' + name, 'level': 'warn', 'mod': name, 'variant': None, 'where': name,
                'problem': "Not in the menu's list", 'detail': "variants.lua doesn't list this mod, so the menu "
                                                              "doesn't show it.",
                'repair': 'Update the list', 'action': {'kind': 'menu'}})
    if view.registry:
        if lua_text is None:
            problems.append({'id': 'menu|missing', 'level': 'error', 'mod': None, 'variant': None, 'where': 'In-game menu',
                             'problem': "The menu's list is missing", 'detail': 'Scripts\\variants.lua is missing.',
                             'repair': 'Write the list', 'action': {'kind': 'menu'}})
        else:
            try:
                stale = os.path.getmtime(lua_path) + 1 < os.path.getmtime(reg_path)
            except OSError:
                stale = False
            if stale:
                problems.append({'id': 'menu|stale', 'level': 'warn', 'mod': None, 'variant': None,
                                 'where': 'In-game menu', 'problem': 'Prepared with an older menu list',
                                 'detail': "The menu's list (variants.lua) is older than the wardrobe "
                                           '(wardrobe_registry.json).', 'repair': 'Update the list',
                                 'action': {'kind': 'menu'}})
    return {'mods': n_mods, 'options': n_opts, 'problems': problems}
