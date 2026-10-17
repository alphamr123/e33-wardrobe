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
    # zen headers: imported package names whose letter case differs from the real package (PC
    # 2026-10-16, Cheekier Chic: SK_Sciel_Chic_Skin vs the mod's SK_Sciel_Chic_skin)
    import e33utoc

    def batch(names, wide=()):
        strs = [n.encode('utf-16-le') if n in wide else n.encode('latin-1') for n in names]
        heads = b''.join(struct.pack('>H', (0x8000 if n in wide else 0) | len(n)) for n in names)
        return (struct.pack('<II', len(names), sum(map(len, strs))) + b'\0' * 8 + b'\x11' * 8 * len(names)
                + heads + b''.join(strs))

    def zen_header(own, imports, wide=(), ipn=None):
        """A UE5.4 zen package header: summary (own name = name map entry 0), name map, imported
        package names (a name batch, then an int32 FName number per name), 16 bytes of export map."""
        names = batch([own[0]])
        imp = batch([b for b, _n in imports], wide) + b''.join(struct.pack('<i', n) for _b, n in imports)
        ipn_off = 52 + len(names)
        size = ipn_off + len(imp) + 16
        summary = struct.pack('<IIII', 0, size, 0, own[1]) + b'\0' * 32 + struct.pack('<i', ipn if ipn is not None else ipn_off)
        return summary + names + imp + b'\xee' * 16

    imports = [('/Game/Sciel/SK_Sciel_Chic_Skin', 0), ('/Game/Bikini/MI_Body', 0), ('/Game/W/MI_Wide', 0),
               ('/Game/Mod/T_Skin', 3), ('/Game/Mod/SK_Foo', 3)]
    hdr = zen_header(('/Game/Mod/BP_Skin', 0), imports, wide={'/Game/W/MI_Wide'})
    real = {'/game/sciel/sk_sciel_chic_skin': '/Game/Sciel/SK_Sciel_Chic_skin', '/game/bikini/mi_body': '/Game/Bikini/MI_Body',
            '/game/w/mi_wide': '/Game/W/MI_wide',
            '/game/mod/t_skin': '/Game/Mod/T_skin', '/game/mod/t_skin_2': '/Game/Mod/T_Skin_2',   # T_Skin_2 is right as it is
            '/game/mod/sk_foo_2': '/Game/Mod/SK_foo_2'}
    new, ch = e33utoc.fix_import_case(hdr, real)
    got = [e33utoc.with_number(b, n) for _o, _s, _w, b, n in e33utoc.zen_imported_packages(new)]
    check('fix_import_case: the names that differ in case get the real spelling, numbers included',
          ch == [('/Game/Sciel/SK_Sciel_Chic_Skin', '/Game/Sciel/SK_Sciel_Chic_skin'), ('/Game/Mod/SK_Foo_2', '/Game/Mod/SK_foo_2')]
          and got[0] == '/Game/Sciel/SK_Sciel_Chic_skin' and got[4] == '/Game/Mod/SK_foo_2', (ch, got))
    check('  an import with an FName number is compared whole (T_Skin_2 is not respelled after T_skin)',
          got[3] == '/Game/Mod/T_Skin_2', got)
    check('  same length, only those two bytes changed (UTF-16 names are left alone)', len(new) == len(hdr)
          and sum(a != b for a, b in zip(new, hdr)) == 2, sum(a != b for a, b in zip(new, hdr)))
    check('  a name with no package of that spelling is not touched', e33utoc.fix_import_case(hdr, {})[1] == [])
    check('zen_package_name: the name the package gives itself, with its number',
          e33utoc.zen_package_name(hdr) == '/Game/Mod/BP_Skin'
          and e33utoc.zen_package_name(zen_header(('/Game/Mod/BP_Skin', 2), imports)) == '/Game/Mod/BP_Skin_1')

    ipn0 = struct.unpack_from('<i', hdr, 48)[0]

    def refused(buf):
        try:
            e33utoc.fix_import_case(buf, real)
            e33utoc.zen_package_name(buf)
            return False
        except e33utoc.UtocError:
            return True
        except Exception:                           # struct.error etc.: the relocator wouldn't skip it
            return False
    check('  not a zen package header, no imported names (offset out of range), or cut short: refused, '
          'never a struct.error (the relocator skips such chunks)',
          refused(b'\x00' * 40) and refused(zen_header(('/Game/Mod/BP_Skin', 0), imports, ipn=10 ** 6))
          and refused(hdr[:4] + struct.pack('<I', len(hdr) + 999) + hdr[8:])
          and refused(hdr[:ipn0] + struct.pack('<I', 1000) + hdr[ipn0 + 4:]),      # more names than bytes
          [refused(b'\x00' * 40), refused(zen_header(('/Game/Mod/BP_Skin', 0), imports, ipn=10 ** 6))])
    # 17 Oct audit: a UTF-16 name with a lone surrogate raised UnicodeDecodeError, and the whole
    # container's links went unread; it is read as it is, and the other names are still fixed
    lone = zen_header(('/Game/Mod/BP_Skin', 0), imports[:1] + [('/Game/W/MI_Wide', 0)], wide={'/Game/W/MI_Wide'})
    ws = lone.find('/Game/W/MI_Wide'.encode('utf-16-le'))
    lone = lone[:ws] + b'\x00\xd8' + lone[ws + 2:]                # first UTF-16 unit: an unpaired surrogate
    try:
        ch_lone = e33utoc.fix_import_case(lone, real)[1]
    except Exception as e:
        ch_lone = repr(e)
    check('  a UTF-16 name with an unpaired surrogate: no error, the other links are still fixed',
          ch_lone == [('/Game/Sciel/SK_Sciel_Chic_Skin', '/Game/Sciel/SK_Sciel_Chic_skin')], ch_lone)
    # the spellings the repair uses: the mod packages' own names only (PC 17 Oct audit: the game's
    # file index says Civil/Textures, its package is Civil/textures, and the mod links to the latter)
    names = e33_relocate.real_names([['/Game/A/SK_Body_skin', '/Game/B/MI_X'], ['/Game/B/mi_x', '/Game/C/T_Y']])
    check('real_names: the mod packages\' own names; a name spelled two ways is left out',
          names == {'/game/a/sk_body_skin': '/Game/A/SK_Body_skin', '/game/c/t_y': '/Game/C/T_Y'}, names)
    check('  needs_case_repair: only imports that differ in case from one of them',
          e33_relocate.needs_case_repair({'/Game/A/SK_Body_Skin', '/Game/C/T_Y', '/Game/Characters/Maelle/Civil/Textures/MI_Top'},
                                         names) == ['/Game/A/SK_Body_Skin'])
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
    # the zip ships a list of docs (the maintainer's notes stay out): every listed doc exists, every
    # tracked player doc is listed, and no shipped doc links to one left out
    docs = os.path.join(os.path.dirname(tools), 'docs')
    left_out = {'README.md', 'index.md', 'runbook.md'}
    on_disk = {f for f in os.listdir(docs) if f.endswith('.md')}
    gone = [f for f in br.DOC_FILES if f not in on_disk]
    unlisted = sorted(on_disk - set(br.DOC_FILES) - left_out)
    dead = sorted(f'{f} -> {t}' for f in br.DOC_FILES if f in on_disk
                  for t in _re.findall(r'\]\((?:\./)?([\w.-]+\.md)', open(os.path.join(docs, f), encoding='utf-8').read())
                  if t not in br.DOC_FILES)
    check('the Tools zip docs: all listed exist, none forgotten, no link to a doc left out',
          not gone and not unlisted and not dead, (gone, unlisted, dead))
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
