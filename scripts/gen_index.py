"""Write docs/index.md: every file with its one-line purpose, the app's API, the mod's game hooks,
every config key and environment variable, and the log lines the app reads. All of it is read
from the code, so the index can't drift from it.

    python scripts/gen_index.py           write docs/index.md
    python scripts/gen_index.py --check   exit 1 if docs/index.md is out of date, or a file has
                                          no header line saying what it is (tests run this)
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'docs', 'index.md')

# folders that aren't source: build output, user data, generated renders
SKIP_DIRS = {'.git', 'dist', 'release', 'bin', 'build_app', 'dist_app', '__pycache__', 'LICENSES', 'node_modules',
             '.pytest_cache', '--help'}
SKIP_FILES = {'docs/index.md'}
EXTS = ('.py', '.lua', '.js', '.html', '.css', '.bat', '.spec', '.yml', '.ini', '.md', '.json', '.txt')
# files that are data and can't carry a header
DATA = {
    'lua/E33Wardrobe/enabled.txt': 'UE4SS reads it: "1" starts the mod',
    'LICENSE': 'MIT licence',
}


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


def git_ignored(root, paths):
    """The paths git ignores (local config, build output): not indexed, so the index is the same on
    a fresh checkout (CI) as here. Without git (or outside a repository) nothing is skipped."""
    import subprocess
    try:
        # -z and bytes: text mode on Windows would send CRLF, and git would match nothing
        p = subprocess.run(['git', '-C', root, 'check-ignore', '-z', '--stdin'],
                           input='\0'.join(paths).encode('utf-8'), capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    if p.returncode not in (0, 1):
        return set()
    return {s for s in p.stdout.decode('utf-8', 'replace').split('\0') if s}   # paths may hold spaces


def source_files_all(root=ROOT):
    out = []
    for d, dirs, files in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith('.') or x == '.github')
        for f in sorted(files):
            p = os.path.join(d, f)
            r = os.path.relpath(p, root).replace(os.sep, '/')
            if r in SKIP_FILES or r.startswith('tools/rules/'):
                continue
            if f.endswith(EXTS) or f in ('LICENSE',):
                out.append(r)
    return out


def source_files(root=ROOT):
    out = source_files_all(root)
    ignored = git_ignored(root, out)
    return [r for r in out if r not in ignored]


def header(root, r):
    """The file's own first line saying what it is, or None."""
    if r in DATA:
        return DATA[r]
    try:
        text = open(os.path.join(root, r), encoding='utf-8', errors='replace').read(4000)
    except OSError:
        return None
    lines = text.splitlines()
    ext = os.path.splitext(r)[1].lower()
    if ext == '.py':
        m = re.search(r'^(?:#![^\n]*\n)?(?:#[^\n]*\n)*\s*[rb]?("""|\'\'\')(.*?)(?:\1|\n\s*\n)', text, re.S | re.M)
        return clean(m.group(2)) if m else None
    if ext == '.lua':
        m = re.match(r'\s*--\[\[(.*?)(?:\n\s*\n|\]\])', text, re.S)      # --[[ block: its first paragraph
        if m and m.group(1).strip():
            return clean(m.group(1))
        para = []
        for ln in lines:                                                   # -- lines at the top
            m = re.match(r'^--(?!\[\[)\s?(.*)$', ln.strip())
            if not m or not m.group(1).strip():
                break
            para.append(m.group(1))
        return clean(' '.join(para)) if para else None
    if ext in ('.js', '.css'):
        m = re.match(r'\s*/\*(.*?)(?:\*/|\n\s*\n)', text, re.S)
        return clean(m.group(1)) if m else None
    if ext == '.html':
        m = re.search(r'<!--\s*(.+?)\s*-->', '\n'.join(lines[:4]), re.S)    # a comment at the very top
        return clean(m.group(1).splitlines()[0]) if m else None
    if ext == '.md':
        for i, ln in enumerate(lines[:12]):
            if ln.startswith('#'):
                title = ln.lstrip('#').strip()
                if len(re.findall(r'[A-Za-z]{2,}', title)) >= 2:
                    return clean(title)
                # a one-word title: add the first sentence under it
                body = next((x.strip() for x in lines[i + 1:i + 15]
                             if x.strip() and not x.startswith(('#', '-', '|', '>', '`', '['))), '')
                body = re.sub(r'[*`\[\]]|\(([^)]*)\)', '', body).split('. ')[0]
                return clean(f'{title}: {body}' if body else title)
            if ln.startswith('name:') and r.startswith('.github/'):   # issue template front matter
                return clean(ln.split(':', 1)[1])
        return None
    if ext == '.json':
        return 'Data.'
    para = []                                   # .bat .spec .yml .ini .txt: the first comment block near the top
    for ln in lines[:12]:
        m = re.match(r'^\s*(?:#|::|REM\b|;)\s?(.*)$', ln, re.I)
        if m and not m.group(1).startswith('!'):
            if m.group(1).strip():
                para.append(m.group(1).strip())
                continue
        if para:
            break
    return clean(' '.join(para)) if para else None


