"""The background queue: one worker thread runs add / reinstall / remove jobs one after another.

The relocator runs IN-PROCESS (the frozen app has no python.exe): e33_relocate.main(argv) with
sys.stdout / sys.stderr sent to a writer that turns its lines into progress ("[<mod>] <option> ..."
starts an option) and notes ("skipped: ..."). A SystemExit with a message fails the step with
that message. Whatever happens, a job ends as done or failed and the queue moves on.
"""
import collections
import os
import queue
import shutil
import sys
import threading
import time
import traceback

from . import archives, library, paths

STEP_LABELS = {
    'unpack': 'Unpacked',
    'sort': 'Sorted by outfit',
    'install': 'Preparing for the in-game menu',
    'remove': 'Removed from the in-game menu',
    'delete': 'Deleted from the library',
}
KEEP_JOBS = 30


class JobFailed(Exception):
    """A plain sentence for the user."""


class Job:
    def __init__(self, jid, kind, name, size, steps, payload=None, mod_id=None):
        self.id, self.kind, self.name, self.size = jid, kind, name, size
        self.status = 'waiting'
        self.steps = [{'key': k, 'label': STEP_LABELS[k], 'state': 'todo', 'detail': ''} for k in steps]
        self.error = None
        self.mod_id = mod_id
        self.payload = payload or {}
        self.notes = []

    def step(self, key):
        return next(s for s in self.steps if s['key'] == key)

    def to_json(self):
        return {'id': self.id, 'name': self.name, 'size': self.size, 'kind': self.kind, 'status': self.status,
                'steps': [dict(s, tags=list(s['tags'])) if 'tags' in s else dict(s) for s in self.steps],
                'error': self.error, 'mod_id': self.mod_id, 'notes': list(self.notes)}


class LineWriter:
    """sys.stdout / sys.stderr while the relocator runs: complete lines go to `on_line`. Writes
    from other threads pass through to the original stream."""
    encoding = 'utf-8'
    errors = 'replace'

    def __init__(self, on_line, passthrough, owner):
        self.on_line, self.passthrough, self.owner = on_line, passthrough, owner
        self.buf = ''

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        if threading.current_thread() is not self.owner:
            if self.passthrough is not None:
                try:
                    self.passthrough.write(s)
                except Exception:
                    pass
            return len(s)
        self.buf += s
        while '\n' in self.buf:
            line, self.buf = self.buf.split('\n', 1)
            try:
                self.on_line(line.rstrip('\r'))
            except Exception:
                pass
        return len(s)

    def flush(self):
        pass

    def isatty(self):
        return False

    def close_buffer(self):
        if self.buf:
            line, self.buf = self.buf, ''
            try:
                self.on_line(line)
            except Exception:
                pass


def run_relocator(argv, on_line):
    """e33_relocate.main(argv) in this thread with its output parsed. Returns (exit code, last lines).
    Raises JobFailed for a SystemExit that carries a message."""
    R = paths.tools()['relocate']
    tail = collections.deque(maxlen=200)

    def line(s):
        tail.append(s)
        on_line(s)
    old = sys.stdout, sys.stderr
    w = LineWriter(line, old[0], threading.current_thread())
    sys.stdout = sys.stderr = w
    try:
        try:
            rc = R.main(list(argv))
        except SystemExit as e:
            code = e.code
            if code is None or code == 0:
                rc = 0
            elif isinstance(code, int):
                rc = code
            else:
                w.close_buffer()
                raise JobFailed(library.plain_error(str(code)))
        w.close_buffer()
    finally:
        sys.stdout, sys.stderr = old
    return (rc if isinstance(rc, int) else 0), list(tail)


def _last_meaningful(tail):
    for s in reversed(tail):
        s = s.strip()
        if s and not s.startswith(('usage:', 'Report', 'Relocated paks', 'Log and report', 'Lua mod written')):
            return s
    return ''


