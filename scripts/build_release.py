"""Build the two release archives into dist/:

  E33Wardrobe-Lua-<version>.zip     the UE4SS mod, root folder E33Wardrobe/ (no variants.lua: the
                                    relocator writes it, and the mod starts without one)
  E33Wardrobe-Tools-<version>.zip   root folder "E33Wardrobe Tools/": tools/, lua/E33Wardrobe/ (the
                                    copy the relocator installs), docs, licences

usage: python scripts/build_release.py [--with-rules]

--with-rules also packs tools/rules/*.json (layout rules for other authors' mods). Leave it off
for Nexus until those authors agree; the Mixer works without them.
"""
import argparse
import os
import re
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import e33common  # noqa: E402

LUA_SRC = os.path.join(ROOT, 'lua', 'E33Wardrobe')
TOOL_FILES = ['E33 Mod Mixer.bat', 'E33 Relocate.bat', 'e33_mixer.py', 'e33_mixer_ui.html', 'e33_relocate.py',
              'e33common.py', 'e33legacy.py', 'e33previews.py', 'e33rules.py', 'e33tex.py', 'e33utoc.py']
LUA_SCRIPTS = ['main.lua', 'menu.lua', 'config.example.lua']   # never config.lua: an update must not replace the user's
TOP_FILES = ['README.md', 'LICENSE', 'CHANGELOG.md', 'CONTRIBUTING.md', 'research/usmap.py']
# the notice for a rules file is only packed together with that file
RULES_NOTICE = re.compile(r'^- \*\*Cheekier Chic\*\*[^\n]*\n(?:  [^\n]*\n)*', re.M)

LUA_README = """E33 Wardrobe {version} - UE4SS mod for Clair Obscur: Expedition 33

Needs UE4SS, experimental build from December 2025 or later (Nexus Mods: E33 UE4SS page, mod 630,
file "UE4SS - Experimental (Newer)"; tested: 3.0.1-1125-g527a483b).

Install: with Vortex, or extract into ...\\Sandfall\\Binaries\\Win64\\ue4ss\\Mods\\
(Game Pass: ...\\Binaries\\WinGDK\\ue4ss\\Mods\\), so that
...\\ue4ss\\Mods\\E33Wardrobe\\Scripts\\main.lua exists.

In game: load a save and press Delete for the menu. Clean (blood and dirt) and Fix look work
right away; switching outfit-mod variants live needs mods prepared with the relocator from the
Tools file.

Keys: copy Scripts\\config.example.lua to config.lua and edit it (updates never replace
config.lua). Problems: send report.txt from this folder (Settings > Report
in the menu).

Documentation, source and issues: see the mod page. Licence: MIT.
"""


def lua_version():
    with open(os.path.join(LUA_SRC, 'Scripts', 'main.lua'), encoding='utf-8') as f:
        m = re.search(r'^local VERSION = "([^"]+)"', f.read(), re.M)
    return m.group(1) if m else None


def add(z, src, arc):
    if not os.path.isfile(src):
        raise SystemExit(f'missing: {os.path.relpath(src, ROOT)}')
    z.write(src, arc)


JUNK = {'Thumbs.db', 'desktop.ini', '.DS_Store'}


def add_tree(z, src, arc, skip=('__pycache__',)):
    for dp, ds, fs in os.walk(src):
        ds[:] = sorted(d for d in ds if d not in skip)
        for f in sorted(fs):
            if f in JUNK or f.endswith(('.pyc', '.tmp')):
                continue
            p = os.path.join(dp, f)
            z.write(p, arc + '/' + os.path.relpath(p, src).replace(os.sep, '/'))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--with-rules', action='store_true', help='include tools/rules/*.json')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist'))
    a = ap.parse_args()

    version = e33common.VERSION
    if lua_version() != version:
        raise SystemExit(f'version mismatch: tools {version}, main.lua {lua_version()}')
    os.makedirs(a.out, exist_ok=True)

    lua_zip = os.path.join(a.out, f'E33Wardrobe-Lua-{version}.zip')
    with zipfile.ZipFile(lua_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        add(z, os.path.join(LUA_SRC, 'enabled.txt'), 'E33Wardrobe/enabled.txt')
        add(z, os.path.join(ROOT, 'LICENSE'), 'E33Wardrobe/LICENSE.txt')
        info = zipfile.ZipInfo('E33Wardrobe/README.txt', date_time=time.localtime(os.path.getmtime(
            os.path.join(LUA_SRC, 'Scripts', 'main.lua')))[:6])
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, LUA_README.format(version=version).replace('\n', '\r\n'))
        for f in LUA_SCRIPTS:
            add(z, os.path.join(LUA_SRC, 'Scripts', f), 'E33Wardrobe/Scripts/' + f)

    tools_zip = os.path.join(a.out, f'E33Wardrobe-Tools-{version}.zip')
    base = 'E33Wardrobe Tools'
    with zipfile.ZipFile(tools_zip, 'w', zipfile.ZIP_DEFLATED) as z:
        for f in TOP_FILES:
            add(z, os.path.join(ROOT, f), f'{base}/{f}')
        with open(os.path.join(ROOT, 'THIRD_PARTY_NOTICES.md'), encoding='utf-8') as fh:
            notices = fh.read()
        if not a.with_rules:
            notices, n = RULES_NOTICE.subn('', notices)
            if n != 1:
                raise SystemExit('THIRD_PARTY_NOTICES.md: the rules-file notice was not found once')
        info = zipfile.ZipInfo(f'{base}/THIRD_PARTY_NOTICES.md', date_time=time.localtime(os.path.getmtime(
            os.path.join(ROOT, 'THIRD_PARTY_NOTICES.md')))[:6])
        info.external_attr = 0o644 << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, notices)
        add_tree(z, os.path.join(ROOT, 'LICENSES'), f'{base}/LICENSES')
        add_tree(z, os.path.join(ROOT, 'docs'), f'{base}/docs')
        for f in TOOL_FILES:
            add(z, os.path.join(ROOT, 'tools', f), f'{base}/tools/{f}')
        if a.with_rules:
            add_tree(z, os.path.join(ROOT, 'tools', 'rules'), f'{base}/tools/rules')
        add(z, os.path.join(LUA_SRC, 'enabled.txt'), f'{base}/lua/E33Wardrobe/enabled.txt')
        for f in LUA_SCRIPTS + ['variants.lua']:
            add(z, os.path.join(LUA_SRC, 'Scripts', f), f'{base}/lua/E33Wardrobe/Scripts/{f}')

    for p in (lua_zip, tools_zip):
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
        print(f'{p}: {len(names)} files, {os.path.getsize(p) // 1024} KB')
    if not a.with_rules:
        print('tools/rules not included (use --with-rules once the mod authors agree)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
