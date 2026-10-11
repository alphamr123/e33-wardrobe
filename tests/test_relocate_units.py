"""Small pure functions of the relocator (no game files, no retoc)."""
import json
import os
import shutil
import struct
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))
import e33_relocate  # noqa: E402
import e33fixes  # noqa: E402


def main():
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    # PC 2026-10-11: two mods by one author both ship /Game/chic_MyMod (a PrimaryAssetLabel)
    label = {'/Game/chic_MyMod': {'class': 'PrimaryAssetLabel', 'object': 'chic_MyMod'}}
    tex = {'/Game/Characters/Lune/Bikini/T_Shared': {'class': 'Texture2D', 'object': 'T_Shared'}}
    reg = [
        {'name': 'Mod A', 'shared': ['/game/chic_mymod', '/game/characters/lune/bikini/t_shared'],
         'slots': [{'variants': [{'classes': {**label, **tex}}]}]},
        {'name': 'Mod B', 'shared': ['/game/chic_mymod'], 'slots': [{'variants': [{'classes': dict(label)}]}]},
    ]
    check('a label asset in two mods\' shared paks is not a clash', e33_relocate.shared_clashes(reg) == {},
          e33_relocate.shared_clashes(reg))
    reg[1]['shared'].append('/game/characters/lune/bikini/t_shared')
    check('a texture in both still is', e33_relocate.shared_clashes(reg)
          == {'/game/characters/lune/bikini/t_shared': ['Mod A', 'Mod B']}, e33_relocate.shared_clashes(reg))
    # PC 2026-10-11: colour-only options (textures that replace the game's) showed no sizes: the
    # full texture read failed and nothing was recorded. The header alone still gives the size.
    tmp = tempfile.mkdtemp(prefix='e33units_')
    base = os.path.join(tmp, 'T_Colour')
    with open(base + '.uexp', 'wb') as f:          # platform data header only, no mips to follow
        f.write(struct.pack('<iiI', 2048, 1024, 0) + struct.pack('<i', 7) + b'PF_BC7\0' + b'\xff' * 8)
    entry, cands = {'object': 'T_Colour'}, []
    e33_relocate.texture_info(base, entry, cands)
    check('a texture the full read fails on still gets its size and format from the header',
          (entry.get('width'), entry.get('height'), entry.get('format')) == (2048, 1024, 'PF_BC7'), entry)
    check('  and the reason the full read failed is recorded', bool(entry.get('tex_error')), entry)
    shutil.rmtree(tmp, ignore_errors=True)
    # fixes.json applied to the wardrobe (Edit rows, hide, rules, disable)
    def v(vid, label):
        return {'id': vid, 'label': label, 'map': {'/Game/A/T_' + label: '/Game/ZWX/A/T_' + label},
                'classes': {'/Game/A/T_' + label: {'class': 'Texture2D', 'object': 'T_' + label, 'override': True}}}
    reg = [{'name': 'Herald', 'slots': [{'id': 'Herald/Potato', 'label': 'Herald: Potato', 'character': 'Lune',
                                          'variants': [v('Herald/Potato/A', 'Herald'), v('Herald/Potato/B', 'Ash'),
                                                       v('Herald/Potato/C', 'Cape')]}]},
           {'name': 'Other', 'slots': [{'id': 'Other/Main', 'label': 'Other: Main', 'variants': [v('Other/Main/A', 'On')]}]}]
    fx = {'version': 1, 'mods': {'herald': {           # mod names compare case-insensitively
        'rows': {'Herald/Potato': {'label': 'Herald coat'}},
        'new_rows': [{'id': 'Herald/+1', 'label': 'Herald extras', 'character': 'Lune'}],
        'options': {'Herald/Potato/B': {'hidden': True}, 'Herald/Potato/C': {'row': 'Herald/+1', 'label': 'Cape only'},
                    'Herald/Potato/A': {'label': 'Herald, full'}},
        'textures': {'Herald/Potato/A': {'/Game/Chars/MI_Body|Color_MAIN': '/Game/A/T_Herald'}},
        'materials': {'Herald/Potato/A': {'/Game/Chars/SK_Mesh|1': 'hide'}}},
        'Other': {'disabled': True}}}
    out = e33fixes.apply(reg, fx)
    sl = {s['id']: s for m in out for s in m['slots']}
    check('apply: a disabled mod is left out of the menu', [m['name'] for m in out] == ['Herald'], [m['name'] for m in out])
    check('  rows renamed, a new row with the moved option (renamed), a hidden option left out',
          sl['Herald/Potato']['label'] == 'Herald coat' and [x['label'] for x in sl['Herald/Potato']['variants']] == ['Herald, full']
          and [x['label'] for x in sl['Herald/+1']['variants']] == ['Cape only'] and sl['Herald/+1']['character'] == 'Lune', sl)
    check('  rules are attached to their variant with lower-case paths (parameter names keep their case)',
          sl['Herald/Potato']['variants'][0].get('fix') == {'tex': {'/game/chars/mi_body|Color_MAIN': '/Game/A/T_Herald'},
                                                          'mat': {'/game/chars/sk_mesh|1': 'hide'}}, sl['Herald/Potato']['variants'][0].get('fix'))
    check('  the registry itself is not changed', reg[0]['slots'][0]['label'] == 'Herald: Potato'
          and len(reg[0]['slots'][0]['variants']) == 3)
    tmp = tempfile.mkdtemp(prefix='e33units_')
    vpath = os.path.join(tmp, 'variants.lua')
    e33_relocate.write_variants_lua(vpath, out)
    try:
        from lupa import lua54
        L = lua54.LuaRuntime()
        data = L.execute(open(vpath, encoding='utf-8').read())
        rule = data[1].slots[1].variants[1].fix.mat['/game/chars/sk_mesh|1']
        check('variants.lua with rules loads in Lua and carries them', rule == 'hide' and data[1].slots[2].label == 'Herald extras', rule)
    except ImportError:
        print('SKIP variants.lua load check: lupa is not installed')
    shutil.rmtree(tmp, ignore_errors=True)
    # safety (audit 1.3.0): moves are all or nothing, an unreadable fixes.json is never wiped,
    # remove_bundle deletes only inside bundles\, names can't break variants.lua
    tmp = tempfile.mkdtemp(prefix='e33units_')
    src, dst, side = os.path.join(tmp, 'mods', 'M'), os.path.join(tmp, 'off', 'M'), os.path.join(tmp, 'off')
    os.makedirs(src)
    os.makedirs(dst)
    open(os.path.join(src, 'new.utoc'), 'w').close()
    open(os.path.join(dst, 'old.utoc'), 'w').close()
    real_rename, calls = os.rename, []

    def failing_rename(a_, b_):                     # the second rename (src -> dst) fails: a locked file
        calls.append((a_, b_))
        if len(calls) == 2:
            raise PermissionError('locked')
        return real_rename(a_, b_)
    os.rename = failing_rename
    try:
        e33fixes.move_dir(src, dst, aside=side)
        moved = True
    except OSError:
        moved = False
    finally:
        os.rename = real_rename
    check('move_dir: a failed move raises and leaves both folders as they were (old copy put back)',
          not moved and os.listdir(src) == ['new.utoc'] and os.listdir(dst) == ['old.utoc']
          and not [f for f in os.listdir(side) if f.startswith('.old-')], (os.listdir(src), os.listdir(dst), os.listdir(side)))
    e33fixes.move_dir(src, dst, aside=side)
    check('  a move that works replaces the old copy and leaves nothing aside', not os.path.exists(src)
          and os.listdir(dst) == ['new.utoc'] and not [f for f in os.listdir(side) if f.startswith('.old-')], os.listdir(side))
    lua = os.path.join(tmp, 'lua')
    os.makedirs(lua)
    with open(os.path.join(lua, 'fixes.json'), 'w', encoding='utf-8') as f:
        f.write('{"mods": {"A": {"disabled": true}')       # cut short
    try:
        with e33fixes.edit(lua) as data:
            data['mods']['B'] = {'disabled': True}
        refused = False
    except e33fixes.FixError:
        refused = True
    check('an unreadable fixes.json is not overwritten by an edit; a copy is kept',
          refused and open(os.path.join(lua, 'fixes.json'), encoding='utf-8').read().endswith('true}')
          and any(f.startswith('fixes.json.bad-') for f in os.listdir(lua)), os.listdir(lua))
    with open(os.path.join(lua, 'fixes.json'), 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'mods': {'A': {'bundles': [{'id': 'b1', 'utoc': 'x.utoc'},
                                                            {'id': 'b2', 'utoc': '../../evil/b2/x.utoc'}]}}}, f)
    open(os.path.join(lua, 'main.lua'), 'w').close()
    os.makedirs(os.path.join(tmp, 'evil', 'b2'))
    e33fixes.remove_bundle(lua, 'A', 'b1')
    e33fixes.remove_bundle(lua, 'A', 'b2')
    check('remove_bundle never deletes outside the bundles folder (the menu folder, ../)',
          os.path.isfile(os.path.join(lua, 'main.lua')) and os.path.isdir(os.path.join(tmp, 'evil', 'b2')), os.listdir(lua))
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        from lupa import lua54
        q = e33_relocate.lua_quote('a\rb\x01c"\\\n')
        check('lua_quote: control characters can\'t end the string', lua54.LuaRuntime().execute('return ' + q) == 'a\rb\x01c"\\\n', q)
    except ImportError:
        pass
    # the Tools zip holds every module the relocator imports (1.2.0/1.2.1 shipped without e33tex.py)
    import re as _re
    tools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools')
    need, todo = set(), ['e33_relocate']
    while todo:
        m = todo.pop()
        if m in need:
            continue
        need.add(m)
        src = open(os.path.join(tools, m + '.py'), encoding='utf-8').read()
        todo += [x for x in _re.findall(r'^\s*(?:import|from) (e33\w+)', src, _re.M) if x not in need]
    spec = __import__('importlib.util').util.spec_from_file_location(
        'build_release', os.path.join(os.path.dirname(tools), 'scripts', 'build_release.py'))
    br = __import__('importlib.util').util.module_from_spec(spec)
    spec.loader.exec_module(br)
    missing = sorted(m + '.py' for m in need if m + '.py' not in br.TOOL_FILES)
    check('the Tools zip lists every module the relocator imports', not missing, missing)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
