"""Variant-mod model: scan a mod folder into choices, evaluate rules, resolve pak lists.

A mod folder is a tree of *option folders* (folders that directly hold .pak/.utoc/.ucas
files). Without a rules file, sibling option folders become one "pick one or none"
choice. A rules file (JSON, see rules/*.json) can instead describe friendly choices,
dependencies and auto-added fix paks.
"""
import ast
import fnmatch
import json
import os
import re

PAK_EXTS = ('.pak', '.utoc', '.ucas')
NONE = 'none'
SKIP_DIRS = {'logicmods', 'ue4ss', 'binaries', 'win64', 'wingdk'}   # parts the mixer doesn't install


def lp(path):
    """Windows long-path form, so library paths over 260 characters still work."""
    if os.name == 'nt':
        a = os.path.abspath(path)
        if not a.startswith('\\\\?\\') and len(a) > 240:
            return '\\\\?\\' + a
        return a
    return path


class RulesError(Exception):
    pass


# ----------------------------------------------------------------------------- expressions

_ALLOWED = (ast.Expression, ast.BoolOp, ast.And, ast.Or, ast.UnaryOp, ast.Not, ast.Compare,
            ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Name, ast.Load, ast.Constant, ast.Tuple, ast.List)


def compile_expr(src):
    tree = ast.parse(src, mode='eval')
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise RulesError(f'unsupported syntax in rule expression: {src!r}')
    return tree


def eval_expr(src, env):
    if src in (None, '', True):
        return True
    tree = compile_expr(src)

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.BoolOp):
            vals = (ev(v) for v in n.values)
            return all(vals) if isinstance(n.op, ast.And) else any(vals)
        if isinstance(n, ast.UnaryOp):
            return not ev(n.operand)
        if isinstance(n, ast.Compare):
            left = ev(n.left)
            for op, right_n in zip(n.ops, n.comparators):
                right = ev(right_n)
                ok = {ast.Eq: left == right, ast.NotEq: left != right}.get(type(op))
                if ok is None:
                    ok = (left in right) if isinstance(op, ast.In) else (left not in right)
                if not ok:
                    return False
                left = right
            return True
        if isinstance(n, ast.Name):
            if n.id not in env:
                raise RulesError(f'unknown choice {n.id!r} in rule expression {src!r}')
            return env[n.id]
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, (ast.Tuple, ast.List)):
            return tuple(ev(e) for e in n.elts)
        raise RulesError(f'unsupported expression {src!r}')
    return ev(tree)


# ----------------------------------------------------------------------------- scanning

def pak_files_in(folder):
    try:
        folder = lp(folder)
        return sorted(f for f in os.listdir(folder)
                      if f.lower().endswith(PAK_EXTS) and os.path.isfile(os.path.join(folder, f)))
    except OSError:
        return []


def find_option_folders(root):
    """Relative paths (forward slashes) of folders that directly contain pak files.
    LogicMods / UE4SS folders are skipped: those parts don't go into ~mods."""
    out = []
    base = lp(root)
    for dirpath, dirs, _files in os.walk(base):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.') and d.lower() not in SKIP_DIRS)
        if pak_files_in(dirpath):
            rel = os.path.relpath(dirpath, base).replace(os.sep, '/')
            out.append('' if rel == '.' else rel)
    return out


def extra_parts(root):
    """Names of non-~mods parts in a mod (LogicMods paks, UE4SS Lua) for a warning."""
    found = set()
    for dirpath, dirs, files in os.walk(lp(root)):
        for d in dirs:
            if d.lower() == 'logicmods':
                found.add('LogicMods (Blueprint mod)')
            if d.lower() in ('ue4ss', 'scripts'):
                try:
                    if any(f.endswith('.lua') for f in os.listdir(os.path.join(dirpath, d))):
                        found.add('UE4SS Lua script')
                except OSError:
                    pass
        if any(f.lower().endswith('.lua') for f in files):
            found.add('UE4SS Lua script')
    return sorted(found)


def unwrap(root):
    """Descend through wrapper folders ('Mod-685-3-3-1/Mod V331/...') that only hold one folder."""
    for _ in range(4):
        try:
            entries = [e for e in os.listdir(lp(root)) if not e.startswith('.')]
        except OSError:
            return root
        dirs = [e for e in entries if os.path.isdir(os.path.join(lp(root), e))]
        files = [e for e in entries if e.lower().endswith(PAK_EXTS)]
        if files or len(dirs) != 1 or len(entries) - len(dirs) > 2:   # allow a readme or two
            return root
        if pak_files_in(os.path.join(root, dirs[0])):      # the only child is itself an option
            return root
        root = os.path.join(root, dirs[0])
    return root


