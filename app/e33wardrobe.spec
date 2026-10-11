# PyInstaller spec for "E33 Wardrobe.exe" (one folder, windowed). Built on Windows by
# .github/workflows/build-app.yml:   pyinstaller --noconfirm app/e33wardrobe.spec
# Needs bin/retoc.exe, bin/7z.exe and bin/7z.dll in the repository root first (the workflow
# downloads / copies them; they are not committed).
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
TOOLS = os.path.join(ROOT, 'tools')


def tree(src, dest):
    out = []
    for dp, _ds, fs in os.walk(src):
        if '__pycache__' in dp:
            continue
        for f in fs:
            out.append((os.path.join(dp, f), os.path.join(dest, os.path.relpath(dp, src))))
    return out


datas = (tree(os.path.join(ROOT, 'app', 'ui'), os.path.join('app', 'ui'))
         + [(os.path.join(ROOT, 'lua', 'E33Wardrobe', 'enabled.txt'), os.path.join('lua', 'E33Wardrobe'))]
         + [(os.path.join(ROOT, 'lua', 'E33Wardrobe', 'Scripts', f), os.path.join('lua', 'E33Wardrobe', 'Scripts'))
            for f in ('main.lua', 'menu.lua', 'config.example.lua', 'variants.lua')]
         + [(os.path.join(ROOT, f), '.') for f in ('LICENSE', 'THIRD_PARTY_NOTICES.md')]
         + [(os.path.join(ROOT, 'LICENSES'), 'LICENSES')])
binaries = [(os.path.join(ROOT, 'bin', f), 'bin') for f in ('retoc.exe', '7z.exe', '7z.dll')
            if os.path.isfile(os.path.join(ROOT, 'bin', f))]
if os.environ.get('E33_REQUIRE_BIN') and len(binaries) < 3:
    raise SystemExit('bin/retoc.exe, bin/7z.exe and bin/7z.dll are needed for a release build')
if os.path.isfile(os.path.join(ROOT, 'bin', '7-Zip-License.txt')):
    datas.append((os.path.join(ROOT, 'bin', '7-Zip-License.txt'), 'bin'))

a = Analysis(
    [os.path.join(ROOT, 'app', 'e33app.py')],
    pathex=[ROOT, TOOLS],
    binaries=binaries,
    datas=datas,
    hiddenimports=['app', 'app.backend', 'app.backend.api', 'app.backend.paths', 'app.backend.archives',
                   'app.backend.library', 'app.backend.jobs', 'app.backend.monitor', 'app.backend.assets',
                   'e33_relocate', 'e33common', 'e33legacy', 'e33utoc', 'e33tex', 'e33rules', 'py7zr'],
    excludes=['tkinter', 'unittest', 'pydoc', 'lupa', 'pytest', 'playwright'],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='E33 Wardrobe', console=False,
          icon=os.path.join(ROOT, 'app', 'icon.ico') if os.path.isfile(os.path.join(ROOT, 'app', 'icon.ico')) else None)
coll = COLLECT(exe, a.binaries, a.datas, name='E33 Wardrobe')
