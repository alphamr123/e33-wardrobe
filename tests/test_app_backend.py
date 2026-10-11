"""The desktop app's backend (app/backend): game folder, UE4SS and menu detection, archives,
sorting by outfit, mod list and details, the job queue and the Api.

usage: python tests/test_app_backend.py

Optional fixtures (read from the environment; the parts that need them are skipped otherwise):
  E33_SAMPLE_MOD                          a folder with the option folders of a real outfit mod
                                          (26 Lune options: sorting must give 5 rows)
  E33_E2E_PAKS, E33_E2E_BASE, E33_RETOC   the fake game of test_relocate_e2e.py: a full add,
                                          update, reinstall and remove through the Api
"""
import base64
import json
import struct
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (ROOT, os.path.join(ROOT, 'tools'), HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

TMP = tempfile.mkdtemp(prefix='e33app_')
os.environ['E33_APPDATA'] = os.path.join(TMP, 'appdata')
os.environ['E33_OFFLINE'] = '1'                 # never ask Nexus from a test
os.environ.pop('E33_CONFIG', None)
os.environ.pop('E33_LUA_TEMPLATE', None)

from app.backend import api as api_mod, archives, jobs, library, paths   # noqa: E402
from make_fake_library import tiny_utoc   # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
    fails += (not cond)


def touch(path, data=b'x'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(data if isinstance(data, bytes) else data.encode('utf-8'))
    return path


def option(mod, rel, pkgs, stem=None):
    """An option folder with a tiny .utoc listing `pkgs` (/Game/... paths) and dummy .ucas/.pak."""
    d = os.path.join(mod, *rel.split('/'))
    stem = stem or os.path.basename(rel).replace(' ', '_') + '_P'
    files = ['Sandfall/Content/' + p[len('/Game/'):] + '.uasset' for p in pkgs]
    touch(os.path.join(d, stem + '.utoc'), tiny_utoc(files))
    touch(os.path.join(d, stem + '.ucas'), b'UCAS')
    touch(os.path.join(d, stem + '.pak'), b'PAK')
    return d


def fake_game(base, steam=True, exe=True):
    root = os.path.join(base, 'steamapps', 'common', 'Expedition 33') if steam else base
    touch(os.path.join(root, 'Sandfall', 'Content', 'Paks', 'global.utoc'))
    os.makedirs(os.path.join(root, 'Sandfall', 'Content', 'Paks', '~mods'), exist_ok=True)
    if exe:
        touch(os.path.join(root, 'Sandfall', 'Binaries', 'Win64', 'SandFall-Win64-Shipping.exe'))
    return root


SK = '/Game/Characters/Heros/{c}/Customization/Skin/SK_{c}_{n}_Skin'
PLACEHOLDER = '/Game/Characters/Heros/Lune/SK_Lune_Placeholder'
SUMMARY_KEYS = {'id', 'name', 'state', 'characters', 'replaces', 'options', 'rows', 'size', 'swatches', 'notes', 'skin', 'note_level'}
DETAIL_KEYS = {'id', 'name', 'characters', 'replaces', 'options', 'size', 'folder', 'state', 'rows', 'skin',
               'overlaps', 'notes'}
OPTION_KEYS = {'id', 'label', 'changes', 'textures', 'tags', 'swatch', 'ok', 'error', 'notes', 'files', 'images',
               'missing'}
IMAGE_KEYS = {'ref', 'name', 'path', 'kind', 'width', 'height', 'format', 'swatch'}
STATE_KEYS = {'version', 'first_run', 'game', 'ue4ss', 'menu', 'library', 'game_running', 'tools'}
MONITOR_KEYS = {'watching', 'game_running', 'since', 'menu_active', 'last_activity', 'ended', 'date', 'problems',
                'on_screen', 'tail'}


def png(w=8, h=8):
    return paths.tools()['tex'].png_bytes(w, h, bytes([200, 40, 40, 255]) * (w * h))


# ============================================================================ the game folder

def test_game_folder():
    base = os.path.join(TMP, 'games')
    root = fake_game(os.path.join(base, 'SteamLibrary'))
    paks = os.path.join(root, 'Sandfall', 'Content', 'Paks')
    want = (os.path.normpath(root), os.path.normpath(paks))
    for name, p in [('the game folder', root), ('Sandfall', os.path.join(root, 'Sandfall')),
                    ('Content', os.path.join(root, 'Sandfall', 'Content')), ('Paks', paks),
                    ('Paks\\~mods', os.path.join(paks, '~mods')),
                    ('Binaries\\Win64', os.path.join(root, 'Sandfall', 'Binaries', 'Win64')),
                    ('the .exe itself', os.path.join(root, 'Sandfall', 'Binaries', 'Win64', 'SandFall-Win64-Shipping.exe')),
                    ('with quotes and spaces', f' "{root}" ')]:
        check(f'game folder from {name}', paths.normalize_game_folder(p) == want, paths.normalize_game_folder(p))
    other = os.path.join(base, 'Other'); os.makedirs(os.path.join(other, 'Sandfall', 'Content', 'Paks'))
    check('a folder that looks like the game but has no global.utoc is refused', paths.normalize_game_folder(other) is None)
    check('  an unrelated folder, a missing one, empty input too', paths.normalize_game_folder(base) is None
          and paths.normalize_game_folder(os.path.join(base, 'nope')) is None and paths.normalize_game_folder('') is None
          and paths.normalize_game_folder(None) is None)
    check('Steam is recognised from steamapps in the path', paths.store_of(root) == 'Steam')
    gp_outer = os.path.join(base, 'XboxGames', 'Clair Obscur- Expedition 33')
    gp_root = os.path.join(gp_outer, 'Content')
    touch(os.path.join(gp_root, 'Sandfall', 'Content', 'Paks', 'global.utoc'))
    os.makedirs(os.path.join(gp_root, 'Sandfall', 'Binaries', 'WinGDK'))
    check('Game Pass: its outer folder leads to <outer>\\Content', paths.normalize_game_folder(gp_outer)
          == (os.path.normpath(gp_root), os.path.normpath(paths.paks_of(gp_root))), paths.normalize_game_folder(gp_outer))
    check('  and the store is Game Pass', paths.store_of(gp_root) == 'Game Pass')
    plain = fake_game(os.path.join(base, 'D', 'Games', 'E33'), steam=False)
    check('  an unknown store is null', paths.store_of(plain) is None)
    return root, gp_root


def test_ue4ss_and_menu(root, gp_root):
    u = paths.ue4ss_info(root)
    check('no UE4SS: not installed, with the problem in plain words', not u['installed'] and not u['ok']
          and u['problem'] == paths.UE4SS_MISSING, u)
    b = os.path.join(root, 'Sandfall', 'Binaries', 'Win64')
    touch(os.path.join(b, 'ue4ss', 'UE4SS.dll'))
    log = os.path.join(b, 'ue4ss', 'UE4SS.log')
    touch(log, '[2026-10-11 07:11:36.1978309] Console created\n'
               '[2026-10-11 07:11:36.2040206] UE4SS - v3.0.1 Beta #0 - Git SHA #527a483b\n'
               '[2026-10-11 07:11:36.2040504] Timezone: Asia/Karachi\n')
    u = paths.ue4ss_info(root)
    check('UE4SS found with its version from UE4SS.log', u['installed'] and u['ok'] and u['problem'] is None
          and u['version'] == '3.0.1 Beta (527a483b)' and u['dir'] == os.path.join(b, 'ue4ss'), u)
    check('  a version that already names its build stays as it is',
          paths.ue4ss_version_from_log('UE4SS - v3.0.1-1125-g527a483b - Git SHA #527a483b') == '3.0.1-1125-g527a483b')
    with open(log, 'a') as f:
        f.write('[Lua] [E33Wardrobe] This UE4SS build is too old for E33Wardrobe: it has no LoopInGameThreadWithDelay.\n')
    u = paths.ue4ss_info(root)
    check('  the log says it is too old: ok false, with the fix', u['installed'] and not u['ok']
          and u['problem'] == "UE4SS is too old for the in-game menu. Get 'UE4SS - Experimental (Newer)'.", u)
    gdk = os.path.join(gp_root, 'Sandfall', 'Binaries', 'WinGDK')
    touch(os.path.join(gdk, 'dwmapi.dll'))
    os.makedirs(os.path.join(gdk, 'ue4ss', 'Mods'))
    u = paths.ue4ss_info(gp_root)
    check('Game Pass: UE4SS under Binaries\\WinGDK (dwmapi.dll + ue4ss folder)', u['installed'] and u['ok']
          and u['version'] is None and u['dir'] == os.path.join(gdk, 'ue4ss'), u)
    check('  the menu folder follows UE4SS', paths.menu_dir(gp_root) == os.path.join(gdk, 'ue4ss', 'Mods', 'E33Wardrobe'))

    lua = paths.menu_dir(root)
    check('menu folder: <ue4ss>\\Mods\\E33Wardrobe', lua == os.path.join(b, 'ue4ss', 'Mods', 'E33Wardrobe'), lua)
    bundled = paths.lua_version(os.path.join(ROOT, 'lua', 'E33Wardrobe', 'Scripts', 'main.lua'))
    m = paths.menu_info(lua)
    check('menu not installed yet', m == {'installed': False, 'version': None, 'bundled': bundled, 'update': False}, m)
    touch(os.path.join(lua, 'Scripts', 'main.lua'), '-- old\nlocal MOD = "E33Wardrobe"\nlocal VERSION = "1.0.0"   -- x\n')
    m = paths.menu_info(lua)
    check('menu installed: its version from main.lua, the bundled one, and an update offered',
          m['installed'] and m['version'] == '1.0.0' and m['bundled'] == bundled and bundled and m['update'], m)
    touch(os.path.join(lua, 'Scripts', 'main.lua'), f'local VERSION = "{bundled}"\n')
    check('  no update when it is the bundled version', not paths.menu_info(lua)['update'])
    os.remove(os.path.join(lua, 'Scripts', 'main.lua'))


# ============================================================================ names and archives

def test_names():
    P = archives.parse_nexus_name
    check('Nexus file name: name, mod id, version, time',
          P('840 Expedition 1 (Crop Top) No Gauntlet-337-2-1-1750919736')
          == ('840 Expedition 1 (Crop Top) No Gauntlet', 337, '2-1', 1750919736))
    check('  with " - " in the name and a long version', P('841 - Civil Skirt (No Thights - No Shoes)-337-1-0-841-1749145312')
          == ('841 - Civil Skirt (No Thights - No Shoes)', 337, '1-0-841', 1749145312))
    check('  underscores in the name', P('841_Civil_Skirt3 - No Shoes-337-1-6-1749806836')[:2] == ('841_Civil_Skirt3 - No Shoes', 337))
    check('  a plain name has no Nexus part', P('Some Outfit v2') is None and P('Outfit-2') is None)
    check('file name part of an archive path',
          archives.file_name_part('/x/840 Expedition 3 (Crop Top)-337-2-1-1750919786.7z') == '840 Expedition 3 (Crop Top)'
          and archives.file_name_part('/x/Plain Mod.zip') == 'Plain Mod')
    S = archives.sanitize_name
    check('folder names safe for Windows', S('A: B? <C>') == 'A B C' and S('CON') == 'CON_' and S('name. ') == 'name'
          and S('backup.old') == 'backup' and S('..hidden') == 'hidden' and S('') == 'Mod' and len(S('x' * 300)) == 80,
          [S('A: B? <C>'), S('CON'), S('name. '), S('backup.old')])
    C = archives.common_words
    check('common leading words, without leading numbers',
          C(['840 Expedition 1 (Crop Top)', '840 Expedition 2 (Crop Top) Jacket', '840 Expedition 7 Shoes']) == 'Expedition'
          and C(['843 - Clea (A)', '843 - Clea (B)']) == 'Clea' and C(['840 A', '841 B']) == '' and C(['12 3', '12 4']) == '')
    L = library
    check('outfit names from meshes', L.outfit_name(SK.format(c='Lune', n='Clea')) == 'Clea'
          and L.outfit_name('/Game/X/SK_Lune_CivilianSkirt_skin') == 'Civilian Skirt'
          and L.outfit_name('/Game/X/SK_Lune_Bikini_A_skin') == 'Bikini A' and L.outfit_name(PLACEHOLDER) is None,
          [L.outfit_name('/Game/X/SK_Lune_CivilianSkirt_skin'), L.outfit_name('/Game/X/SK_Lune_Bikini_A_skin')])
    check('  the base body takes the options\' common words, else "Base body"',
          L.row_name([PLACEHOLDER], ['840 Expedition 1 (Crop Top)', '840 Expedition 2']) == 'Expedition'
          and L.row_name([PLACEHOLDER], ['Alpha', 'Beta']) == 'Base body')
    check('option labels without the number and the row name',
          L.option_label('843_Clea - Shorter Skirt.', 'Clea') == 'Shorter Skirt'
          and L.option_label('843 - Clea (No Thights)', 'Clea') == 'No Thights'
          and L.option_label('843_Clea6 - Shorter Skirt. No Shoes', 'Clea') == 'Shorter Skirt. No Shoes'
          and L.option_label('OutfitA_P', 'Lune outfit') == 'OutfitA',
          [L.option_label('843_Clea - Shorter Skirt.', 'Clea'), L.option_label('843 - Clea (No Thights)', 'Clea')])
    check('texture size labels', [L.size_label(x) for x in (4096, 2048, 1024, 512, 0)] == ['4K', '2K', '1K', '512 px', ''])
    check('CamelCase folder names as words; other names stay', L.humanize('LuneFelineSorceressBarefoot')
          == 'Lune Feline Sorceress Barefoot' and L.humanize('SemiNude') == 'Semi Nude' and L.humanize('Clea') == 'Clea'
          and L.humanize('only Lune mod fix') == 'only Lune mod fix' and L.humanize('BTLS') == 'BTLS'
          and L.humanize('Lace_dress') == 'Lace_dress', [L.humanize('LuneFelineSorceressBarefoot'), L.humanize('SemiNude')])
    check('Replaces for the base body: shared words of several options, never the mod name or one folder name',
          L.base_body_name(['840 Expedition 1 (Crop Top)', '840 Expedition 2'], 'Lune Outfit Options') == 'Expedition'
          and L.base_body_name(['Fitting Outfits - Lune'], 'Fitting Outfits - Lune') == 'Base body'
          and L.base_body_name(['LuneFelineSorceressBarefoot'], 'Lune Feline Sorceress') == 'Base body'
          and L.base_body_name(['Neutral Set A', 'Neutral Set B'], 'Neutral Set') == 'Base body',
          [L.base_body_name(['Fitting Outfits - Lune'], 'Fitting Outfits - Lune')])
    tex = {'/Game/X/T_A_D': {'class': 'Texture2D'}, '/Game/X/T_Body_D': {'class': 'Texture2D', 'width': 4096}}
    check('texture sizes the relocator did not record are named as unknown (not left out)',
          L.texture_summary(tex, True) == 'Body 4K, outfit (size ?)'
          and L.texture_summary({'/Game/X/T_A_D': {'class': 'Texture2D'}}, True, guessed=True) == 'Outfit',
          L.texture_summary(tex, True))
    check('lists of names: the first three and how many more', L.few(['a', 'b']) == 'a and b'
          and L.few(['a', 'b', 'c', 'd', 'e']) == 'a, b, c and 2 more' and L.names_of(['/Game/X/T_A', '/Game/Y/T_B'])
          == 'T_A and T_B', L.few(['a', 'b', 'c', 'd', 'e']))


def make_zip(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def mod_files(prefix, stem, pkgs=('/Game/Characters/Heros/Lune/T_Lune_Test_D',)):
    files = ['Sandfall/Content/' + p[len('/Game/'):] + '.uasset' for p in pkgs]
    return {prefix + stem + '.utoc': tiny_utoc(files), prefix + stem + '.ucas': b'UCAS', prefix + stem + '.pak': b'PAK'}


def test_archives():
    work = os.path.join(TMP, 'arch')
    # zip-slip and absolute names
    for i, bad in enumerate(['../evil.txt', '/abs.txt', 'C:/win.txt', 'ok/..\\..\\back.txt']):
        z = make_zip(os.path.join(work, f'bad{i}.zip'), {'fine.txt': b'x', bad: b'evil'})
        dest = os.path.join(work, f'out{i}', 'x')
        try:
            archives.extract_archive(z, dest)
            refused = False
        except archives.ArchiveError as e:
            refused = 'outside its folder' in str(e) or 'absolute path' in str(e)
        check(f'zip with {bad!r} is refused before anything is written', refused and not os.path.exists(
            os.path.join(work, f'out{i}', 'evil.txt')) and not os.path.exists(os.path.join(work, 'evil.txt'))
            and not os.path.exists(os.path.join(dest, 'fine.txt')))
    # a single zip with a wrapper folder and a readme
    z = make_zip(os.path.join(work, 'drop', 'Neutral Outfit-4242-1-0-1750000000.zip'),
                 {'Neutral Outfit/readme.txt': b'hi', **mod_files('Neutral Outfit/Variant A/', 'VarA_P'),
                  **mod_files('Neutral Outfit/Variant B/', 'VarB_P')})
    groups, bad = archives.plan_items([z])
    res = archives.unpack_group(groups[0], os.path.join(work, 'job1'))
    check('zip: unpacked, wrapper folder stripped, name without the Nexus part',
          res['name'] == 'Neutral Outfit' and sorted(os.listdir(res['folder'])) == ['Variant A', 'Variant B', 'readme.txt']
          and os.path.isfile(os.path.join(res['folder'], 'Variant A', 'VarA_P.utoc')), (res, os.listdir(res['folder'])))
    # 7z
    try:
        import py7zr
    except ImportError:
        py7zr = None
    src = os.path.join(work, 'src7')
    for n, data in mod_files('Pack/Sandfall/Content/Paks/~mods/', 'Seven_P').items():
        touch(os.path.join(src, n), data)
    if py7zr:
        s7 = os.path.join(work, 'drop', 'Seven Mod.7z')
        with py7zr.SevenZipFile(s7, 'w') as zz:
            zz.writeall(os.path.join(src, 'Pack'), 'Pack')
        g, _ = archives.plan_items([s7])
        res = archives.unpack_group(g[0], os.path.join(work, 'job2'))
        check('7z: unpacked, wrapper and game-layout folders stripped', res['name'] == 'Seven Mod'
              and os.path.isfile(os.path.join(res['folder'], 'Seven_P.utoc')), res)
    else:
        print('SKIP 7z checks: py7zr is not installed')
    keep = make_zip(os.path.join(work, 'drop', 'Kept Rows.zip'), {**mod_files('Kept Rows/Lune outfit/A/', 'A_P'),
                                                                  **mod_files('Kept Rows/Lune outfit/B/', 'B_P')})
    res = archives.unpack_group(archives.plan_items([keep])[0][0], os.path.join(work, 'job2b'))
    check('zip: a meaningful folder below the wrapper (a menu row) is kept', os.listdir(res['folder']) == ['Lune outfit'], res)
    # several archives of one Nexus mod become one mod, an option folder per archive
    a1 = make_zip(os.path.join(work, 'drop2', '840 Style 1 (Short)-4243-1-0-1750000001.zip'), mod_files('', 'Base_P'))
    a2 = make_zip(os.path.join(work, 'drop2', '840 Style 2 (Long)-4243-1-1-1750000002.zip'), mod_files('Wrap/', 'Base_P'))
    a3 = make_zip(os.path.join(work, 'drop2', 'Other Thing.zip'), mod_files('', 'Other_P'))
    folder = os.path.join(work, 'drop2', 'Loose Folder')
    for n, data in mod_files('', 'Loose_P').items():
        touch(os.path.join(folder, n), data)
    groups, bad = archives.plan_items([a1, a2, a3, folder, os.path.join(work, 'drop2', 'notes.txt')])
    check('dropped items: files of one Nexus mod grouped, others alone, other files refused',
          [len(g['items']) for g in groups] == [2, 1, 1] and groups[0]['modid'] == 4243 and len(bad) == 1,
          (groups, bad))
    asked = []
    res = archives.unpack_group(groups[0], os.path.join(work, 'job3'),
                                lookup=lambda mid: asked.append(mid) or 'Neutral Style Pack')
    check('  one mod named from Nexus, one option folder per archive (named by its file name)',
          asked == [4243] and res['name'] == 'Neutral Style Pack'
          and sorted(os.listdir(res['folder'])) == ['840 Style 1 (Short)', '840 Style 2 (Long)']
          and os.path.isfile(os.path.join(res['folder'], '840 Style 2 (Long)', 'Base_P.utoc')), res)
    res = archives.unpack_group(groups[0], os.path.join(work, 'job4'), lookup=lambda mid: None)
    check('  without Nexus: the files\' common words name it', res['name'] == 'Style', res['name'])
    check('  the Nexus lookup is skipped offline (E33_OFFLINE) and never required', archives.nexus_mod_name(4243) is None)
    old = archives._graphql
    archives._graphql = lambda q, t: {'data': {'legacyModsByDomain': {'nodes': [{'name': 'Neutral Style Pack'}]}}}
    os.environ.pop('E33_OFFLINE')
    try:
        check('  the Nexus answer is read and cached', archives.nexus_mod_name(9999) == 'Neutral Style Pack'
              and json.load(open(os.path.join(paths.app_data_dir(), 'nexus_names.json'))).get('9999') == 'Neutral Style Pack')
        archives._graphql = lambda q, t: (_ for _ in ()).throw(OSError('offline'))
        check('  a failed lookup gives None', archives.nexus_mod_name(9998) is None)
    finally:
        archives._graphql = old
        os.environ['E33_OFFLINE'] = '1'
    res = archives.unpack_group(groups[2], os.path.join(work, 'job5'), library=os.path.join(work, 'drop2'))
    check('a folder already in the library is used where it is', res['in_place'] and res['folder'] == folder, res)
    res = archives.unpack_group(groups[2], os.path.join(work, 'job6'), library=os.path.join(work, 'elsewhere'))
    check('  a folder from elsewhere is copied, the original stays', not res['in_place']
          and os.path.isfile(os.path.join(res['folder'], 'Loose_P.utoc')) and os.path.isfile(os.path.join(folder, 'Loose_P.utoc')))
    # an archive of archives (a "pack" download)
    inner1 = open(a1, 'rb').read()
    inner2 = open(a2, 'rb').read()
    pack = make_zip(os.path.join(work, 'drop3', 'all files.zip'), {os.path.basename(a1): inner1, os.path.basename(a2): inner2})
    g, _ = archives.plan_items([pack])
    res = archives.unpack_group(g[0], os.path.join(work, 'job7'), lookup=lambda mid: None)
    check('an archive holding the archives of one mod becomes that mod', res['name'] == 'all files'
          and sorted(os.listdir(res['folder'])) == ['840 Style 1 (Short)', '840 Style 2 (Long)'], (res, os.listdir(res['folder'])))
    folder_of_archives = os.path.join(work, 'drop4')
    os.makedirs(folder_of_archives)
    shutil.copy(a1, folder_of_archives)
    shutil.copy(a2, folder_of_archives)
    g, _ = archives.plan_items([folder_of_archives])
    check('a dropped folder holding only archives counts as those archives', len(g) == 1 and len(g[0]['items']) == 2, g)
    # rar without 7-Zip
    rar = touch(os.path.join(work, 'drop', 'Some Mod.rar'), b'Rar!\x1a\x07\x00')
    o7, ou = paths.find_7z, paths.find_unrar
    paths.find_7z = paths.find_unrar = lambda: None
    try:
        archives.extract_archive(rar, os.path.join(work, 'rarout'))
        msg = ''
    except archives.ArchiveError as e:
        msg = str(e)
    finally:
        paths.find_7z, paths.find_unrar = o7, ou
    check('rar without 7-Zip: a clear error', msg.startswith('RAR needs 7-Zip'), msg)
    bad_zip = touch(os.path.join(work, 'drop', 'Broken.zip'), b'not a zip')
    try:
        archives.extract_archive(bad_zip, os.path.join(work, 'brokenout'))
        msg = ''
    except archives.ArchiveError as e:
        msg = str(e)
    check('a damaged zip: a plain error', 'damaged or not a zip' in msg, msg)


# ============================================================================ sorting by outfit

def test_arrange():
    mod = os.path.join(TMP, 'arr', 'Outfit Set')
    option(mod, '843 - Clea (Short)', [SK.format(c='Lune', n='Clea'), '/Game/Label_Lune_Skin_Clea'])
    option(mod, '843_Clea - Long', [SK.format(c='Lune', n='Clea')])
    option(mod, '840 Expedition 1 (Crop Top)', [PLACEHOLDER])
    option(mod, '840 Expedition 2 (Jacket)', [PLACEHOLDER])
    option(mod, 'Trio Gala', [SK.format(c=c, n='Gala') for c in ('Lune', 'Maelle', 'Sciel')])
    option(mod, '_Extra fix', [SK.format(c='Lune', n='Clea')])
    touch(os.path.join(mod, 'readme.txt'), b'hi')
    groups = library.arrange_by_outfit(mod)
    check('options replacing several outfits: one folder per outfit', library.group_tags(groups)
          == ['Expedition \u00b7 2', 'Clea \u00b7 2', 'Gala \u00b7 1'], library.group_tags(groups))
    check('  the folders were moved; the on/off extra and the readme stay', sorted(os.listdir(mod))
          == ['Clea', 'Expedition', 'Gala', '_Extra fix', 'readme.txt']
          and sorted(os.listdir(os.path.join(mod, 'Clea'))) == ['843 - Clea (Short)', '843_Clea - Long'], sorted(os.listdir(mod)))
    slots = paths.tools()['relocate'].option_slots(mod)
    check('  the relocator then makes one row per outfit', sorted(slots) == ['Clea', 'Expedition', '_Extra fix', 'Trio Gala']
          or sorted(slots) == ['Clea', 'Expedition', 'Trio Gala', '_Extra fix'], sorted(slots))
    check('  a costume for three characters is one group', groups[2]['meshes'] == sorted(SK.format(c=c, n='Gala')
                                                                                         for c in ('Lune', 'Maelle', 'Sciel')))
    check('  sorting again changes nothing', library.arrange_by_outfit(mod) == [])
    one = os.path.join(TMP, 'arr', 'One Outfit')
    option(one, 'A', [SK.format(c='Lune', n='Clea')])
    option(one, 'B', [SK.format(c='Lune', n='Clea')])
    check('options of one outfit are left as they are', library.arrange_by_outfit(one) == []
          and sorted(os.listdir(one)) == ['A', 'B'])
    apart = os.path.join(TMP, 'arr', 'Apart')
    option(apart, 'X/A', [SK.format(c='Lune', n='Clea')])
    option(apart, 'Y/B', [SK.format(c='Lune', n='Sirene')])
    check('options in different folders (already sorted) are left as they are', library.arrange_by_outfit(apart) == [])
    names = os.path.join(TMP, 'arr', 'Clash')
    option(names, 'Clea', [SK.format(c='Lune', n='Clea')])
    option(names, 'Other', [SK.format(c='Lune', n='Sirene')])
    g = library.arrange_by_outfit(names)
    check('an option folder named like its outfit still sorts', sorted(os.listdir(names)) == ['Clea', 'Sirene']
          and os.listdir(os.path.join(names, 'Clea')) == ['Clea'], (g, os.listdir(names)))
    pk = {}

    def fake_packages(u):
        return pk.get(os.path.basename(os.path.dirname(u)), [])
    syn = os.path.join(TMP, 'arr', 'Synthetic')
    for n, m in [('1 A', 'SK_Lune_Clea_Skin'), ('2 B', 'SK_Lune_Sirene_Skin'), ('3 C', 'SK_Lune_Sirene_Skin')]:
        option(syn, n, ['/Game/Dummy'])
        pk[n] = ['/Game/Characters/Heros/Lune/Customization/Skin/' + m]
    g = library.arrange_by_outfit(syn, packages=fake_packages)
    check('package lists can come from elsewhere (tests)', library.group_tags(g) == ['Clea \u00b7 1', 'Sirene \u00b7 2'])

    sample = os.environ.get('E33_SAMPLE_MOD')
    if not sample or not os.path.isdir(sample):
        print('SKIP real outfit mod: set E33_SAMPLE_MOD')
        return
    real = os.path.join(TMP, 'arr', 'Lune Outfit Options')
    shutil.copytree(sample, real, copy_function=lambda s, d: os.link(s, d))      # hard links: no copy of the mod
    groups = library.arrange_by_outfit(real)
    check('real mod: 26 options sorted into 5 rows', library.group_tags(groups) == [
        'Expedition \u00b7 7', 'Civilian Skirt \u00b7 3', 'Bikini A \u00b7 2', 'Clea \u00b7 6', 'Sirene \u00b7 8'],
        library.group_tags(groups))
    check('  and the relocator sees 5 rows of 26 options', sorted(library.menu_rows(real)) == sorted(
        [('Expedition', 7), ('Civilian Skirt', 3), ('Bikini A', 2), ('Clea', 6), ('Sirene', 8)]), library.menu_rows(real))


# ============================================================================ mod list and details (no retoc)

def test_library_view():
    base = os.path.join(TMP, 'view')
    paks = os.path.join(base, 'Sandfall', 'Content', 'Paks')
    lib = os.path.join(base, 'Sandfall', 'Content', 'Paks_ModLibrary')
    lua = os.path.join(base, 'lua')
    out_root = os.path.join(paks, '~mods', '_E33Wardrobe')
    mesh = SK.format(c='Lune', n='Clea')
    body_t = '/Game/Characters/Heros/Lune/Body/T_Lune_Body_D'
    out_t = '/Game/Characters/Heros/Lune/Customization/Skin/T_Lune_Clea_D'
    mi = '/Game/Characters/Heros/Lune/Customization/Skin/MI_Lune_Clea'
    mod = os.path.join(lib, 'Neutral Set')
    option(mod, 'Clea/843_Clea - Short', [mesh, mi, body_t, out_t])
    option(mod, 'Clea/843_Clea - Long', [mesh])
    option(mod, 'Clea/843_Clea - Broken', [mesh])
    os.makedirs(os.path.join(lib, 'Not a mod', 'empty'))
    os.makedirs(os.path.join(lib, '.incoming', 'job1'))
    touch(os.path.join(lib, 'Neutral Set.old', 'x.utoc'))
    md = os.path.join(out_root, 'Neutral_Set')
    touch(os.path.join(md, 'swatches', 'Neutral_Set_Clea_843_Clea_-_Short_P_1.png'), png())
    touch(os.path.join(md, 'swatches', 'Neutral_Set_Clea_843_Clea_-_Short_P_2.png'), png(4, 4))
    for stem in ('Neutral_Set_Clea_843_Clea_-_Short_P', 'Neutral_Set_Clea_843_Clea_-_Long_P'):
        for ext in ('.utoc', '.ucas'):
            touch(os.path.join(md, stem + ext))
    label_pkg = '/Game/Chic_MyMod'
    classes = {mesh: {'class': 'SkeletalMesh', 'object': 'SK_Lune_Clea_Skin', 'override': True},
               mi: {'class': 'MaterialInstanceConstant', 'object': 'MI_Lune_Clea', 'override': True},
               body_t: {'class': 'Texture2D', 'object': 'T_Lune_Body_D', 'override': True, 'width': 4096, 'height': 4096,
                        'format': 'PF_BC7'},
               out_t: {'class': 'Texture2D', 'object': 'T_Lune_Clea_D', 'override': True, 'width': 2048, 'height': 1024,
                       'format': 'PF_BC7'},
               '/Game/Characters/Heros/Lune/PA_Lune_Clea': {'class': 'PhysicsAsset', 'object': 'PA', 'override': True}}
    classes_a = dict(classes, **{label_pkg: {'class': 'PrimaryAssetLabel', 'object': 'Chic_MyMod', 'override': False}})
    va = {'id': 'Neutral Set/Clea/843_Clea - Short', 'label': 'Clea: 843 Clea - Short', 'classes': classes_a,
          'map': {k: '/Game/ZW' + k[8:] for k in classes},
          'output': os.path.join(md, 'Neutral_Set_Clea_843_Clea_-_Short_P.utoc')}
    vb = {'id': 'Neutral Set/Clea/843_Clea - Long', 'label': '843 Clea - Long', 'classes': {mesh: classes[mesh]},
          'map': {mesh: '/Game/ZW' + mesh[8:]}, 'output': os.path.join(md, 'Neutral_Set_Clea_843_Clea_-_Long_P.utoc')}
    other_mesh_map = {mesh: '/Game/ZQ' + mesh[8:]}
    registry = [{'name': 'Neutral Set', 'slots': [{'id': 'Neutral Set/Clea', 'label': 'Neutral Set: Clea', 'character': None,
                                                   'variants': [vb, va]}],
                 'shared': ['/game/modonly/a', '/game/chic_mymod', '/game/modonly/t_lune_clea_extra']},
                {'name': 'Other Set', 'slots': [{'id': 'Other Set/Main', 'label': 'Other Set: Main', 'character': 'Lune',
                                                 'variants': [{'id': 'Other Set/', 'label': 'on', 'map': other_mesh_map,
                                                               'classes': {mesh: classes[mesh], label_pkg:
                                                                           classes_a[label_pkg]},
                                                               'output': os.path.join(out_root, 'Other_Set', 'Other_Set_P.utoc')}]}],
                 'shared': ['/game/modonly/a', '/game/chic_mymod', '/game/modonly/t_lune_clea_extra']},
                {'name': 'Label Twin', 'slots': [{'id': 'Label Twin/Main', 'label': 'Label Twin: Main', 'character': 'Lune',
                                                  'variants': [{'id': 'Label Twin/', 'label': 'on', 'map': {},
                                                                'classes': {label_pkg: classes_a[label_pkg]},
                                                                'output': os.path.join(out_root, 'Other_Set', 'Other_Set_P.utoc')}]}],
                 'shared': ['/game/chic_mymod']}]
    touch(os.path.join(out_root, 'Other_Set', 'Other_Set_P.utoc'))
    paths.write_json(os.path.join(lua, 'wardrobe_registry.json'), registry)
    report = {va['id']: dict(va, notes=['has its own shaders: packed as pakchunk41234'],
                             unresolved={mi: 1}, swatches=['Neutral_Set_Clea_843_Clea_-_Short_P_1.png',
                                                          'Neutral_Set_Clea_843_Clea_-_Short_P_2.png'],
                             swatch_textures=[out_t, body_t]),
              vb['id']: dict(vb, notes=[], unresolved={}, swatches=[]),
              'Neutral Set/Clea/843_Clea - Broken': {'error': 'Broken_P.utoc is container version Initial, the game uses '
                                                              'ReplaceIoChunkHashWithIoHash (built for a different Unreal version?)'},
              'Neutral Set/(shared)': {'output': 'x', 'packages': []}}
    paths.write_json(os.path.join(md, 'relocate_report.json'), report)
    failed = os.path.join(lib, 'Failed Mod')
    option(failed, '', ['/Game/Characters/Heros/Lune/T_X'], stem='Only_P')
    paths.write_json(os.path.join(out_root, 'Failed_Mod', 'relocate_report.json'),
                     {'Failed Mod/': {'error': 'no .utoc in this folder (legacy .pak-only mods are not supported yet)'}})
    option(os.path.join(lib, 'Fitting Set'), '', [PLACEHOLDER], stem='Fitting_P')
    option(os.path.join(lib, 'Feline Set'), 'Pack 1/LuneFelineBarefoot', [PLACEHOLDER])
    option(os.path.join(lib, 'Feline Set'), 'Pack 2/LuneNoEars', [PLACEHOLDER])
    fresh = os.path.join(lib, 'Fresh Mod')
    option(fresh, 'Red', ['/Game/Characters/Heros/Maelle/T_Maelle_Hair_D'])
    option(fresh, 'Blue', ['/Game/Characters/Heros/Maelle/T_Maelle_Hair_D'])

    v = library.View(lib, paks, lua, active={'Fresh Mod'})
    mods = {m['id']: m for m in library.list_mods(v)}
    check('list: library mods plus relocated ones; folders without paks, .old backups and .incoming are not mods',
          sorted(mods) == ['Failed Mod', 'Feline Set', 'Fitting Set', 'Fresh Mod', 'Label Twin', 'Neutral Set',
                           'Other Set'], sorted(mods))
    check('  every summary has the ModSummary keys', all(set(m) == SUMMARY_KEYS for m in mods.values()),
          [set(m) ^ SUMMARY_KEYS for m in mods.values()])
    n = mods['Neutral Set']
    check('a mod replacing the base body with one option: Replaces says "Base body", not the mod\'s name',
          mods['Fitting Set']['replaces'] == ['Base body'], mods['Fitting Set'])
    fel = library.mod_details(v, 'Feline Set')
    check('  CamelCase row folders read as words; each one-option row replaces the base body',
          [r['label'] for r in fel['rows']] == ['Lune Feline Barefoot', 'Lune No Ears'] and fel['replaces'] == ['Base body'],
          ([r['label'] for r in fel['rows']], fel['replaces']))
    check('  states: ready, failed, working, and a relocated mod without a library folder',
          (n['state'], mods['Failed Mod']['state'], mods['Fresh Mod']['state'], mods['Other Set']['state'])
          == ('ready', 'failed', 'working', 'ready'), [m['state'] for m in mods.values()])
    check('  characters, replaced outfits, counts, skin', n['characters'] == ['Lune'] and n['replaces'] == ['Clea']
          and n['options'] == 3 and n['rows'] == 1 and n['skin'] is True and n['size'] > 0, n)
    check('  swatches are small PNG data URLs', len(n['swatches']) == 1 and n['swatches'][0].startswith('data:image/png;base64,')
          and base64.b64decode(n['swatches'][0].split(',', 1)[1])[:4] == b'\x89PNG', n['swatches'])
    d = library.mod_details(v, 'Neutral Set')
    check('details: the ModDetails keys', set(d) == DETAIL_KEYS, set(d) ^ DETAIL_KEYS)
    row = d['rows'][0]
    check('  one row per menu slot, with its character', len(d['rows']) == 1 and row['id'] == 'Neutral Set/Clea'
          and row['label'] == 'Clea' and row['character'] == 'Lune', row)
    opts = {o['label']: o for o in row['options']}
    check('  options with clean labels and the OptionDetails keys', sorted(opts) == ['Broken', 'Long', 'Short']
          and all(set(o) == OPTION_KEYS for o in opts.values()), sorted(opts))
    s = opts['Short']
    check('  changes, textures by kind and size, tags', s['changes'] == 'Outfit mesh, 1 material, 2 textures, physics'
          and s['textures'] == 'Body 4K, outfit 2K' and s['tags'] == ['physics', 'own shaders'], s)
    check('  an unresolved link explained in plain words', s['notes'] == [
        "One texture link in MI_Lune_Clea points to a file the mod doesn't include; the menu fills it in game."], s['notes'])
    check('  its swatch', (s['swatch'] or '').startswith('data:image/png;base64,'))
    check('  the variant id', s['id'] == 'Neutral Set/Clea/843_Clea - Short', s['id'])
    ft = {f['path']: f for f in s['files']}
    check('  its files by path, with what each is and whether it replaces a game file', s['files'][0] == {
        'path': mesh, 'type': 'Outfit mesh', 'game': True} and ft[body_t]['type'] == 'Body texture'
          and ft[out_t]['type'] == 'Texture' and ft[mi]['type'] == 'Material' and ft[label_pkg] == {
              'path': label_pkg, 'type': 'Asset label', 'game': False} and len(s['files']) == 6, s['files'])
    im = s['images']
    check('  its textures for the viewer: the ones with a swatch first, with size, format and ref',
          [i['name'] for i in im] == ['T_Lune_Clea_D', 'T_Lune_Body_D'] and all(set(i) == IMAGE_KEYS for i in im)
          and im[0]['ref'] == 'Neutral Set/Clea/843_Clea - Short|' + out_t and im[0]['kind'] == 'Outfit'
          and (im[0]['width'], im[0]['height'], im[0]['format']) == (2048, 1024, 'BC7') and im[1]['kind'] == 'Body'
          and im[0]['swatch'].startswith('data:image/png') and im[1]['swatch'].startswith('data:image/png'), im)
    check('  the package with a link to a missing file, by path', s['missing'] == [
        {'in': mi, 'name': 'MI_Lune_Clea', 'links': 1, 'texture': True, 'names': []}], s['missing'])
    b = opts['Broken']
    check('  a refused option: ok false and why', b['ok'] is False and b['error']
          == 'Its pak was built for a different version of the game engine.' and b['swatch'] is None, b)
    check('  an option without textures', opts['Long']['textures'] == '' and opts['Long']['changes'] == 'Outfit mesh')
    check('skin: body textures, their size and the character', d['skin']['has'] and d['skin']['text']
          == "Brings its own body textures (4K) for Lune. They show only with this mod's outfits."
          and len(d['skin']['swatches']) == 1, d['skin'])
    check('  and its images for the viewer', [i['path'] for i in d['skin']['images']] == [body_t], d['skin']['images'])
    check('overlaps: another relocated mod replacing the same outfit of the same character, with the files', d['overlaps'] == [
        {'mod': 'Other Set', 'text': "Both replace Lune's Clea outfit. In game, the one picked last shows.",
         'files': [mesh]}], d['overlaps'])
    texts = [x['text'] for x in d['notes']]
    nb = {x['text'].split(' ', 2)[1]: x for x in d['notes']}
    check('notes: refused options, missing links, the same new files in two mods', any('1 of 3 options' in t for t in texts)
          and any("1 option links to files" in t for t in texts) and any('"Other Set" has 2 of this mod\'s new files' in t
                                                                       for t in texts), texts)
    by = lambda word: next((x for x in d['notes'] if word in x['text']), {})   # noqa: E731
    check('  they name the options and files, with the full list in items',
          by('1 of 3 options')['text'].endswith(': Broken.') and by('1 of 3 options')['items'] == ['Broken']
          and by('links to files')['text'] == "1 option links to files the mod doesn't include: Short."
          and by('links to files')['items'] == ['Short (MI_Lune_Clea: 1 link)'] and by('links to files')['what'] == 'options'
          and by('Other Set')['items'] == ['/game/modonly/a', '/game/modonly/t_lune_clea_extra']
          and by('Other Set')['what'] == 'files' and '(a and t_lune_clea_extra)' in by('Other Set')['text'], d['notes'])
    check('  a shared PrimaryAssetLabel (cook metadata) is no reason to suspect two versions of one mod',
          not any('Label Twin' in t for t in texts) and not any('chic_mymod' in i.lower() for x in d['notes']
                                                                 for i in x.get('items', [])), texts)
    check('  the summary counts them', n['notes'] == len(d['notes']))
    f = library.mod_details(v, 'Failed Mod')
    check('a failed mod: its option says why, in plain words', f['state'] == 'failed' and f['rows'][0]['options'][0]['error']
          == "Only a .pak file, no .utoc: this option can't be switched in game.", f['rows'])
    fr = library.mod_details(v, 'Fresh Mod')
    check('a mod not prepared yet: options guessed from its paks', fr['rows'][0]['options'][0]['changes'] == '1 texture'
          and fr['characters'] == ['Maelle'] and fr['options'] == 2, fr['rows'][0])
    check('unknown mod: None', library.mod_details(v, 'Nope') is None and library.mod_details(v, '../x') is None)
    os.remove(os.path.join(md, 'Neutral_Set_Clea_843_Clea_-_Long_P.utoc'))
    n2 = library.mod_details(library.View(lib, paks, lua), 'Neutral Set')
    check('prepared files missing: not installed, with a note', n2['state'] == 'not_installed'
          and any('missing' in x['text'] for x in n2['notes']), n2['notes'])


# ============================================================================ jobs without retoc

class FakeEnv:
    def __init__(self, ctx=None):
        self.ctx, self.changes = ctx, 0

    def _context(self):
        if self.ctx is None:
            raise jobs.JobFailed('Pick the game folder first.')
        return self.ctx

    def _bump(self):
        self.changes += 1


def test_jobs():
    R = paths.tools()['relocate']
    seen = []
    orig = R.main

    def fake_main(argv):
        print('[Neutral Set] Clea/843_Clea - Short ...')
        print('    skipped: is encrypted')
        sys.stderr.write('[Neutral Set] Clea/843_Clea - Long ...\n')
        raise SystemExit('The game is running. Close it first: its paks are locked while it runs.')
    R.main = fake_main
    real_out = sys.stdout
    try:
        jobs.run_relocator(['--x'], seen.append)
        msg = ''
    except jobs.JobFailed as e:
        msg = str(e)
    finally:
        R.main = orig
    check('relocator in-process: its lines are parsed, stdout is restored', seen[:2] == [
        '[Neutral Set] Clea/843_Clea - Short ...', '    skipped: is encrypted'] and len(seen) == 3 and sys.stdout is real_out, seen)
    check('  a SystemExit with a message fails with that message', msg
          == 'The game is running. Close it first: its paks are locked while it runs.', msg)
    R.main = lambda argv: 1
    try:
        rc, tail = jobs.run_relocator([], lambda s: None)
    finally:
        R.main = orig
    check('  a plain return code comes back', rc == 1)

    env = FakeEnv()
    q = jobs.JobQueue(env)
    j1 = q.reinstall('Anything')
    j2 = q.remove('Anything', True)
    q.wait(30)
    snap = {j['id']: j for j in q.snapshot()}
    check('jobs fail with a readable error and the queue goes on', snap[j1]['status'] == 'failed'
          and snap[j1]['error'] == 'Pick the game folder first.' and snap[j2]['status'] == 'failed' and not q.busy(), snap)
    check('  Poll job keys and steps', set(snap[j2]) >= {'id', 'name', 'size', 'kind', 'status', 'steps', 'error', 'mod_id'}
          and [s['key'] for s in snap[j2]['steps']] == ['remove', 'delete'] and snap[j2]['kind'] == 'remove', snap[j2])

    def boom():
        raise RuntimeError('disk on fire')
    env2 = FakeEnv({'library': os.path.join(TMP, 'jl'), 'paks': '', 'lua_dir': '', 'retoc': None, 'root': ''})
    q2 = jobs.JobQueue(env2)
    old = jobs.archives.unpack_group
    jobs.archives.unpack_group = lambda *a, **k: boom()
    try:
        jid = q2.add({'items': [os.path.join(TMP, 'x.zip')], 'modid': None})
        q2.wait(30)
    finally:
        jobs.archives.unpack_group = old
    j = q2.snapshot()[0]
    check('  an unexpected exception marks the job failed, never stuck', j['status'] == 'failed'
          and 'disk on fire' in j['error'] and j['steps'][0]['state'] == 'fail' and env2.changes >= 2, j)


# ============================================================================ the Api without retoc

class Dialogs:
    def __init__(self, folder=None, files=None):
        self._folder, self._files = folder, files or []

    def folder(self):
        return self._folder

    def files(self):
        return self._files


def test_api_basics(root):
    a = api_mod.Api(start_monitor=False)
    st = a.get_state()
    check('state: all keys; first run; the game not found here', set(st) == STATE_KEYS and st['first_run']
          and st['game']['found'] is False and st['ue4ss'] == {'installed': False, 'version': None, 'ok': False,
                                                                 'problem': None}, st)
    check('  versions and tools', st['version'] == paths.tools()['common'].VERSION and st['menu']['bundled']
          and 'zip' in st['tools']['formats'] and isinstance(st['tools']['retoc'], bool), st)
    check('without a game: adding is refused with a reason', a.add_paths(['x']) == {'ok': False, 'error': 'Pick the game folder first.'})
    check('pick_game_folder without dialogs: not available', a.pick_game_folder() == {'ok': False, 'error': 'not available'})
    a.dialogs = Dialogs(folder=None)
    check('  cancelled', a.pick_game_folder() == {'ok': False, 'error': 'cancelled'}
          and a.pick_files() == {'ok': False, 'error': 'cancelled'})
    a.dialogs = Dialogs(folder=os.path.join(root, 'Sandfall', 'Binaries', 'Win64'))
    r = a.pick_game_folder()
    check('  a folder inside the game: normalised, saved, source "picked"', r['ok'] and r['state']['game']['root']
          == os.path.normpath(root) and r['state']['game']['source'] == 'picked' and r['state']['game']['store'] == 'Steam'
          and not r['state']['first_run'], r)
    check('  the library defaults to Paks_ModLibrary next to Paks', r['state']['library']
          == os.path.join(root, 'Sandfall', 'Content', 'Paks_ModLibrary'))
    bad = a.set_game_folder(TMP)
    check('a wrong folder: a plain error, the game is kept', bad['ok'] is False and 'No game found there' in bad['error']
          and bad['state']['game']['root'] == os.path.normpath(root))
    b = api_mod.Api(start_monitor=False)
    check('a new start uses the saved game folder', b.get_state()['game']['source'] == 'saved')
    p = b.poll()
    check('poll: busy, changed, jobs', set(p) == {'busy', 'changed', 'jobs'} and p['busy'] is False and p['jobs'] == []
          and isinstance(p['changed'], int))
    m = b.monitor()
    check('monitor: the Monitor keys (from app/backend/monitor.py, or empty without it)', MONITOR_KEYS <= set(m), m)
    check('problems_text: plain text', isinstance(b.problems_text(), str) and b.problems_text().strip())
    check('add_paths: nothing usable', b.add_paths([os.path.join(TMP, 'nothing.txt')])['ok'] is False)
    lib = b.get_settings()['library']
    check('  the library folder itself is refused', b.add_paths([os.path.dirname(lib)])['ok'] is False)
    s = b.save_settings({'library': os.path.join(root, 'Sandfall', 'Content', 'Paks', 'lib')})
    check('settings: a library inside Paks is refused', s['ok'] is False and 'inside the Paks folder' in s['error'], s)
    s = b.save_settings({'watch_game': False, 'library': os.path.join(TMP, 'MyLibrary')})
    check('  saved: library and watch_game', s == {'ok': True, 'library': os.path.join(TMP, 'MyLibrary'), 'watch_game': False}
          and b.get_settings() == {'library': os.path.join(TMP, 'MyLibrary'), 'watch_game': False}, s)
    b.save_settings({'library': ''})
    check('  an empty library goes back to the default', b.get_settings()['library'] == lib)
    check('open_path: returns the path off Windows; unknown targets are errors',
          b.open_path('game') == {'ok': True, 'path': os.path.normpath(root)} and b.open_path('nothing here')['ok'] is False
          and b.open_path('report')['ok'] is False)
    check('open_url: known names only', b.open_url('github')['ok'] and b.open_url('nexus')['url'].endswith('/938')
          and b.open_url('elsewhere')['ok'] is False)
    check('mod ids never leave the library (separators, drive letters, "..")',
          library.safe_child(TMP, 'C:') is None and library.safe_child(TMP, '..') is None
          and library.safe_child(TMP, 'a/b') is None and library.safe_child(TMP, 'a\\b') is None
          and library.safe_child(TMP, 'Mod') == os.path.join(TMP, 'Mod')
          and b.remove_mod('C:', True)['ok'] is False and b.open_path('..')['ok'] is False)
    check('mod_details of an unknown mod: ok false', b.mod_details('Nope')['ok'] is False
          and b.reinstall_mod('Nope')['ok'] is False and b.remove_mod('Nope', False)['ok'] is False)
    check('install_menu without UE4SS: a reason', b.install_menu()['error'] == 'Install UE4SS first: the menu runs inside it.')
    touch(os.path.join(root, 'Sandfall', 'Binaries', 'Win64', 'ue4ss', 'UE4SS.dll'))
    r = b.install_menu()
    lua = paths.menu_dir(root)
    check('install_menu: the Lua mod and an empty wardrobe', r['ok'] and r['state']['menu']['installed']
          and not r['state']['menu']['update'] and os.path.isfile(os.path.join(lua, 'Scripts', 'menu.lua'))
          and open(os.path.join(lua, 'Scripts', 'variants.lua')).read().strip().endswith('return {}')
          and os.path.isfile(os.path.join(lua, 'enabled.txt')), r)
    touch(os.path.join(lua, 'Scripts', 'variants.lua'), '-- mine\nreturn { 1 }\n')
    b.install_menu()
    check('  an existing variants.lua is kept', 'return { 1 }' in open(os.path.join(lua, 'Scripts', 'variants.lua')).read())
    touch(os.path.join(lua, 'live_log_previous.txt'), '10:00:00 #1 session start 2026-10-10 10:00:00\r\n'
          '10:00:05 #2 log: could not load /Game/Mods/Gone/T_Gone.T_Gone\r\n10:02:00 #3 key DEL\r\n')
    f = b.monitor_file('previous')
    check('monitor_file(previous): the session before, read once with the same rules', f.get('which') == 'previous'
          and f['exists'] and [p['key'] for p in f['problems']] == ['load:T_Gone'] and f['problems'][0]['lines'] == [
              '10:00:05 log: could not load /Game/Mods/Gone/T_Gone.T_Gone'] and f['since'] == '10:00:00'
          and f['ended'] == '10:02:00' and f['date'] == '2026-10-10' and len(f['tail']) == 3 and not f['game_running']
          and MONITOR_KEYS <= set(f), f)
    again = b.monitor_file('previous', f['version'])
    check('  asked again with the version it has: just "unchanged"', again == {
        'ok': True, 'unchanged': True, 'version': f['version'], 'which': 'previous'}, again)
    with open(os.path.join(lua, 'live_log_previous.txt'), 'ab') as fh:
        fh.write(b'10:03:00 #4 key DEL\r\n')
    check('  a changed file gives a new version and its lines', b.monitor_file('previous', f['version']).get('lines') == 4)
    u = b.monitor_file('ue4ss')
    check('monitor_file(ue4ss): UE4SS.log alone; last: none yet; unknown names refused', u['which'] == 'ue4ss'
          and not u['exists'] and u['tail'] == [] and b.monitor_file('last')['exists'] is False
          and b.monitor_file('other')['ok'] is False, u)
    shutil.rmtree(lua, ignore_errors=True)   # Windows: a log file still open can't be deleted
    check('every method answers JSON-able data, never raises', json.dumps([b.get_state(), b.list_mods(), b.poll(),
                                                                           b.get_settings(), b.mod_details(None)]) and True)
    check('bulk calls: nothing given, or only unknown mods: a reason', b.reinstall_mods([])['ok'] is False
          and b.remove_mods(['Nope', 'Nada'], True) == {'ok': False, 'errors': [
              {'id': 'Nope', 'error': 'There is no mod named "Nope".'}, {'id': 'Nada', 'error': 'There is no mod named "Nada".'}],
              'error': 'None of the 2 mods could be queued: There is no mod named "Nope".'}, b.remove_mods(['Nope', 'Nada'], True))
    check('texture_preview of an unknown mod: a reason', b.texture_preview('Nope', 'Nope/x|/Game/T', 512)['ok'] is False)
    import re
    from app import e33app
    documented = set()
    with open(os.path.join(ROOT, 'app', 'API.md'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('| `'):
                documented |= set(re.findall(r'`(\w+)\(', line.split('|')[1]))
    check('the window exposes exactly the methods of API.md, and the Api has them all',
          documented == set(e33app.METHODS) and all(callable(getattr(b, m, None)) for m in e33app.METHODS),
          (documented ^ set(e33app.METHODS)))


# ============================================================================ a full add job (fixtures)

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


def test_e2e():
    paks_src, base, retoc = (os.environ.get(k) for k in ('E33_E2E_PAKS', 'E33_E2E_BASE', 'E33_RETOC'))
    if not (paks_src and base and retoc):
        print('SKIP full add job: set E33_E2E_PAKS, E33_E2E_BASE and E33_RETOC')
        return
    import e33legacy as L
    e2e = os.path.join(TMP, 'e2e')
    os.environ['E33_APPDATA'] = os.path.join(e2e, 'appdata')
    game = os.path.join(e2e, 'Game')
    paks = os.path.join(game, 'Sandfall', 'Content', 'Paks')
    shutil.copytree(paks_src, paks, copy_function=os.link)
    touch(os.path.join(game, 'Sandfall', 'Binaries', 'Win64', 'ue4ss', 'UE4SS.dll'))

    def legacy_copy(dst, pkgs):
        for p in pkgs:
            rel = L.package_to_rel(p)
            for ext in ('.uasset', '.uexp', '.ubulk'):
                s = os.path.join(base, *rel.split('/')) + ext
                if os.path.isfile(s):
                    touch(os.path.join(dst, *rel.split('/')) + ext, open(s, 'rb').read())

    tex_pkg = None
    for dp, _ds, fs in sorted(os.walk(os.path.join(base, 'Sandfall', 'Content'))):
        for f in sorted(fs):
            if f.endswith('.uasset') and tex_pkg is None:
                try:
                    if L.read_package_info(os.path.join(dp, f))['main_class'] == 'Texture2D':
                        tex_pkg = L.rel_to_package(os.path.relpath(os.path.join(dp, f), base).replace(os.sep, '/'))[0]
                except Exception:
                    pass
    src = os.path.join(e2e, 'src', 'Test Outfits')
    variants = {'Lune outfit/OutfitA_P': ['/Game/Environment/SM_BlueCube', '/Game/Materials/MI_BlueCube'],
                'Lune outfit/OutfitB_P': ['/Game/Materials/MI_BlueCube'] + ([tex_pkg] if tex_pkg else [])}
    for rel, pkgs in variants.items():
        leg = os.path.join(e2e, 'leg', rel.replace('/', '_'))
        legacy_copy(leg, pkgs)
        out = os.path.join(src, *rel.split('/'))
        os.makedirs(out)
        rc, o = run([retoc, 'to-zen', '--version', 'UE5_4', leg, os.path.join(out, os.path.basename(rel) + '.utoc')])
        assert rc == 0, o
    archive = os.path.join(e2e, 'downloads', 'Test Outfits-4321-1-0-1750000000.zip')
    os.makedirs(os.path.dirname(archive))
    with zipfile.ZipFile(archive, 'w') as z:
        for dp, _ds, fs in os.walk(src):
            for f in fs:
                full = os.path.join(dp, f)
                z.write(full, os.path.relpath(full, os.path.dirname(src)))

    a = api_mod.Api(start_monitor=False)
    r = a.set_game_folder(paks)
    check('e2e: game set from its Paks folder; UE4SS found; retoc found', r['ok'] and r['state']['ue4ss']['installed']
          and r['state']['tools']['retoc'], r)
    r = a.add_paths([archive])
    check('add_paths queues one job', r['ok'] and len(r['jobs']) == 1, r)
    jid = r['jobs'][0]
    details, states, t0 = set(), set(), time.time()
    while time.time() - t0 < 600:
        p = a.poll()
        job = next(j for j in p['jobs'] if j['id'] == jid)
        states.add(job['status'])
        for s in job['steps']:
            if s['key'] == 'install' and s['state'] == 'run' and s.get('detail', '').startswith('Option'):
                details.add(s['detail'])
        if not p['busy']:
            break
        time.sleep(0.02)
    job = next(j for j in a.poll()['jobs'] if j['id'] == jid)
    check('the job finished', job['status'] == 'done' and job['error'] is None and job['mod_id'] == 'Test Outfits'
          and job['kind'] == 'add' and job['name'] == os.path.basename(archive) and job['size'] == os.path.getsize(archive), job)
    steps = {s['key']: s for s in job['steps']}
    check('  steps: unpack, sort, install, all done', [s['key'] for s in job['steps']] == ['unpack', 'sort', 'install']
          and all(s['state'] == 'done' for s in job['steps'])
          and [s['label'] for s in job['steps']] == ['Unpacked', 'Sorted by outfit', 'Preparing for the in-game menu'], job)
    check('  details: options found, rows, options ready', steps['unpack']['detail'] == '2 options found'
          and steps['sort']['detail'] == '1 row in the menu' and steps['install']['detail'] == '2 options ready'
          and steps['install']['progress'] == 1.0, steps)
    check('  progress per option while it ran', details and all(d.startswith('Option ') and ' of 2: Lune outfit \u00b7 Outfit'
                                                                 in d for d in details), details)
    mods = a.list_mods()
    check('list_mods: the new mod, ready', len(mods) == 1 and set(mods[0]) == SUMMARY_KEYS and mods[0]['state'] == 'ready'
          and mods[0]['id'] == 'Test Outfits' and mods[0]['options'] == 2 and mods[0]['rows'] == 1
          and mods[0]['characters'] == ['Lune'] and mods[0]['size'] > 0, mods)
    if tex_pkg:
        check('  with a swatch from its texture', len(mods[0]['swatches']) == 1
              and mods[0]['swatches'][0].startswith('data:image/png;base64,'), mods[0]['swatches'])
    d = a.mod_details('Test Outfits')
    check('mod_details: shape', set(d) == DETAIL_KEYS and d['state'] == 'ready' and d['folder'] == os.path.join(
        a.get_settings()['library'], 'Test Outfits'), d)
    row = d['rows'][0]
    check('  its row and options', row['id'] == 'Test Outfits/Lune outfit' and row['label'] == 'Lune outfit'
          and row['character'] == 'Lune' and [o['label'] for o in row['options']] == ['OutfitA', 'OutfitB']
          and all(set(o) == OPTION_KEYS and o['ok'] for o in row['options']), row)
    oa, ob = row['options']
    check('  what each option changes', oa['changes'] == 'Mesh, 1 material' and (
        ob['changes'] == '1 material, 1 texture' if tex_pkg else ob['changes'] == '1 material'), (oa, ob))
    if tex_pkg:
        check('  texture size and swatch of the option with a texture', ob['textures'].startswith('Textures ')
              and (ob['swatch'] or '').startswith('data:image/png;base64,') and oa['swatch'] is None, ob)
        img = ob['images'][0]
        t0 = time.time()
        pv = a.texture_preview('Test Outfits', img['ref'], 1024)
        took = time.time() - t0
        png_b = base64.b64decode((pv.get('url') or ',').split(',', 1)[1])
        w_h = struct.unpack('>II', png_b[16:24]) if png_b[:4] == b'\x89PNG' else None
        check('texture_preview: the texture itself, read from the prepared pak with retoc and decoded',
              pv.get('ok') and pv['source'] == 'texture' and w_h == (pv['width'], pv['height'])
              and (pv['tex_width'], pv['tex_height'], pv['format']) == (img['width'], img['height'], img['format'])
              and pv['name'] == img['name'] and pv['path'] == tex_pkg, {k: v for k, v in pv.items() if k != 'url'})
        print(f'      (preview took {took:.2f} s)')
        t0 = time.time()
        again = a.texture_preview('Test Outfits', img['ref'], 1024)
        check('  the second time it comes from the cache', again.get('url') == pv.get('url') and time.time() - t0 < 1.0)
        sm = a.texture_preview('Test Outfits', img['ref'], 128)
        check('  a smaller one says it is smaller than the texture', sm.get('ok') and max(sm['width'], sm['height']) <= 128
              and 'Shown at' in sm['note'], {k: v for k, v in sm.items() if k != 'url'})
        content = os.path.dirname(paks)
        check('  no work folder is left next to Paks', not [n for n in os.listdir(content) if n.startswith('_e33wardrobe_work_')],
              os.listdir(content))
        check('  refs of another mod, or of files that are not its textures, are refused',
              a.texture_preview('Test Outfits', 'Other/x|' + tex_pkg)['ok'] is False
              and a.texture_preview('Test Outfits', img['ref'].split('|')[0] + '|/Game/../../etc/passwd')['ok'] is False
              and a.texture_preview('Test Outfits', img['ref'].split('|')[0] + '|/Game/Materials/MI_BlueCube')['ok'] is False)
    reg = json.load(open(os.path.join(paths.menu_dir(game), 'wardrobe_registry.json')))
    check('the wardrobe has it; the menu was installed with it', [m['name'] for m in reg] == ['Test Outfits']
          and a.get_state()['menu']['installed'])
    check('relocator settings live in the app data folder', os.environ.get('E33_CONFIG', '').startswith(TMP)
          or paths.tools()['relocate'].CONFIG_PATH.startswith(TMP), paths.tools()['relocate'].CONFIG_PATH)

    # the same archive again: an update of the mod
    r = a.add_paths([archive])
    a._jobs.wait(600)
    job = a.poll()['jobs'][-1]
    lib = a.get_settings()['library']
    check('adding it again updates the mod; no backup left', job['status'] == 'done'
          and 'replaces the earlier version' in job['steps'][0]['detail'] and not os.path.exists(os.path.join(lib, 'Test Outfits.old'))
          and a.list_mods()[0]['state'] == 'ready', job)
    # a pak-only mod is refused with a reason; the queue goes on
    pak_only = make_zip(os.path.join(e2e, 'downloads', 'Old Style.zip'), {'Old Style/Old_P.pak': b'PAK'})
    r1 = a.add_paths([pak_only])
    r2 = a.reinstall_mods(['Test Outfits', 'Nope'])
    check('reinstall_mods: one job per known mod, the others listed with why', r2['ok'] and len(r2['jobs']) == 1
          and r2['errors'] == [{'id': 'Nope', 'error': 'The folder of "Nope" is missing from the library.'}], r2)
    a._jobs.wait(600)
    js = {j['id']: j for j in a.poll()['jobs']}
    check('a .pak-only mod: refused with a reason, not put in the library', js[r1['jobs'][0]]['status'] == 'failed'
          and 'only .pak files' in js[r1['jobs'][0]]['error'] and not os.path.exists(os.path.join(lib, 'Old Style')),
          js[r1['jobs'][0]])
    check('reinstall after it: done', js[r2['jobs'][0]]['status'] == 'done' and js[r2['jobs'][0]]['kind'] == 'reinstall'
          and [s['key'] for s in js[r2['jobs'][0]]['steps']] == ['install'], js[r2['jobs'][0]])
    r = a.remove_mods(['Test Outfits'], True)
    a._jobs.wait(600)
    job = a.poll()['jobs'][-1]
    reg = json.load(open(os.path.join(paths.menu_dir(game), 'wardrobe_registry.json')))
    check('remove_mods with delete_files: out of the menu, paks and folder gone', r['ok'] and job['status'] == 'done'
          and [s['state'] for s in job['steps']] == ['done', 'done'] and reg == []
          and not os.path.exists(os.path.join(lib, 'Test Outfits'))
          and not os.path.exists(os.path.join(paks, '~mods', '_E33Wardrobe', 'Test_Outfits')) and a.list_mods() == [], job)
    check('nothing left in the library\'s incoming folder', not os.listdir(os.path.join(lib, '.incoming')))

    # names of files that links point to: kept in the zen package, read with retoc get
    from app.backend import assets
    zmod = os.path.join(e2e, 'zen', 'Zen Mod')
    leg = os.path.join(e2e, 'zen_leg')
    legacy_copy(leg, ['/Game/Materials/MI_BlueCube'])
    os.makedirs(os.path.join(zmod, 'Opt'))
    rc, o = run([retoc, 'to-zen', '--version', 'UE5_4', leg, os.path.join(zmod, 'Opt', 'Opt_P.utoc')])
    info = paths.tools()['utoc'].read_utoc(os.path.join(zmod, 'Opt', 'Opt_P.utoc'))
    chunk = info['chunks'][info['files'].index('Sandfall/Content/Materials/MI_BlueCube.uasset')]
    rc2, o2 = run([retoc, 'get', os.path.join(zmod, 'Opt', 'Opt_P.utoc'), chunk, os.path.join(e2e, 'mi.bin')])
    names = None
    if rc2 == 0:
        with open(os.path.join(e2e, 'mi.bin'), 'rb') as f:
            names = assets.zen_imported_packages(f.read())
    check('a zen package lists the packages it imports by name (read from the .utoc chunk with retoc get)',
          rc == 0 and names == ['/Game/Materials/M_Cube'], (o[-300:], o2[-300:], names))
    other_paks = os.path.join(e2e, 'OtherGame', 'Sandfall', 'Content', 'Paks')
    touch(os.path.join(other_paks, 'pakchunk0-Windows.utoc'), tiny_utoc(['Sandfall/Content/Other/T_Other.uasset']))
    touch(os.path.join(other_paks, 'pakchunk0-Windows.ucas'), b'UCAS')
    empty_paks = os.path.join(e2e, 'NoGame', 'Sandfall', 'Content', 'Paks')
    os.makedirs(empty_paks)

    class V:
        pass
    v = V()
    v.paks = other_paks
    got = assets.missing_names(v, zmod, os.path.join(zmod, 'Opt'), {'/Game/Materials/MI_BlueCube': 1})
    check('  an import that neither the game nor the mod has is named', got == {
        '/Game/Materials/MI_BlueCube': ['/Game/Materials/M_Cube']}, got)
    v.paks = empty_paks
    got = assets.missing_names(v, zmod, os.path.join(zmod, 'Opt'), {'/Game/Materials/MI_BlueCube': 1})
    check('  without the game\'s file list nothing is named (it would all look missing)', got == {}, got)
    v.paks = paks
    got = assets.missing_names(v, zmod, os.path.join(zmod, 'Opt'), {'/Game/Materials/MI_BlueCube': 1})
    check('  one the game has is not', got == {}, got)


def main():
    root, gp_root = test_game_folder()
    test_ue4ss_and_menu(root, gp_root)
    test_names()
    test_archives()
    test_arrange()
    test_library_view()
    test_jobs()
    test_api_basics(fake_game(os.path.join(TMP, 'apigame')))
    test_e2e()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