def pretty(name):
    name = re.sub(r'_P$', '', name)
    return name.replace('_', ' ').strip() or name


def auto_rules(root, name):
    """Derive choices from the folder layout when no rules file exists."""
    options = find_option_folders(root)
    by_parent = {}
    for rel in options:
        parent = rel.rsplit('/', 1)[0] if '/' in rel else ''
        by_parent.setdefault(parent, []).append(rel)
    choices, paks = [], []
    n = 0
    for parent, kids in sorted(by_parent.items()):
        exclusive = [k for k in kids if not os.path.basename(k).startswith('_') and k != '']
        toggles = [k for k in kids if k not in exclusive]
        if len(exclusive) >= 2:
            n += 1
            cid = f'c{n}'
            choices.append({'id': cid, 'label': parent or name,
                            'options': [{'value': k, 'label': pretty(os.path.basename(k))} for k in exclusive],
                            'none_label': '(none)', 'default': NONE})
            paks.append({'path': '{%s}' % cid, 'when': f"{cid} != 'none'"})
        else:
            toggles += exclusive
        for k in toggles:
            n += 1
            cid = f'c{n}'
            label = pretty(os.path.basename(k)) if k else name
            choices.append({'id': cid, 'label': (parent + ' / ' if parent else '') + label, 'toggle': True,
                            'options': [{'value': 'on', 'label': 'On'}], 'none_label': 'Off', 'default': NONE})
            paks.append({'path': (k or '.').replace('{', '{{').replace('}', '}}'), 'when': f"{cid} == 'on'"})
    return {'format': 1, 'name': name, 'auto': True, 'choices': choices, 'paks': paks, 'checks': []}


def rules_match(rules, root):
    for p in rules.get('match', {}).get('paths', []):
        if not os.path.isdir(os.path.join(root, *p.split('/'))):
            return False
    return bool(rules.get('match', {}).get('paths'))


def _rules_files(root, rules_dirs):
    own = os.path.join(root, 'e33mixer.rules.json')
    if os.path.isfile(own):
        yield own
    for d in rules_dirs:
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.endswith('.json'):
                    yield os.path.join(d, fn)


def find_rules(root, rules_dirs, depth=3):
    """(rules, prefix): a rules file matching `root` or a folder up to `depth` levels below it
    (e.g. the mod inside a wrapper folder next to an add-on download). prefix is that folder's
    path relative to root ('' for root itself)."""
    level = [('', root)]
    for _ in range(depth + 1):
        nxt = []
        for prefix, folder in level:
            for path in _rules_files(folder, rules_dirs):
                try:
                    with open(path, encoding='utf-8') as f:
                        r = json.load(f)
                except (OSError, ValueError):
                    continue
                if path.endswith('e33mixer.rules.json') or rules_match(r, folder):
                    r['_source'] = path
                    return r, prefix
            try:
                for d in sorted(os.listdir(folder)):
                    full = os.path.join(folder, d)
                    if not d.startswith('.') and os.path.isdir(full) and not pak_files_in(full):
                        nxt.append(((prefix + '/' if prefix else '') + d, full))
            except OSError:
                pass
        level = nxt
    return None, ''


# ----------------------------------------------------------------------------- resolution

