"""Find the problem mod: turn half of the suspects off, ask whether the problem still happens,
repeat with the half that has it, until one mod is left. A state machine kept in
%APPDATA%\\E33Wardrobe\\culprit.json, so it survives an app restart.

Mods that are cleared (shown not to cause it) stay ON in later rounds, so the game stays close to
normal. Mods that were already disabled are never touched, also ones the user disables by hand
while it runs (they are never added to `mine`). Turning a mod off or on is `switch(mod, on)`
(e33fixes.set_disabled through the Api); `is_off(mod)` tells whether a mod is disabled now.
The state is saved after every switch, and `off` always lists what is really off.

State: {active, started, round, suspects, cleared, off (suspects off this round), mine (mods it
has turned off right now), before (mods disabled before it started), history [{round, on, off,
answer}], found}.
"""
import datetime as _dt
import math
import os

from . import paths


class CulpritError(Exception):
    """A plain sentence for the user."""


def state_path():
    return os.path.join(paths.app_data_dir(), 'culprit.json')


def load():
    s = paths.read_json(state_path(), None)
    return s if isinstance(s, dict) and s.get('active') else None


def save(s):
    paths.write_json(state_path(), s)


def clear():
    try:
        os.remove(state_path())
    except OSError:
        pass


def rounds_left(n):
    return math.ceil(math.log2(n)) if n > 1 else 0


def in_hunt(mod, s=None):
    """True while a running hunt manages this mod (a suspect, cleared, or turned off by it)."""
    s = load() if s is None else s
    if not s:
        return False
    return mod in s.get('mine', []) or (not s.get('found') and (mod in s['suspects'] or mod in s['cleared']))


def status(s=None):
    """The wizard's view of the state ({'active': False} when not running)."""
    s = load() if s is None else s
    if not s:
        return {'active': False}
    suspects, off = s['suspects'], s.get('off') or []
    on = [m for m in suspects if m not in off]
    about = s['round'] if s.get('found') else s['round'] - 1 + rounds_left(len(suspects))
    return {'active': True, 'round': s['round'], 'rounds_about': about, 'on': on, 'off': off,
            'cleared': s['cleared'], 'before': s['before'], 'found': s.get('found'), 'history': s['history'],
            'started': s['started'], 'mine': list(s['mine'])}


def _set_off(s, want_off, switch, is_off):
    """Turn exactly `want_off` off (the ones it turned off before and no longer wants: back on).
    Saves after every switch; `off` ends up as what is really off. Raises CulpritError (state saved)
    when a mod can't be switched."""
    errors = []
    want = set(want_off)
    for m in [m for m in s['mine'] if m not in want]:
        try:
            switch(m, True)
            s['mine'].remove(m)
        except CulpritError as e:
            errors.append(str(e))
        save(s)
    for m in want_off:
        if m in s['mine']:
            continue
        if is_off(m):                       # the user's own choice: never adopted, never turned on
            continue
        try:
            switch(m, False)
            s['mine'].append(m)
        except CulpritError as e:
            errors.append(str(e))
        save(s)
    s['off'] = [m for m in want_off if m in s['mine'] or is_off(m)]
    save(s)
    if errors:
        raise CulpritError(' '.join(errors) + f" This round {len(s['off'])} of {len(want_off)} are off; the answers "
                                              'still count what is really off.')


def _next(s, switch, is_off):
    if len(s['suspects']) == 1:
        s['found'] = s['suspects'][0]
        _set_off(s, [s['found']], switch, is_off)
        s['off'] = []
        save(s)
        return
    half = math.ceil(len(s['suspects']) / 2)
    _set_off(s, s['suspects'][half:], switch, is_off)


def start(mods, disabled_before, switch, is_off=lambda m: False):
    """mods: every mod in the wardrobe; disabled_before: the ones already off (left alone)."""
    if load():
        raise CulpritError('Finding the problem mod is already running.')
    suspects = [m for m in mods if m not in set(disabled_before)]
    if len(suspects) < 2:
        raise CulpritError('This needs at least 2 mods that are on.')
    s = {'active': True, 'started': _dt.datetime.now().strftime('%Y-%m-%d %H:%M'), 'round': 1,
         'suspects': suspects, 'cleared': [], 'off': [], 'mine': [], 'before': sorted(disabled_before),
         'history': [], 'found': None}
    save(s)                         # first, so a crash halfway can still turn everything back on
    _next(s, switch, is_off)
    return status(s)


def answer(still_happens, switch, is_off=lambda m: False):
    """The user's answer for this round: True = the problem still happens."""
    s = load()
    if not s:
        raise CulpritError('Finding the problem mod is not running.')
    if s.get('found'):
        raise CulpritError('The problem mod was already found.')
    off = s['off']
    on = [m for m in s['suspects'] if m not in off]
    s['history'].append({'round': s['round'], 'on': on, 'off': list(off), 'answer': 'still' if still_happens else 'gone'})
    if still_happens:                   # it's among the ones that were on
        s['cleared'] += off
        s['suspects'] = on
    else:                               # it went away with these off: it's one of them
        s['cleared'] += on
        s['suspects'] = list(off)
    s['round'] += 1
    save(s)
    _next(s, switch, is_off)
    return status(s)


def finish(keep_off, switch, known=None, forget=False):
    """End: turn every mod it turned off back on, except the found one when keep_off. Tries every
    mod; mods no longer in the wardrobe (`known`: the current mod names) are dropped. The state is
    kept while some can't be turned back on, unless `forget` (then it is cleared anyway).
    -> {active, kept_off, errors: [sentences], dropped: [mods]}"""
    s = load()
    if not s:
        return {'active': False, 'kept_off': None, 'errors': [], 'dropped': []}
    keep = s.get('found') if keep_off else None
    errors, dropped = [], []
    for m in list(s['mine']):
        if m == keep:
            continue
        if known is not None and m not in known:
            s['mine'].remove(m)             # removed meanwhile: nothing to turn back on
            dropped.append(m)
            save(s)
            continue
        try:
            switch(m, True)
            s['mine'].remove(m)
        except CulpritError as e:
            errors.append(str(e))
        save(s)
    left = [m for m in s['mine'] if m != keep]
    if left and not forget:
        save(s)
    else:
        clear()
    return {'active': bool(left) and not forget, 'kept_off': keep, 'errors': errors, 'dropped': dropped, 'left': left}