def clean(s):
    s = re.sub(r'\s+', ' ', s).strip().rstrip('*/').strip()
    # the first sentence (a full stop followed by a space and a capital letter or the end)
    m = re.match(r'(.+?[A-Za-z0-9)`"\']{2})\.(?=\s+[A-Z(]|$)', s)
    if m:
        s = m.group(1)
    if len(s) > 150:
        s = s[:148].rsplit(' ', 1)[0].rstrip(',;:(/ ') + ' …'
    if s.endswith('.') or s.endswith(':'):
        s = s[:-1]
    # a header says what the file is: at least two words (not "[[", "<!--", a lone name)
    return s if len(re.findall(r'[A-Za-z]{2,}', s)) >= 2 else None


def read(r):
    return open(os.path.join(ROOT, r), encoding='utf-8', errors='replace').read()


def api_methods():
    m = re.search(r'^METHODS = \[(.*?)\]', read('app/e33app.py'), re.S | re.M)
    names = re.findall(r"'(\w+)'", m.group(1)) if m else []
    defined = {}
    for r in ('app/backend/api.py',):
        src = read(r)
        for dm in re.finditer(r'@api_method\s*\n\s*def (\w+)\(', src):
            defined[dm.group(1)] = r
    doc = read('app/API.md')
    rows = []
    for n in names:
        rows.append((n, defined.get(n, 'NOT DEFINED'), 'yes' if re.search(r'\b%s\b' % n, doc) else 'MISSING'))
    extra = sorted(set(defined) - set(names))
    return rows, extra


def dev_routes():
    src = read('app/e33app.py')
    routes = sorted(set(re.findall(r"""['"](/api/?|/[\w./-]*)['"]""", src)))
    return [r for r in routes if r.startswith('/')]


def lua_hooks():
    rows = []
    for r in ('lua/E33Wardrobe/Scripts/main.lua', 'lua/E33Wardrobe/Scripts/menu.lua'):
        src = read(r)
        code = re.sub(r'--[^\n]*', '', src)              # registrations in code, not in comments
        for m in re.finditer(r'\b(Register(?!Hook\b)\w*Hook\w*|RegisterConsoleCommandHandler|RegisterKeyBind)\s*[,(]', code):
            rows.append((m.group(1), '', r))
        for m in re.finditer(r'RegisterHook\s*,?\s*\(?\s*"([^"]+)"\s*[,)]', code):
            rows.append(('RegisterHook', m.group(1), r))
        for m in re.finditer(r'"/Script/SandFall\.CharacterSkinAssignPolicy:" \.\. fn', src):
            pol = re.search(r'POLICY_FUNCS = \{([^}]*)\}', src)
            for f in re.findall(r'"(\w+)"', pol.group(1) if pol else ''):
                rows.append(('RegisterHook', '/Script/SandFall.CharacterSkinAssignPolicy:' + f, r))
    seen, out = set(), []
    for row in rows:
        if row not in seen and not row[0].startswith('RegisterKeyBind'):
            seen.add(row)
            out.append(row)
    return out


def lua_settings():
    src = read('lua/E33Wardrobe/Scripts/main.lua')
    m = re.search(r'^local SETTINGS = \{(.*?)\}\s*$', src, re.S | re.M)
    return re.findall(r'(\w+)\s*=\s*("[^"]*"|[\w.]+)', m.group(1)) if m else []


def lua_config_keys():
    src = read('lua/E33Wardrobe/Scripts/config.example.lua')
    keys = re.findall(r'^\s{8}(\w+)\s*=\s*\{\s*"([^"]+)",\s*\{([^}]*)\}', src, re.M)
    return [(k, '+'.join(re.findall(r'"(\w+)"', mods) + [key])) for k, key, mods in keys]


def app_settings():
    src = read('app/backend/api.py')
    return sorted(set(re.findall(r"self\._settings\.get\('(\w+)'", src)) | set(re.findall(r"new\['(\w+)'\]", src)))


def relocator_config():
    src = read('tools/e33_relocate.py')
    return sorted(set(re.findall(r"cfg\.get\('(\w+)'", src)) | set(re.findall(r"cfg\['(\w+)'\]", src)))


def env_vars():
    found = {}
    for r in source_files():
        if not r.endswith(('.py', '.yml', '.js', '.lua', '.spec')) or r == 'scripts/gen_index.py':
            continue
        for v in set(re.findall(r'\bE33_[A-Z0-9_]+\b', read(r))):
            found.setdefault(v, []).append(r)
    return sorted(found.items())


def monitor_rules():
    """(source, regex, title or handler) of every Rule(...) in monitor.py, read with the parser."""
    import ast
    rows = []
    for node in ast.walk(ast.parse(read('app/backend/monitor.py'))):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', None) == 'Rule':
            args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
            kw = {k.arg: (k.value.value if isinstance(k.value, ast.Constant) else None) for k in node.keywords}
            pattern = args[2] if len(args) > 2 else kw.get('pattern')
            if isinstance(pattern, str) is False and pattern is None:      # pattern built from pieces
                pattern = ''.join(x.value for x in ast.walk(node.args[2]) if isinstance(x, ast.Constant)
                                  and isinstance(x.value, str)) if len(node.args) > 2 else '?'
            title = args[4] if len(args) > 4 else kw.get('title')
            what = title or ('handled by ' + kw['special'] if kw.get('special') else '')
            rows.append((args[0], pattern, what or ''))
    rows.sort(key=lambda r: ('mod live ue4ss any'.split().index(r[0]) if r[0] in ('mod', 'live', 'ue4ss', 'any') else 9))
    return rows