class Mod:
    def __init__(self, root, rules_dirs=(), name=None):
        self.root = unwrap(root)
        self.name = name or os.path.basename(os.path.normpath(root))
        rules, self.prefix = find_rules(self.root, rules_dirs)
        if rules is None:
            rules = auto_rules(self.root, os.path.basename(os.path.normpath(self.root)))
            rules['_source'] = 'auto'
            self.prefix = ''
        self.rules = rules
        self.extra_parts = extra_parts(self.root)
        self._folders = None

    def _p(self, rel):
        """Rule paths are relative to the folder the rules matched (self.prefix)."""
        return f'{self.prefix}/{rel}' if self.prefix else rel

    def folders(self):
        if self._folders is None:
            self._folders = find_option_folders(self.root)
        return self._folders

    def find_folder(self, basename):
        """An option folder with this name anywhere in the mod (add-on downloads dropped in)."""
        hits = [f for f in self.folders() if os.path.basename(f).lower() == basename.lower()]
        return hits[0] if hits else None

    def _options_for(self, ch, env):
        if 'options_from' in ch:
            for src in ch['options_from']:
                if eval_expr(src.get('when'), env):
                    found = [o for o in self.folders() if fnmatch.fnmatchcase(o, self._p(src['glob']))]
                    rx = re.compile(src['label_regex']) if src.get('label_regex') else None
                    opts = []
                    for o in found:
                        base = os.path.basename(o)
                        m = rx.search(base) if rx else None
                        opts.append({'value': o, 'label': m.group(1) if m else pretty(base)})
                    return opts
            return []
        return list(ch.get('options', []))

    def evaluate(self, selection):
        """Return (choices_view, env). Values are coerced to valid options in rule order."""
        env, view = {}, []
        for flag, basename in self.rules.get('flags', {}).items():
            env[flag] = self.find_folder(basename) is not None
        for ch in self.rules['choices']:
            env.setdefault(ch['id'], NONE)
        for ch in self.rules['choices']:
            cid = ch['id']
            visible = bool(eval_expr(ch.get('show_if'), env))
            opts = self._options_for(ch, env) if visible else []
            allow_none = 'none_label' in ch and bool(eval_expr(ch.get('allow_none_if'), env))
            values = [o['value'] for o in opts]
            want = selection.get(cid, ch.get('default', NONE))
            if not visible:
                val = NONE
            elif want in values or (want == NONE and allow_none):
                val = want
            else:
                pref = ch.get('prefer_label')
                pick = next((o['value'] for o in opts if pref and o['label'] == pref), None)
                default = ch.get('default', NONE)
                if pick is None and default in values:
                    pick = default
                if pick is None:
                    pick = NONE if allow_none or not values else values[0]
                val = pick
            env[cid] = val
            view.append({'id': cid, 'label': ch.get('label', cid), 'visible': visible,
                         'toggle': ch.get('toggle', False), 'help': ch.get('help', ''),
                         'options': ([{'value': NONE, 'label': ch['none_label']}] if allow_none else []) + opts,
                         'value': val})
        return view, env

    def resolve(self, selection):
        """Return dict(choices, env, paks=[rel folders], files=[(src_abs, name)], messages=[...])."""
        view, env = self.evaluate(selection)
        msgs, folders = [], []
        for entry in self.rules.get('paks', []):
            if not eval_expr(entry.get('when'), env):
                continue
            try:
                if 'find' in entry:
                    want = entry['find'].format(**env)
                    rel = self.find_folder(want)
                    if rel is None:
                        msgs.append({'level': 'error', 'text': entry.get('missing') or f'Missing in your copy of the mod: {want}'})
                        continue
                else:
                    tpl = entry['path']
                    single = re.fullmatch(r'\{\w+\}', tpl.strip()) is not None   # a choice value is already a full path
                    rel = (tpl if single or tpl in ('.', '') else self._p(tpl)).format(**env)
            except KeyError as e:
                raise RulesError(f'pak template {entry.get("path", entry.get("find"))!r} uses unknown choice {e}')
            rel = '' if rel in ('.', '') else rel
            if rel not in folders:
                folders.append(rel)
            if entry.get('note'):
                msgs.append({'level': 'info', 'text': entry['note']})
        files = []
        for rel in folders:
            src = os.path.join(self.root, *rel.split('/')) if rel else self.root
            got = pak_files_in(src) if os.path.isdir(src) else []
            if not got:
                msgs.append({'level': 'error', 'text': f'Missing in your copy of the mod: {rel or "(mod root)"}'})
            files += [(os.path.join(src, f), f) for f in got]
        if self.extra_parts:
            msgs.append({'level': 'warn', 'text': 'This mod also contains ' + ', '.join(self.extra_parts) +
                         '. The mixer only installs ~mods paks; install those parts by hand as the mod page says.'})
        for chk in self.rules.get('checks', []):
            if eval_expr(chk.get('when'), env):
                msgs.append({'level': chk.get('level', 'warn'), 'text': chk['message']})
        seen = {}
        for src, fn in files:
            if fn.lower() in seen and seen[fn.lower()] != src:
                msgs.append({'level': 'error', 'text': f'Two selected files share the name {fn}'})
            seen[fn.lower()] = src
        return {'choices': view, 'env': env, 'paks': folders, 'files': files, 'messages': msgs}
