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


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def main():
    paks, base, retoc = sys.argv[1:4]
    tmp = tempfile.mkdtemp(prefix='e33e2e_')
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
    rc, _ = run([sys.executable, '-I', os.path.join(TOOLS, 'e33_relocate.py'), '--retoc', retoc, '--paks', paks,
                 '--mod', lib, '--out', out, '--lua-dir', lua, '--work', tmp])
    check('stale output pruned on a full run', not os.path.exists(stale))

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
    os.link(staging, os.path.join(lua5, 'Scripts', 'main.lua'))
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
    shutil.copytree(paks, paks6, copy_function=os.link)
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

    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