def build():
    files = source_files()
    out = ['# Index (generated)', '',
           'Written by `scripts/gen_index.py` from the code. Do not edit by hand: run '
           '`python scripts/gen_index.py`. `tests/test_docs_index.py` fails when it is out of date.', '',
           '- [Files](#files)', '- [App API](#app-api)', '- [Game hooks](#game-hooks)',
           '- [Config keys](#config-keys)', '- [Environment variables](#environment-variables)',
           '- [Log lines the app reads](#log-lines-the-app-reads)', '',
           '## Files', '']
    group = None
    for r in files:
        g = r.split('/')[0] if '/' in r else '(root)'
        if g != group:
            group = g
            out += ['', f'### {g}', '', '| File | What it is |', '|---|---|']
        h = header(ROOT, r)
        out.append(f'| `{r}` | {(h or "**NO HEADER**").replace("|", "/")} |')
    rows, extra = api_methods()
    out += ['', '## App API', '',
            'The UI calls these through pywebview (`window.pywebview.api.<method>`), or in dev and tests through '
            '`POST /api/<method>` on `app/e33app.py --dev PORT`. The contract is `app/API.md`.', '',
            '| Method | Defined in | In API.md |', '|---|---|---|']
    out += [f'| `{n}` | `{d}` | {a} |' for n, d, a in rows]
    if extra:
        out += ['', 'Defined with `@api_method` but not exposed (not in `METHODS`): ' + ', '.join(f'`{x}`' for x in extra)]
    out += ['', 'Dev bridge paths (`app/e33app.py`): ' + ', '.join(f'`{r}`' for r in dev_routes())]
    out += ['', '## Game hooks', '', 'Where the in-game mod is entered from the game (UE4SS registrations).', '',
            '| Registration | Target | File |', '|---|---|---|']
    out += [f'| `{a}` | {("`" + b + "`") if b else ""} | `{c}` |' for a, b, c in lua_hooks()]
    out += ['', '## Config keys', '', '### In-game settings (`Mods/E33Wardrobe/settings.txt`, defaults in `main.lua` SETTINGS)', '',
            '| Key | Default |', '|---|---|']
    out += [f'| `{k}` | `{v}` |' for k, v in lua_settings()]
    out += ['', '### Keys (`Scripts/config.lua`, example in `config.example.lua`)', '', '| Name | Default key |', '|---|---|']
    out += [f'| `{k}` | `{v}` |' for k, v in lua_config_keys()]
    out += ['', '### App settings (app data folder, `app/backend/api.py`)', '',
            ', '.join(f'`{k}`' for k in app_settings()),
            '', '### Relocator config (`tools/e33wardrobe_config.json`, `tools/e33_relocate.py --save`)', '',
            ', '.join(f'`{k}`' for k in relocator_config())]
    out += ['', '## Environment variables', '', '| Variable | Used in |', '|---|---|']
    out += [f'| `{v}` | {", ".join(f"`{x}`" for x in sorted(fs))} |' for v, fs in env_vars()]
    out += ['', '## Log lines the app reads', '',
            '`app/backend/monitor.py` turns these lines into Game log problems. Changing their text in `main.lua` '
            'or `menu.lua` breaks the app; `tests/test_app_monitor.py` covers them. Source: `mod` = the menu\'s '
            'own messages (`[E33Wardrobe] …` in UE4SS.log, `log: …` in live_log.txt), `live` = other live_log.txt '
            'lines, `ue4ss` = UE4SS.log.', '',
            '| Source | Line (regular expression) | Shown in the Game log as |', '|---|---|---|']
    pipe = '\\|'                                  # a | inside a table cell
    out += ['| %s | %s | %s |' % (s, ('`%s`' % t.replace('|', pipe)) if t else '(no pattern: a handler passes it the line)',
                                  w.replace('|', '/')) for s, t, w in monitor_rules()]
    return '\n'.join(out) + '\n'


def problems(text):
    bad = [ln for ln in text.splitlines() if 'NO HEADER' in ln or 'NOT DEFINED' in ln or '| MISSING |' in ln]
    return bad


def main():
    text = build()
    if '--check' in sys.argv:
        bad = problems(text)
        stale = not os.path.isfile(OUT) or open(OUT, encoding='utf-8').read() != text
        for b in bad:
            print('PROBLEM ' + b)
        if stale:
            print('docs/index.md is out of date: run python scripts/gen_index.py')
        return 1 if (bad or stale) else 0
    with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    bad = problems(text)
    for b in bad:
        print('PROBLEM ' + b)
    print(f'wrote {rel(OUT)}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
