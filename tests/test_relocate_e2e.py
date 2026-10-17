"""End-to-end relocator test against a fake game (no real E33 files needed).

usage: python -I tests/test_relocate_e2e.py <fake Paks dir> <base legacy dir> <retoc>

<fake Paks dir> holds global.utoc (from `retoc gen-script-objects`) + a base container built
from <base legacy dir> (Sandfall/Content/... incl. Environment/SM_BlueCube,
Materials/MI_BlueCube, Materials/M_Cube). The test builds a mod library with:
  Lune outfit/OutfitA_P   SM_BlueCube + MI_BlueCube   (mesh + its material)
  Lune outfit/OutfitB_P   SM_BlueCube importing /Game/ModCommon/MI_Shared (only in the common pak)
  Lune color/Red_P        MI_BlueCube only
  _Common_P               /Game/ModCommon/MI_Shared   (new asset, no game counterpart)
then runs e33_relocate.py and converts the result back with retoc to check every import.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.join(HERE, '..', 'tools')
sys.path.insert(0, TOOLS)
import e33legacy as L  # noqa: E402



def link_or_copy(src, dst):
    """A hard link (no copy of a big fixture), or a copy when the fixture is on another drive."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    paks, base, retoc = sys.argv[1:4]
    tmp = tempfile.mkdtemp(prefix='e33e2e_')
    # the relocator's work folder must be on the game's drive (it hard-links the game's paks):
    # a copy of the fixture Paks next to the work folder, whichever drive the fixture is on
    src_paks, paks = paks, os.path.join(tmp, 'Paks')
    shutil.copytree(src_paks, paks, copy_function=link_or_copy)
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    def legacy_copy(dst, pkgs, marker=None):
        for p in pkgs:
            rel = L.package_to_rel(p)
            for ext in ('.uasset', '.uexp', '.ubulk'):
                s = os.path.join(base, *rel.split('/')) + ext
                if os.path.isfile(s):
                    d = os.path.join(dst, *rel.split('/')) + ext
                    os.makedirs(os.path.dirname(d), exist_ok=True)
                    data = bytearray(open(s, 'rb').read())
                    if marker and ext == '.uexp':
                        mid = len(data) // 2
                        data[mid:mid + len(marker)] = marker
                    open(d, 'wb').write(bytes(data))

    def pack(legacy_dir, out_dir, stem):
        os.makedirs(out_dir, exist_ok=True)
        rc, out = run([retoc, 'to-zen', '--version', 'UE5_4', legacy_dir, os.path.join(out_dir, stem + '.utoc')])
        assert rc == 0, out

    lib = os.path.join(tmp, 'Lib', 'TestMod')
    # common pak: a NEW material at a mod-only path (relocate MI_BlueCube there, same length)
    shared_old, shared_new = '/Game/Materials/MI_BlueCube', '/Game/ModCommon/MI_BlueCube'   # same length
    assert len(shared_old) == len(shared_new)
    lc = os.path.join(tmp, 'leg_common')
    legacy_copy(lc, [shared_old])
    L.relocate_tree(lc, lc + '_r', {shared_old: shared_new})
    pack(lc + '_r', os.path.join(lib, '_Common_P'), 'Common_P')
    # OutfitA: mesh + material
    la = os.path.join(tmp, 'leg_a')
    legacy_copy(la, ['/Game/Environment/SM_BlueCube', '/Game/Materials/MI_BlueCube'], b'OUTFIT_A_MARK')
    pack(la, os.path.join(lib, 'Lune outfit', 'OutfitA_P'), 'OutfitA_P')
    # OutfitB: mesh whose material lives only in the common pak
    lb = os.path.join(tmp, 'leg_b')
    legacy_copy(lb, ['/Game/Environment/SM_BlueCube'], b'OUTFIT_B_MARK')
    L.relocate_tree(lb, lb + '_r', {shared_old: shared_new})        # repoint its import only
    pack(lb + '_r', os.path.join(lib, 'Lune outfit', 'OutfitB_P'), 'OutfitB_P')
    # Red color: material only
    lr = os.path.join(tmp, 'leg_r')
    legacy_copy(lr, ['/Game/Materials/MI_BlueCube'], b'RED_COLOR_MARK')
    pack(lr, os.path.join(lib, 'Lune color', 'Red_P'), 'Red_P')
    # a second color so 'Lune color' is a group
    lr2 = os.path.join(tmp, 'leg_r2')
    legacy_copy(lr2, ['/Game/Materials/MI_BlueCube'], b'BLUE_COLORMARK')
    pack(lr2, os.path.join(lib, 'Lune color', 'Blue_P'), 'Blue_P')
    # Tex_P: a material and a texture (the fake game's Texture2D), for texture sizes and swatches
    tex_pkg, tex_swatch = None, ''
    for dp, _ds, fs in sorted(os.walk(os.path.join(base, 'Sandfall', 'Content'))):
        for f in sorted(fs):
            if f.endswith('.uasset') and tex_pkg is None:
                try:
                    if L.read_package_info(os.path.join(dp, f))['main_class'] == 'Texture2D':
                        tex_pkg = L.rel_to_package(os.path.relpath(os.path.join(dp, f), base).replace(os.sep, '/'))[0]
                except Exception:
                    pass
    if tex_pkg:
        lt = os.path.join(tmp, 'leg_tex')
        legacy_copy(lt, ['/Game/Materials/MI_BlueCube', tex_pkg])
        pack(lt, os.path.join(lib, 'Lune color', 'Tex_P'), 'Tex_P')
    else:
        print('SKIP texture size / swatch checks: the base legacy dir has no Texture2D')

    # Flat_P: a pak whose file index has no folders (as some outfit mods' paks do). It overrides
    # MI_BlueCube and adds a mod-only material at /Game/ModFlat/MI_FlatOnly (same length trick).
    lf = os.path.join(tmp, 'leg_flat')
    legacy_copy(lf, ['/Game/Materials/MI_BlueCube'], b'FLAT_MARK_ABC')
    L.relocate_tree(lf, lf + '_x', {})                                   # plain copy
    flat_only = '/Game/ModFlatXY/MI_BlueCube'
    assert len(flat_only) == len(shared_old)
    lfo = os.path.join(tmp, 'leg_flatonly')
    legacy_copy(lfo, ['/Game/Materials/MI_BlueCube'])
    L.relocate_tree(lfo, lfo + '_r', {shared_old: flat_only})
    flat_root = os.path.join(tmp, 'leg_flat_root')
    os.makedirs(flat_root)
    for src_root in (lf + '_x', lfo + '_r'):                              # move files to the root
        for dp, _ds, fs in os.walk(src_root):
            for f in fs:
                tag = 'Only' if src_root.endswith('_r') else ''
                dst = os.path.join(flat_root, f if not tag else f)
                if tag:
                    sub = os.path.join(tmp, 'leg_flat_root2'); os.makedirs(sub, exist_ok=True)
                    shutil.copy(os.path.join(dp, f), os.path.join(sub, f))
                else:
                    shutil.copy(os.path.join(dp, f), dst)
    pack(flat_root, os.path.join(lib, 'Lune flat', 'Flat_P'), 'Flat_P')
    pack(os.path.join(tmp, 'leg_flat_root2'), os.path.join(lib, 'Lune flat', 'Flat_P'), 'FlatOnly_P')
    os.makedirs(os.path.join(lib, 'Lune flat', 'Flat2_P'))                # a sibling so 'Lune flat' is a group
    for f in os.listdir(os.path.join(lib, 'Lune color', 'Red_P')):
        shutil.copy(os.path.join(lib, 'Lune color', 'Red_P', f), os.path.join(lib, 'Lune flat', 'Flat2_P', f.replace('Red_P', 'Flat2_P')))
    idx = __import__('e33utoc').read_utoc(os.path.join(lib, 'Lune flat', 'Flat_P', 'Flat_P.utoc'))
    check('test pak really has a flat index', all('/' not in f for f in idx['files']), idx['files'])

    out, lua = os.path.join(tmp, 'out'), os.path.join(tmp, 'lua', 'E33Wardrobe')
    rc, log = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                   '--mod', lib, '--out', out, '--lua-dir', lua, '--work', tmp])
    print(log.strip()[-1500:])
    check('relocator exit code 0', rc == 0, rc)
    rep = json.load(open(os.path.join(out, 'relocate_report.json')))
    shared = rep.pop('TestMod/(shared)', None)
    check('shared pak written for mod-only assets', shared and shared_new.lower() in shared['packages'], shared)
    for vid, r in rep.items():
        check(f'{vid} relocated', 'error' not in r, r.get('error'))
    va = rep.get('TestMod/Lune outfit/OutfitA_P', {})
    vb = rep.get('TestMod/Lune outfit/OutfitB_P', {})
    check('OutfitA marks the mesh as a game override', va.get('classes', {}).get('/Game/Environment/SM_BlueCube', {}).get('override'))
    lua_txt = open(os.path.join(lua, 'Scripts', 'variants.lua')).read()
    check('variants.lua has the Lune outfit slot with character=Lune', 'character = "Lune"' in lua_txt)
    check('Lua mod installed with its in-game menu', all(os.path.isfile(os.path.join(lua, 'Scripts', f))
                                                        for f in ('main.lua', 'menu.lua', 'config.example.lua'))
                                                    and not os.path.exists(os.path.join(lua, 'Scripts', 'config.lua')))

    # Convert each relocated container back against the fake game + common pak and inspect imports.
    for vid, r in rep.items():
        if 'error' in r:
            continue
        comp = os.path.join(tmp, 'comp_' + str(abs(hash(vid))))
        os.makedirs(comp)
        for f in os.listdir(paks):
            if f.endswith(('.utoc', '.ucas')):
                shutil.copy(os.path.join(paks, f), comp)
        for f in ('.utoc', '.ucas'):
            shutil.copy(r['output'][:-5] + f, os.path.join(comp, 'zz_' + os.path.basename(r['output'])[:-5] + '_9_P' + f))
        if shared:
            for f in ('.utoc', '.ucas'):
                shutil.copy(shared['output'][:-5] + f, os.path.join(comp, 'zz_shared_7_P' + f))
        back = os.path.join(comp, 'back')
        rc, o = run([retoc, 'to-legacy', '--version', 'UE5_4', '--no-shaders', '--no-script-objects', comp, back])
        check(f'{vid}: converts back', rc == 0, o[-300:])
        for old, new in r['map'].items():
            f = os.path.join(back, *L.package_to_rel(new).split('/')) + '.uasset'
            if not os.path.isfile(f):
                check(f'{vid}: {new} present', False)
                continue
            info = L.read_package_info(f)
            bad = [x for x in info['imported_packages'] if x.startswith('/Engine/UnknownPackage')]
            check(f'{vid}: {os.path.basename(new)} imports resolve', not bad, info['imported_packages'])
            if old == '/Game/Environment/SM_BlueCube':
                # own material -> its relocated copy; a material from the common pak -> its original
                # (mod-only) path, provided by the shared pak and swapped per variant at runtime
                want = r['map'].get('/Game/Materials/MI_BlueCube') or (shared_new if vid.endswith('OutfitB_P') else None)
                check(f'{vid}: mesh imports {want}', want in info['imported_packages'], info['imported_packages'])
            uexp = open(f[:-7] + '.uexp', 'rb').read()
            mark = {'OutfitA_P': b'OUTFIT_A_MARK', 'OutfitB_P': b'OUTFIT_B_MARK', 'Red_P': b'RED_COLOR_MARK'}.get(vid.rsplit('/', 1)[1])
            if mark and old in ('/Game/Environment/SM_BlueCube', '/Game/Materials/MI_BlueCube') and not (
                    vid.endswith('OutfitA_P') and old.endswith('MI_BlueCube')):
                check(f'{vid}: {os.path.basename(new)} carries the variant\'s own data', mark in uexp)
    fv = rep.get('TestMod/Lune flat/Flat_P', {})
    check('flat-indexed pak relocated', 'error' not in fv, fv.get('error'))
    check('  its game override found by its real path', '/Game/Materials/MI_BlueCube' in fv.get('map', {}), list(fv.get('map', {})))
    check('  its mod-only package found by its real path', flat_only in fv.get('map', {}), list(fv.get('map', {})))
    check('  shared pak includes the flat mod-only package', flat_only.lower() in (shared or {}).get('packages', []), shared)
    if 'output' in fv:
        lst = run([retoc, 'list', '--path', fv['output']])[1]
        check('  only the variant\'s own packages are packed', lst.count('ExportBundleData') == 2, lst)

    # variants.lua flags mod-only assets (4th field false) so the Lua never treats them as vanilla
    check('variants.lua marks mod-only assets', '"MaterialInstanceConstant", false }' in lua_txt)

    # textures: size and pixel format in the report; small swatch PNGs next to the paks (for the app)
    if tex_pkg:
        import e33tex
        vt = rep.get('TestMod/Lune color/Tex_P', {})
        c = vt.get('classes', {}).get(tex_pkg, {})
        want = e33tex.parse_texture(os.path.join(base, *L.package_to_rel(tex_pkg).split('/')))
        check('texture width, height and pixel format recorded in the report',
              (c.get('width'), c.get('height'), c.get('format')) == (want['width'], want['height'], want['format']), c)
        sw = vt.get('swatches') or []
        tex_swatch = sw[0] if sw else 'missing.png'
        png = os.path.join(out, 'TestMod', 'swatches', sw[0]) if sw else ''
        data = open(png, 'rb').read() if png and os.path.isfile(png) else b''
        import struct
        dims = struct.unpack('>II', data[16:24]) if len(data) > 24 else (0, 0)
        check('a swatch PNG (<= 64 px) is written for the variant with a texture', len(sw) == 1 and
              data.startswith(b'\x89PNG') and 0 < max(dims) <= 64 and sw[0] == os.path.basename(vt['output'])[:-5] + '_1.png',
              (sw, dims))
        check('  and the report names its texture', vt.get('swatch_textures') == [tex_pkg], vt.get('swatch_textures'))
        check('  variants without textures list no swatches', rep.get('TestMod/Lune color/Red_P', {}).get('swatches') == [],
              rep.get('TestMod/Lune color/Red_P', {}).get('swatches'))

    # --only: the shared pak is rebuilt from ALL of the mod's containers, not just the selected one
    rc, log2 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                    '--mod', lib, '--out', out, '--lua-dir', lua, '--work', tmp, '--only', 'Red_P'])
    rep2 = json.load(open(os.path.join(out, 'relocate_report.json')))
    sh2 = rep2.get('TestMod/(shared)', {})
    check('--only run keeps every mod-only asset in the shared pak', shared_new.lower() in sh2.get('packages', []), sh2)
    reg = json.load(open(os.path.join(lua, 'wardrobe_registry.json')))
    ids = [v['id'] for m in reg for s_ in m['slots'] for v in s_['variants']]
    check('--only run keeps the other variants in the wardrobe', 'TestMod/Lune outfit/OutfitA_P' in ids, ids)

    # stale outputs from removed variants are pruned on a full run
    stale = os.path.join(out, 'TestMod', 'Gone_P.utoc')
    open(stale, 'wb').write(b'x')
    os.makedirs(os.path.join(out, 'TestMod', 'swatches'), exist_ok=True)
    stale_sw = os.path.join(out, 'TestMod', 'swatches', 'Gone_P_1.png')
    open(stale_sw, 'wb').write(b'x')
    rc, _ = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                 '--mod', lib, '--out', out, '--lua-dir', lua, '--work', tmp])
    check('stale output pruned on a full run', not os.path.exists(stale))
    check('  and its swatches too, while current ones stay', not os.path.exists(stale_sw) and
          (not tex_pkg or os.path.isfile(os.path.join(out, 'TestMod', 'swatches', tex_swatch))),
          os.listdir(os.path.join(out, 'TestMod', 'swatches')))

    # an import nothing provides (kept with a note), and a pak built for another engine version (refused)
    lib2 = os.path.join(tmp, 'Lib2', 'BadMod')
    lm = os.path.join(tmp, 'leg_missing')
    legacy_copy(lm, ['/Game/Environment/SM_BlueCube'])
    L.relocate_tree(lm, lm + '_r', {'/Game/Materials/MI_BlueCube': '/Game/Materials/MI_GoneCube'})  # import -> nowhere
    pack(lm + '_r', os.path.join(lib2, 'Opt', 'Missing_P'), 'Missing_P')
    lv = os.path.join(tmp, 'leg_v')
    legacy_copy(lv, ['/Game/Materials/MI_BlueCube'])
    os.makedirs(os.path.join(lib2, 'Opt', 'OldVer_P'))
    rc_, o_ = run([retoc, 'to-zen', '--version', 'UE5_3', lv, os.path.join(lib2, 'Opt', 'OldVer_P', 'OldVer_P.utoc')])
    rc, log3 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                    '--mod', lib2, '--out', os.path.join(tmp, 'out2'), '--lua-dir', os.path.join(tmp, 'lua2'), '--work', tmp])
    rep3 = json.load(open(os.path.join(tmp, 'out2', 'relocate_report.json')))
    r_missing = rep3.get('BadMod/Opt/Missing_P', {})
    err_ver = rep3.get('BadMod/Opt/OldVer_P', {}).get('error', '')
    check('unresolvable import: variant kept by default, with a note naming the package',
          'error' not in r_missing and r_missing.get('unresolved') and any('SM_BlueCube (1)' in n for n in r_missing.get('notes', [])),
          r_missing.get('error') or r_missing.get('notes'))
    check('  the console says so', 'reference(s) to an asset that is in neither the game nor this mod' in log3, log3[-800:])
    if r_missing.get('output'):
        comp = os.path.join(tmp, 'comp_missing')
        os.makedirs(comp)
        for f in os.listdir(paks):
            if f.endswith(('.utoc', '.ucas')):
                shutil.copy(os.path.join(paks, f), comp)
        for f in ('.utoc', '.ucas'):
            shutil.copy(r_missing['output'][:-5] + f, os.path.join(comp, 'zz_missing_9_P' + f))
        rc_b, o_b = run([retoc, 'to-legacy', '--version', 'UE5_4', '--no-shaders', '--no-script-objects', comp,
                         os.path.join(comp, 'back')])
        new_mesh = r_missing['map'].get('/Game/Environment/SM_BlueCube')
        ua = os.path.join(comp, 'back', *L.package_to_rel(new_mesh).split('/')) + '.uasset' if new_mesh else ''
        imps = L.read_package_info(ua)['imported_packages'] if os.path.isfile(ua) else []
        check('  its pak converts back; the missing reference stays empty, the rest resolves',
              rc_b == 0 and sum(1 for x in imps if x.startswith('/Engine/UnknownPackage')) == 1
              and all(x.startswith(('/Engine/UnknownPackage', '/Script/', '/Game/')) for x in imps), (o_b[-300:], imps))
    check('pak built for another Unreal version is refused with an explanation', 'different Unreal version' in err_ver, err_ver)
    check('no pak written for a refused variant', not any(f.lower().startswith('oldver')
          for f in os.listdir(os.path.join(tmp, 'out2', 'BadMod'))))

    # --strict-imports refuses it; the build from the previous run is kept, not deleted
    rc, log4 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                    '--mod', lib2, '--out', os.path.join(tmp, 'out2'), '--lua-dir', os.path.join(tmp, 'lua2'),
                    '--work', tmp, '--strict-imports'])
    rep4 = json.load(open(os.path.join(tmp, 'out2', 'relocate_report.json')))
    r4 = rep4.get('BadMod/Opt/Missing_P', {})
    check('--strict-imports refuses it and names the package', 'could not be resolved in SM_BlueCube' in r4.get('error', ''),
          r4.get('error'))
    kept = r4.get('kept_previous', '')
    check('  the previous build is kept: files stay, still in variants.lua', kept and os.path.isfile(kept)
          and os.path.isfile(kept[:-5] + '.ucas')
          and 'BadMod/Opt/Missing_P' in open(os.path.join(tmp, 'lua2', 'Scripts', 'variants.lua')).read(), kept)
    check('  the console says it was kept', 'kept the build from the previous run' in log4, log4[-600:])

    # several mods relocated one after another: each keeps its own log and report
    rc, _ = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                 '--mod', lib, '--out', os.path.join(tmp, 'out2'), '--lua-dir', os.path.join(tmp, 'lua2'),
                 '--work', tmp, '--only', 'Red_P'])
    merged = json.load(open(os.path.join(tmp, 'out2', 'relocate_report.json')))
    check('a second mod\'s run keeps the first mod in relocate_report.json',
          any(k.startswith('BadMod/') for k in merged) and any(k.startswith('TestMod/') for k in merged), list(merged))
    check('  each mod has its own log and report', all(os.path.isfile(os.path.join(tmp, 'out2', m, f))
          for m in ('BadMod', 'TestMod') for f in ('relocate_log.txt', 'relocate_report.json')))
    check('  the first mod\'s log is still its own', 'Missing_P' in open(os.path.join(tmp, 'out2', 'BadMod', 'relocate_log.txt')).read())
    con = open(os.path.join(tmp, 'out2', 'relocate_console.txt'), encoding='utf-8').read()
    check('the relocator keeps its console output in relocate_console.txt, one header per run',
          con.count('===== run ') >= 3 and 'variants relocated' in con and '--strict-imports' in con, con[-500:])
    R = __import__('e33_relocate')
    check('character from a mod name: CamelCase and "Name - Set"', R.character_of('ScielBodyLight') == 'Sciel'
          and R.character_of('Maelle - Claudia Set') == 'Maelle' and R.character_of('Main') is None)

    # ---- output names never collide (they used to: two variants overwrote one pak)
    check('plain names keep their file names (no churn for existing wardrobes)',
          R.safe_name('Some Outfit V2') == 'Some_Outfit_V2' and R.safe_name('Lune - Some Set') == 'Lune_-_Some_Set')
    check('names that clean to the same text get different file names',
          R.safe_name('Red (v2)_P') != R.safe_name('Red [v2]_P') and R.safe_name('\u8d64_P') != R.safe_name('\u9752_P')
          and R.safe_name('rouge \u00e9') != R.safe_name('rouge \u00e8'))
    taken = {}
    s1, s2 = R.variant_stem('M/a b_P', taken), R.variant_stem('M/a_b_P', taken)
    check('  and two variants whose stems still clash in one run get distinct pak names', s1 != s2, (s1, s2))
    check('  a hash never follows "_" directly (UE reads _<digits>_P as a pak priority)',
          '-' in R.safe_name('x' * 200) and '_-' not in R.safe_name('Red (v2)_P'), R.safe_name('Red (v2)_P'))

    reloc = [sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks]
    # ---- a work folder left by a killed run is removed by the next run (it holds hard links to the game)
    stale = os.path.join(tmp, '_e33wardrobe_work_killed')
    os.makedirs(os.path.join(stale, 'game')); open(os.path.join(stale, 'game', 'global.utoc'), 'w').write('x')
    os.utime(stale, (1, 1))
    young = os.path.join(tmp, '_e33wardrobe_work_running')
    os.makedirs(young)
    rc, log5 = run(reloc + ['--mod', lib, '--out', os.path.join(tmp, 'out3'), '--lua-dir', os.path.join(tmp, 'lua3'),
                            '--work', tmp, '--only', 'Red_P'])
    check('a work folder left by an interrupted run is removed, and said so', not os.path.exists(stale)
          and 'left by an interrupted run' in log5, log5[-400:])
    check('  a recent one (a run that may still be going) is left alone', os.path.isdir(young))
    shutil.rmtree(young)
    check('  and this run removed its own work folder',
          not [d for d in os.listdir(tmp) if d.startswith('_e33wardrobe_work_')], os.listdir(tmp))

    # ---- bad input is refused before anything is written
    rc, log6 = run(reloc + ['--mod', os.path.join(tmp, 'does not exist'), '--out', os.path.join(tmp, 'out4')])
    check('a missing --mod folder is an error (it gave "0/0 relocated" before)', rc != 0 and 'not found' in log6
          and not os.path.exists(os.path.join(tmp, 'out4')), log6[-300:])
    empty = os.path.join(tmp, 'EmptyMod'); os.makedirs(os.path.join(empty, 'Opt'))
    rc, log7 = run(reloc + ['--mod', empty, '--out', os.path.join(tmp, 'out4')])
    check('  a folder without paks too', rc != 0 and 'No .utoc or .pak' in log7, log7[-300:])
    dup = os.path.join(tmp, 'other', 'TestMod'); shutil.copytree(lib, dup)
    rc, log8 = run(reloc + ['--mod', lib, '--mod', dup, '--out', os.path.join(tmp, 'out4')])
    check('  two --mod folders with the same name too', rc != 0 and 'same name' in log8, log8[-300:])
    rc, log9 = run(reloc + ['--mod', lib, '--work', os.path.join(paks, 'w'), '--out', os.path.join(tmp, 'out4')])
    check('  a --work folder inside Paks too (the game would load it)', rc != 0 and 'inside the Paks' in log9
          and not os.path.exists(os.path.join(paks, 'w')), log9[-300:])

    # ---- the Lua mod is updated without writing through a mod manager's hard link
    lua5 = os.path.join(tmp, 'lua5'); os.makedirs(os.path.join(lua5, 'Scripts'))
    staging = os.path.join(tmp, 'staging_main.lua'); open(staging, 'w').write('-- an older main.lua')
    link_or_copy(staging, os.path.join(lua5, 'Scripts', 'main.lua'))
    rc, _ = run(reloc + ['--mod', lib, '--out', os.path.join(tmp, 'out5'), '--lua-dir', lua5, '--work', tmp,
                         '--only', 'Red_P'])
    tmpl = open(os.path.join(HERE, '..', 'lua', 'E33Wardrobe', 'Scripts', 'main.lua')).read()
    check('the Lua mod is updated by replacing the file, not writing through a hard link',
          open(os.path.join(lua5, 'Scripts', 'main.lua')).read() == tmpl and open(staging).read() == '-- an older main.lua')
    st = os.stat(os.path.join(lua5, 'Scripts', 'menu.lua')).st_mtime
    rc, _ = run(reloc + ['--mod', lib, '--out', os.path.join(tmp, 'out5'), '--lua-dir', lua5, '--work', tmp,
                         '--only', 'Red_P'])
    check('  unchanged files are not written again', os.stat(os.path.join(lua5, 'Scripts', 'menu.lua')).st_mtime == st)

    # ---- --mod "<name>" finds the mod in the default library next to Paks (no saved config needed)
    game6 = os.path.join(tmp, 'game6', 'Content')
    paks6 = os.path.join(game6, 'Paks')
    shutil.copytree(paks, paks6, copy_function=link_or_copy)
    shutil.copytree(lib, os.path.join(game6, 'Paks_ModLibrary', 'TestMod'))
    rc, log11 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks6,
                     '--mod', 'TestMod', '--out', os.path.join(tmp, 'out6'), '--lua-dir', os.path.join(tmp, 'lua6'),
                     '--work', tmp, '--only', 'Red_P'])
    check('--mod with just a name uses the library next to Paks', rc == 0
          and os.path.isdir(os.path.join(tmp, 'out6', 'TestMod')), (rc, log11[-300:]))

    # ---- --save remembers the Paks folder for later runs (its own settings file)
    cfgf = os.path.join(tmp, 'e33wardrobe_config.json')
    os.environ['E33_CONFIG'] = cfgf
    rc, log12 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--paks', paks6, '--save'])
    saved = json.load(open(cfgf)) if os.path.isfile(cfgf) else {}
    rc2, log13 = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--mod', 'TestMod',
                      '--out', os.path.join(tmp, 'out7'), '--lua-dir', os.path.join(tmp, 'lua7'), '--work', tmp,
                      '--only', 'Red_P'])
    del os.environ['E33_CONFIG']
    check('--save stores the Paks folder; a later run without --paks uses it',
          rc == 0 and saved.get('paks_dir') == paks6 and rc2 == 0 and os.path.isdir(os.path.join(tmp, 'out7', 'TestMod')),
          (rc, saved, rc2, log13[-300:]))

    # ---- --remove takes a mod out of the wardrobe
    rc, log10 = run(reloc + ['--remove', 'testmod', '--out', os.path.join(tmp, 'out5'), '--lua-dir', lua5])
    vl = open(os.path.join(lua5, 'Scripts', 'variants.lua')).read()
    check('--remove: the mod leaves the wardrobe and its relocated paks are deleted', rc == 0
          and 'TestMod' not in vl and not os.path.exists(os.path.join(tmp, 'out5', 'TestMod')), (rc, log10[-300:]))

    # ---- fixes.json: bundling a file from another mod, disabling a mod (the app's fix tools)
    import e33fixes
    import e33_relocate
    game = os.path.join(tmp, 'G', 'Sandfall', 'Content', 'Paks')      # own copy: Disabled goes next to Paks
    os.makedirs(game)
    for f in os.listdir(paks):
        if os.path.isfile(os.path.join(paks, f)):
            try:
                link_or_copy(os.path.join(paks, f), os.path.join(game, f))
            except OSError:
                shutil.copy2(os.path.join(paks, f), os.path.join(game, f))
    lib3, lua3 = os.path.join(tmp, 'Lib3'), os.path.join(tmp, 'lua3', 'E33Wardrobe')
    ln = os.path.join(tmp, 'leg_needy')
    legacy_copy(ln, ['/Game/Environment/SM_BlueCube'])
    L.relocate_tree(ln, ln + '_r', {'/Game/Materials/MI_BlueCube': '/Game/Materials/MI_GoneCube'})
    pack(ln + '_r', os.path.join(lib3, 'Needy', 'Opt', 'Mesh_P'), 'Mesh_P')
    os.makedirs(os.path.join(lib3, 'Needy', 'Opt', 'Mesh2_P'))
    for f in os.listdir(os.path.join(lib3, 'Needy', 'Opt', 'Mesh_P')):
        shutil.copy(os.path.join(lib3, 'Needy', 'Opt', 'Mesh_P', f), os.path.join(lib3, 'Needy', 'Opt', 'Mesh2_P', f.replace('Mesh_P', 'Mesh2_P')))
    ld = os.path.join(tmp, 'leg_donor')
    legacy_copy(ld, ['/Game/Materials/MI_BlueCube'])
    L.relocate_tree(ld, ld + '_r', {'/Game/Materials/MI_BlueCube': '/Game/Materials/MI_GoneCube'})
    pack(ld + '_r', os.path.join(lib3, 'Donor', 'Opt', 'Gone_P'), 'Gone_P')
    reloc3 = [sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', game,
              '--lua-dir', lua3, '--work', tmp]
    out3 = os.path.join(game, '~mods', '_E33Wardrobe')
    rc, _ = run(reloc3 + ['--mod', os.path.join(lib3, 'Needy')])
    r0 = json.load(open(os.path.join(out3, 'relocate_report.json'))).get('Needy/Opt/Mesh_P', {})
    check('bundle: before, the option links to a file nowhere (MI_GoneCube)', rc == 0 and r0.get('unresolved'), r0)
    rec = e33fixes.make_bundle(game, lua3, 'Needy', os.path.join(lib3, 'Donor'), ['/Game/Materials/MI_GoneCube'],
                               retoc=retoc, from_option='Donor/Opt/Gone_P')
    check('  make_bundle copies it from the other mod into a small container under the menu folder',
          rec['packages'] == ['/Game/Materials/MI_GoneCube'] and os.path.isfile(os.path.join(lua3, *rec['utoc'].split('/')))
          and e33fixes.load(lua3)['mods']['Needy']['bundles'][0]['from_mod'] == 'Donor', rec)
    rc, log11 = run(reloc3 + ['--mod', os.path.join(lib3, 'Needy')])
    rep11 = json.load(open(os.path.join(out3, 'relocate_report.json')))
    r1, sh1 = rep11.get('Needy/Opt/Mesh_P', {}), rep11.get('Needy/(shared)', {})
    check('  after Reinstall the link resolves (no unresolved imports) and the shared pak holds the file',
          rc == 0 and not r1.get('unresolved') and '/game/materials/mi_gonecube' in sh1.get('packages', []), (r1.get('notes'), sh1))
    rc, log12 = run(reloc3 + ['--mod', os.path.join(lib3, 'Donor')])
    reg3 = json.load(open(os.path.join(lua3, 'wardrobe_registry.json')))
    check('  a bundled file in both mods\' shared paks is not reported as "two versions of one mod"',
          rc == 0 and 'Two versions' not in log12 and e33_relocate.shared_clashes(reg3) == {}
          and next(m for m in reg3 if m['name'] == 'Needy').get('bundled') == ['/game/materials/mi_gonecube'], log12[-400:])
    vl = lambda: open(os.path.join(lua3, 'Scripts', 'variants.lua'), encoding='utf-8').read()  # noqa: E731
    dis = os.path.join(e33fixes.disabled_root(game), 'Needy')
    r = e33fixes.set_disabled(game, lua3, 'Needy', True)
    check('disable: the prepared files move out of Paks and the menu leaves the mod out',
          r['ok'] and not os.path.isdir(os.path.join(out3, 'Needy')) and os.path.isdir(dis)
          and not os.path.commonpath([os.path.abspath(dis), os.path.abspath(game)]) == os.path.abspath(game)
          and 'mod = "Needy"' not in vl() and 'mod = "Donor"' in vl(), (r, os.listdir(out3)))
    rc, log13 = run(reloc3 + ['--mod', os.path.join(lib3, 'Needy')])
    check('  Reinstall of a disabled mod keeps it disabled (prepared, then moved back out)',
          rc == 0 and 'is disabled' in log13 and os.path.isdir(dis) and not os.path.isdir(os.path.join(out3, 'Needy'))
          and any(f.endswith('.utoc') for f in os.listdir(dis)) and 'mod = "Needy"' not in vl(), log13[-400:])
    if os.name == 'nt':
        # 17 Oct audit: a file open in the parked folder (Explorer preview, antivirus) made the
        # rename fail with a traceback that ended the whole run; now that mod is skipped with a note
        held = open(os.path.join(dis, next(f for f in os.listdir(dis) if f.endswith('.utoc'))), 'rb')
        try:
            rc, log14 = run(reloc3 + ['--mod', os.path.join(lib3, 'Needy'), '--mod', os.path.join(lib3, 'Donor')])
        finally:
            held.close()
        check('  a disabled mod whose parked folder can\'t be moved: skipped with a note, the other mod is prepared',
              rc == 0 and 'Traceback' not in log14 and 'could not be moved back' in log14 and os.path.isdir(dis)
              and '[Donor]' in log14, log14[-600:])
    r = e33fixes.set_disabled(game, lua3, 'Needy', False)
    check('enable: back in ~mods and in the menu', r['ok'] and os.path.isdir(os.path.join(out3, 'Needy'))
          and not os.path.isdir(dis) and 'mod = "Needy"' in vl(), r)
    e33fixes.set_disabled(game, lua3, 'Needy', True)
    rc, _ = run(reloc3 + ['--remove', 'Needy'])
    check('--remove of a disabled mod deletes its parked copy and forgets "disabled"', rc == 0 and not os.path.isdir(dis)
          and not e33fixes.is_disabled(e33fixes.load(lua3), 'Needy'), os.listdir(e33fixes.disabled_root(game)))

    # ---- a link that differs from its package only in letter case (PC 2026-10-16: Cheekier Chic's
    # Sciel Blueprint asks for SK_Sciel_Chic_Skin, the mod's mesh is SK_Sciel_Chic_skin). The game
    # resolves it; retoc wrote /Engine/UnknownPackage and the relocated Blueprint had no body.
    lib5 = os.path.join(tmp, 'Lib5')
    lk = os.path.join(tmp, 'leg_case')
    legacy_copy(lk, ['/Game/Materials/MI_BlueCube', '/Game/Environment/SM_BlueCube'])
    L.relocate_tree(lk, lk + '_mi', {'/Game/Materials/MI_BlueCube': '/Game/Materials/MI_CaseCube'})
    L.relocate_tree(lk, lk + '_sm', {'/Game/Materials/MI_BlueCube': '/Game/Materials/MI_caseCube'})
    lk2 = lk + '_both'
    for src_, pkg_ in ((lk + '_mi', '/Game/Materials/MI_CaseCube'), (lk + '_sm', '/Game/Environment/SM_BlueCube')):
        f = L.package_to_rel(pkg_)
        for ext in ('.uasset', '.uexp'):
            d = os.path.join(lk2, *f.split('/')) + ext
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy(os.path.join(src_, *f.split('/')) + ext, d)
    pack(lk2, os.path.join(lib5, 'Cased', 'Opt', 'Case_P'), 'Case_P')
    rc, log15 = run(reloc3 + ['--mod', os.path.join(lib5, 'Cased')])
    r5 = json.load(open(os.path.join(out3, 'relocate_report.json'))).get('Cased/Opt/Case_P', {})
    check('case: a link spelled MI_caseCube to the mod\'s MI_CaseCube resolves (no unresolved imports)',
          rc == 0 and r5.get('output') and not r5.get('unresolved'), (r5.get('unresolved'), r5.get('error'), log15[-400:]))
    check('  and the run says it fixed the letter case of that link',
          'fixed the letter case of 1 link(s)' in log15
          and '/Game/Materials/MI_caseCube -> /Game/Materials/MI_CaseCube' in log15, log15[-400:])
    sm_new, mi_new = r5.get('map', {}).get('/Game/Environment/SM_BlueCube'), r5.get('map', {}).get('/Game/Materials/MI_CaseCube')
    comp5, leg5 = os.path.join(tmp, 'comp_case'), os.path.join(tmp, 'leg_case_out')
    os.makedirs(comp5)
    for f in os.listdir(game):
        if os.path.isfile(os.path.join(game, f)) and f.lower().endswith(('.utoc', '.ucas')):
            link_or_copy(os.path.join(game, f), os.path.join(comp5, f))
    for ext in ('.utoc', '.ucas'):
        link_or_copy(r5['output'][:-5] + ext, os.path.join(comp5, 'zz_case_out_P' + ext))
    imported = []
    if sm_new and mi_new:
        run([retoc, 'to-legacy', comp5, leg5, '--no-shaders', '--no-script-objects', '--filter', L.package_to_rel(sm_new) + '.'])
        ua = os.path.join(leg5, *L.package_to_rel(sm_new).split('/')) + '.uasset'
        imported = L.read_package_info(ua)['imported_packages'] if os.path.isfile(ua) else []
    check('  the relocated mesh links to the relocated material, as the game would load it',
          bool(mi_new) and mi_new in imported and '/Engine/UnknownPackage' not in imported, (sm_new, mi_new, imported))
    # ... but a link to a GAME package is never respelled (PC 17 Oct audit): the game's file index can
    # spell a folder differently from the package's own name (index Civil/Textures, package
    # Civil/textures), and mods link by the package's own name. A game container like that:
    lg = os.path.join(tmp, 'leg_gamecase')
    legacy_copy(lg, ['/Game/Materials/MI_BlueCube'])
    L.relocate_tree(lg, lg + '_r', {'/Game/Materials/MI_BlueCube': '/Game/Mtl/textures/MI_TCube'})
    low_dir = os.path.join(lg + '_r', 'Sandfall', 'Content', 'Mtl', 'textures')
    os.rename(low_dir, low_dir + '_x')
    os.rename(low_dir + '_x', os.path.join(lg + '_r', 'Sandfall', 'Content', 'Mtl', 'Textures'))  # index: Textures
    rc_, o_ = run([retoc, 'to-zen', '--version', 'UE5_4', lg + '_r', os.path.join(game, 'pakchunk77-Windows.utoc')])
    lm6 = os.path.join(tmp, 'leg_gamecase_mod')
    legacy_copy(lm6, ['/Game/Environment/SM_BlueCube'])
    L.relocate_tree(lm6, lm6 + '_r', {'/Game/Materials/MI_BlueCube': '/Game/Mtl/textures/MI_TCube'})
    pack(lm6 + '_r', os.path.join(lib5, 'GameCase', 'Opt', 'Mesh_P'), 'Mesh_P')
    rc, log16 = run(reloc3 + ['--mod', os.path.join(lib5, 'GameCase')])
    r6 = json.load(open(os.path.join(out3, 'relocate_report.json'))).get('GameCase/Opt/Mesh_P', {})
    check('case: a link spelled like the game package\'s own name (not its file index) is left as it is and resolves',
          rc_ == 0 and rc == 0 and r6.get('output') and not r6.get('unresolved') and 'letter case' not in log16,
          (o_[-200:], r6.get('unresolved'), [x for x in log16.splitlines() if 'letter case' in x]))
    os.remove(os.path.join(game, 'pakchunk77-Windows.utoc'))
    os.remove(os.path.join(game, 'pakchunk77-Windows.ucas'))

    # ---- names that clean to the same folder or pak (audit 1.3.0): nothing overwrites another's files
    lib4 = os.path.join(tmp, 'Lib4')
    for mod in ('Twin A', 'Twin_A'):
        for opt in ('Outfit A', 'Outfit_A'):
            d = os.path.join(lib4, mod, 'Row', opt)
            os.makedirs(d)
            for f in os.listdir(os.path.join(lib3, 'Needy', 'Opt', 'Mesh_P')):
                shutil.copy(os.path.join(lib3, 'Needy', 'Opt', 'Mesh_P', f), os.path.join(d, f.replace('Mesh_P', 'Opt_P')))
    run(reloc3 + ['--mod', os.path.join(lib4, 'Twin A')])
    run(reloc3 + ['--mod', os.path.join(lib4, 'Twin_A')])
    reg4 = {m['name']: m for m in json.load(open(os.path.join(lua3, 'wardrobe_registry.json')))}
    dir_of = lambda n: os.path.dirname(reg4[n]['slots'][0]['variants'][0]['output'])  # noqa: E731
    d1, d2 = dir_of('Twin A'), dir_of('Twin_A')
    check('two mods whose names clean to the same folder get different folders', d1 != d2 and os.path.isdir(d1)
          and os.path.isdir(d2), (d1, d2))
    run(reloc3 + ['--mod', os.path.join(lib4, 'Twin_A')])
    reg4 = {m['name']: m for m in json.load(open(os.path.join(lua3, 'wardrobe_registry.json')))}
    check('  a later run keeps each mod in the folder it already has', dir_of('Twin_A') == d2 and dir_of('Twin A') == d1,
          (dir_of('Twin_A'), d2))
    outs = {v['id']: v['output'] for s_ in reg4['Twin A']['slots'] for v in s_['variants']}
    oa, ob = outs['Twin A/Row/Outfit A'], outs['Twin A/Row/Outfit_A']
    before = (os.path.getmtime(oa), os.path.getsize(oa))
    rc, log14 = run(reloc3 + ['--mod', os.path.join(lib4, 'Twin A'), '--only', 'Row/Outfit_A$'])
    reg4 = {m['name']: m for m in json.load(open(os.path.join(lua3, 'wardrobe_registry.json')))}
    outs2 = {v['id']: v['output'] for s_ in reg4['Twin A']['slots'] for v in s_['variants']}
    check('  repairing one option (--only) writes its own pak, never its look-alike sibling\'s',
          rc == 0 and outs2['Twin A/Row/Outfit_A'] == ob and outs2['Twin A/Row/Outfit A'] == oa
          and (os.path.getmtime(oa), os.path.getsize(oa)) == before, (outs2, log14[-300:]))
    rep4 = json.load(open(os.path.join(d1, 'relocate_report.json')))
    check('  and the mod\'s own report keeps the other options\' entries', 'Twin A/Row/Outfit A' in rep4
          and 'Twin A/Row/Outfit_A' in rep4, list(rep4))
    rc, _ = run(reloc3 + ['--remove', 'Twin_A'])        # its folder is the hashed one; "Twin_A" is the other's
    check('  removing one deletes only its own folder', rc == 0 and not os.path.isdir(d2) and os.path.isdir(d1)
          and any(f.endswith('.utoc') for f in os.listdir(d1)), (os.path.isdir(d1), os.path.isdir(d2)))

    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