class JobQueue:
    """`env` (the Api) provides _context() -> dict(root, paks, library, lua_dir, retoc) (raises
    JobFailed when the game isn't set) and _bump() (something changed: the UI refreshes)."""

    def __init__(self, env):
        self.env = env
        self.lock = threading.RLock()
        self.jobs = []
        self.q = queue.Queue()
        self.next_id = 1
        self.thread = None

    # -- submitting
    def _submit(self, kind, name, size, steps, payload=None, mod_id=None):
        with self.lock:
            job = Job(self.next_id, kind, name, size, steps, payload, mod_id)
            self.next_id += 1
            self.jobs.append(job)
            finished = [j for j in self.jobs if j.status in ('done', 'failed')]
            while len(self.jobs) > KEEP_JOBS and finished:
                self.jobs.remove(finished.pop(0))
            if self.thread is None or not self.thread.is_alive():
                self.thread = threading.Thread(target=self._worker, name='e33-jobs', daemon=True)
                self.thread.start()
        self.q.put(job)
        self.env._bump()
        return job.id

    def add(self, group):
        return self._submit('add', archives.group_label(group), archives.group_size(group),
                            ['unpack', 'sort', 'install'], payload=group)

    def reinstall(self, mod_id, size=0):
        return self._submit('reinstall', mod_id, size, ['install'], mod_id=mod_id)

    def remove(self, mod_id, delete_files, size=0):
        steps = ['remove'] + (['delete'] if delete_files else [])
        return self._submit('remove', mod_id, size, steps, payload={'delete': bool(delete_files)}, mod_id=mod_id)

    # -- reading
    def snapshot(self):
        with self.lock:
            return [j.to_json() for j in self.jobs]

    def clear_finished(self):
        with self.lock:
            n = len(self.jobs)
            self.jobs = [j for j in self.jobs if j.status not in ('done', 'failed')]
            return n - len(self.jobs)

    def pending(self, kind, mod_id):
        """Id of a waiting job of this kind for this mod (a second click adds nothing)."""
        with self.lock:
            for j in self.jobs:
                if j.status == 'waiting' and j.kind == kind and j.mod_id == mod_id:
                    return j.id
        return None

    def busy(self):
        with self.lock:
            return any(j.status in ('waiting', 'working') for j in self.jobs)

    def active_mod_ids(self):
        with self.lock:
            return {j.mod_id for j in self.jobs if j.status in ('waiting', 'working') and j.mod_id}

    def wait(self, timeout=None):
        """Block until the queue is idle (tests)."""
        end = None if timeout is None else time.time() + timeout
        while self.busy():
            if end is not None and time.time() > end:
                return False
            time.sleep(0.1)
        return True

    # -- the worker
    def _worker(self):
        while True:
            job = self.q.get()
            try:
                with self.lock:
                    job.status = 'working'
                self.env._bump()
                getattr(self, '_run_' + job.kind)(job)
                with self.lock:
                    job.status = 'done'
            except JobFailed as e:
                self._fail(job, str(e))
            except BaseException as e:      # never leave the queue stuck (SystemExit included)
                self._log(job, traceback.format_exc())
                self._fail(job, f'Unexpected error: {type(e).__name__}: {e}'.rstrip(': '))
            finally:
                with self.lock:
                    for s in job.steps:
                        if s['state'] == 'run':
                            s['state'] = 'fail' if job.status == 'failed' else 'done'
                self.env._bump()

    def _fail(self, job, msg):
        with self.lock:
            job.status = 'failed'
            job.error = msg
            for s in job.steps:
                if s['state'] == 'run':
                    s['state'] = 'fail'

    def _log(self, job, text):
        try:
            p = os.path.join(paths.app_data_dir(), 'backend.log')
            if os.path.isfile(p) and os.path.getsize(p) > 1024 * 1024:
                os.replace(p, p + '.old')
            with open(p, 'a', encoding='utf-8') as f:
                f.write(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] job {job.id} ({job.kind} {job.name}):\n{text}\n')
        except OSError:
            pass

    def _set(self, job, key, **kw):
        with self.lock:
            job.step(key).update(kw)

    # -- add
    def _run_add(self, job):
        ctx = self.env._context()
        lib = ctx['library']
        os.makedirs(lib, exist_ok=True)
        incoming = os.path.join(lib, '.incoming')
        os.makedirs(incoming, exist_ok=True)
        for e in os.listdir(incoming):                       # left by a run that was closed mid-way
            shutil.rmtree(paths.lp(os.path.join(incoming, e)), ignore_errors=True)
        work = os.path.join(incoming, f'job{job.id}')
        self._set(job, 'unpack', state='run', detail='')
        backup = target = None
        try:
            try:
                res = archives.unpack_group(job.payload, work, library=lib)
            except archives.ArchiveError as e:
                raise JobFailed(str(e))
            folder = res['folder']
            utoc = pak = False
            for _dp, _ds, fs in os.walk(paths.lp(folder)):
                utoc = utoc or any(f.lower().endswith('.utoc') for f in fs)
                pak = pak or any(f.lower().endswith('.pak') for f in fs)
            if not utoc:
                if pak:
                    raise JobFailed(f"{job.name} has only .pak files, no .utoc. The menu can't switch it; install it "
                                    'in Paks\\~mods by hand.')
                raise JobFailed(f'No game files (.utoc or .pak) in {job.name}. Is it an outfit mod?')
            if not library.option_folders(folder):
                raise JobFailed(f'{job.name} has no paks for Paks\\~mods (only LogicMods or UE4SS parts). Install it by '
                                'hand as the mod page says.')
            name = res['name']
            if res['in_place']:
                target = folder
            else:
                existing = [e for e in os.listdir(lib) if e.lower() == name.lower() and os.path.isdir(os.path.join(lib, e))]
                if existing:
                    name = existing[0]
                target = os.path.join(lib, name)
                with self.lock:
                    job.mod_id = name
                if existing:
                    backup = target + '.old'
                    shutil.rmtree(paths.lp(backup), ignore_errors=True)
                    try:
                        os.replace(paths.lp(target), paths.lp(backup))
                    except OSError as e:
                        backup = None
                        raise JobFailed(f"Couldn't replace the old version of {name}: a file in it is open ({e.strerror}). "
                                        'Close Explorer windows showing it and try again.')
                os.replace(paths.lp(folder), paths.lp(target))
            name = os.path.basename(target)
            with self.lock:
                job.mod_id = name
            n_opts = len(library.option_folders(target))
            detail = library.plural(n_opts, 'option') + ' found'
            if backup:
                detail += '; replaces the earlier version'
            for n in res.get('notes') or []:
                job.notes.append(n)
            self._set(job, 'unpack', state='done', detail=detail)
            self.env._bump()

            self._set(job, 'sort', state='run')
            try:
                groups = library.arrange_by_outfit(target)
            except OSError as e:
                raise JobFailed(f"Couldn't sort the options into outfit folders: {e.strerror or e}.")
            rows = library.menu_rows(target)
            tags = library.group_tags(groups) if groups else (
                [f'{lbl} · {n}' for lbl, n in rows] if len(rows) > 1 else [])
            self._set(job, 'sort', state='done', detail=library.plural(len(rows), 'row') + ' in the menu', tags=tags)

            self._relocate(job, target, ctx)
        except BaseException as e:
            restored = False
            if backup and os.path.isdir(paths.lp(backup)):
                try:
                    if target and os.path.isdir(paths.lp(target)):
                        shutil.rmtree(paths.lp(target))
                    os.replace(paths.lp(backup), paths.lp(target))
                    restored = True
                except OSError:
                    pass
            if restored and isinstance(e, JobFailed):
                raise JobFailed(f'{e} The earlier version was put back.')
            raise
        finally:
            shutil.rmtree(paths.lp(work), ignore_errors=True)
        if backup:
            shutil.rmtree(paths.lp(backup), ignore_errors=True)

    # -- install (relocate)
    def _relocate(self, job, mod_folder, ctx):
        self._set(job, 'install', state='run', detail='Starting', progress=0.0)
        if not ctx.get('retoc'):
            raise JobFailed("retoc was not found, so mods can't be prepared. It belongs in the app's bin folder: "
                            'reinstall the app.')
        R = paths.tools()['relocate']
        mod_name = os.path.basename(os.path.normpath(mod_folder))
        slots = R.option_slots(mod_folder)
        labels = {}
        for key, opts in slots.items():
            row = library.row_label(key, mod_name, [o['rel'] for o in opts])
            for o in opts:
                base = os.path.basename(o['rel'])
                if key == 'Main':
                    labels[o['rel']] = mod_name
                elif row == mod_name:                          # options straight in the mod's folder
                    labels[o['rel']] = library.option_label(base)
                elif key == base:                              # an on/off option: its own row
                    labels[o['rel']] = library.option_label(base)
                else:
                    labels[o['rel']] = f'{row} · {library.option_label(base, row)}'
        total = max(1, sum(len(v) for v in slots.values()))
        prefix = f'[{mod_name}] '
        state = {'k': 0}

        def on_line(s):
            if s.startswith(prefix) and s.endswith(' ...'):
                rel = s[len(prefix):-4]
                state['k'] += 1
                k = state['k']
                self._set(job, 'install', detail=f'Option {k} of {total}: {labels.get(rel, library.pretty(rel))}',
                          progress=round(min(0.99, (k - 0.5) / total), 3))
            elif s.strip().startswith('skipped:'):
                job.notes.append(library.plain_error(s.strip()[len('skipped:'):]))
            elif s.startswith('WARNING:'):
                job.notes.append(s[len('WARNING:'):].strip())

        argv = ['--paks', ctx['paks'], '--mod', mod_folder, '--retoc', ctx['retoc'], '--lua-dir', ctx['lua_dir']]
        try:
            rc, tail = run_relocator(argv, on_line)
        except OSError as e:
            raise JobFailed(f"Couldn't write {e.filename or 'a file'}: {e.strerror or e}. Is the game folder read-only?")
        view = library.View(ctx['library'], ctx['paks'], ctx['lua_dir'])
        rep = {k: v for k, v in view.report(mod_name).items() if not k.endswith('/(shared)')}
        ok = [k for k, v in rep.items() if not v.get('error')]
        failed = [v for v in rep.values() if v.get('error')]
        if rc != 0 or not ok:
            if failed:
                reasons = []
                for v in failed:
                    r = library.plain_error(v['error'])
                    if r not in reasons:
                        reasons.append(r)
                raise JobFailed(f"None of the {library.plural(len(rep), 'option')} could be prepared. "
                                + ' '.join(reasons[:2]))
            last = _last_meaningful(tail)
            raise JobFailed('The relocator stopped' + (f': {library.plain_error(last)}' if last else '.'))
        detail = library.plural(len(ok), 'option') + ' ready'
        if failed:
            detail += f'; {len(failed)} skipped'
        self._set(job, 'install', state='done', detail=detail, progress=1.0)

    # -- reinstall
    def _run_reinstall(self, job):
        ctx = self.env._context()
        folder = library.safe_child(ctx['library'], job.mod_id)
        if not folder or not os.path.isdir(paths.lp(folder)):
            self._set(job, 'install', state='run')
            raise JobFailed(f'The folder of {job.mod_id} is missing from the library.')
        self._relocate(job, folder, ctx)

    # -- remove
    def _run_remove(self, job):
        ctx = self.env._context()
        self._set(job, 'remove', state='run')
        view = library.View(ctx['library'], ctx['paks'], ctx['lua_dir'])
        in_menu = job.mod_id in view.by_name
        report_dir = view.report_dir(job.mod_id)
        if in_menu:
            rc, tail = run_relocator(['--remove', job.mod_id, '--paks', ctx['paks'], '--lua-dir', ctx['lua_dir']],
                                     lambda s: None)
            if rc != 0:
                raise JobFailed("Couldn't take it out of the menu"
                                + (f': {library.plain_error(_last_meaningful(tail))}' if _last_meaningful(tail) else '.'))
            detail = 'Taken out of the in-game menu'
        else:
            detail = "It wasn't in the in-game menu"
        out_root = os.path.join(ctx['paks'], '~mods', '_E33Wardrobe')
        if report_dir and os.path.isdir(report_dir) and paths.is_inside(report_dir, out_root) \
                and os.path.normcase(os.path.abspath(report_dir)) != os.path.normcase(os.path.abspath(out_root)):
            left = [f for _dp, _ds, fs in os.walk(report_dir) for f in fs if f.lower().endswith(('.utoc', '.ucas', '.pak'))]
            if not left:                                        # only logs, reports and swatches of a failed mod
                shutil.rmtree(report_dir, ignore_errors=True)
        self._set(job, 'remove', state='done', detail=detail)
        self.env._bump()
        if job.payload.get('delete'):
            self._set(job, 'delete', state='run')
            folder = library.safe_child(ctx['library'], job.mod_id)
            if folder and os.path.isdir(paths.lp(folder)):
                shutil.rmtree(paths.lp(folder), ignore_errors=True)
                if os.path.exists(paths.lp(folder)):
                    raise JobFailed(f"Couldn't delete {folder}: a file in it is open. Close it and try again.")
                self._set(job, 'delete', state='done', detail='Folder deleted')
            else:
                self._set(job, 'delete', state='done', detail='There was no folder')
