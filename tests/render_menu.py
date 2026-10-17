"""Render the in-game menu to PNG files, to look at layout changes without the game (needs lupa
and a Chromium; see docs/DEVELOPMENT.md).

usage: python tests/render_menu.py <out dir> [variants.lua] [--chrome PATH] [--font-dir DIR]
                                     [--menu menu.lua] [--main main.lua] [--zoom 2]

Runs the real main.lua and menu.lua in the UMG mock of test_lua_menu.py, walks the widget tree the
menu built (canvas > border > size box > vertical box > title bar, rows of text blocks and buttons,
help, status bar) and draws it as HTML with the same panel width, row height, font sizes, colours
(linear -> sRGB), paddings and slot rules (Auto / Fill, Fill / centred), then screenshots it with
headless Chromium. A Button is drawn as UMG's default style tinted by its background colour
(rounded 4px corners, 1-2px content padding); the engine's real style may pad captions more. Text is Roboto, the default
UMG font, when --font-dir has Roboto.ttf / Roboto-Bold.ttf. It is an approximation of Slate's
layout, close enough to see crowded rows, cut captions and wrong highlights.

Edit SCENES below to choose which screens are drawn. Each scene prints its widget count
(widgets built / widgets on screen), to keep an eye on what the menu costs the game thread.
--menu / --main draw another copy of the scripts (e.g. an older menu.lua, to compare); --zoom 2
draws at twice the pixels, to check 1px edges.
"""
import html
import os
import shutil
import subprocess
import sys
import tempfile

from lupa import lua54

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_lua_mock as base  # noqa: E402
import test_lua_menu as menu_test  # noqa: E402

SCRIPTS = os.path.join(HERE, '..', 'lua', 'E33Wardrobe', 'Scripts')

# (file name, list of actions); an action is ('key', id) or ('click', caption[, row label])
SCENES = [
    ('01_outfits_lune', [('key', 'DEL'), ('click', 'Lune')]),
    ('02_fav_empty', [('click', 'Favorites')]),
    ('03_fav_saved', [('click', 'Back'), ('click', 'On', 'Herald'), ('click', 'Favorites'), ('click', 'Save look'),
                      ('click', 'Back'), ('click', 'Off', 'Herald'), ('click', '>', 'Outfit · CC'),
                      ('click', 'Favorites'), ('click', 'Save look')]),
    ('04_fav_use', [('click', 'Use')]),
    ('05_outfits_after', [('click', 'Back')]),
    ('06_explain_row', [('click', 'Off', 'Herald'), ('click', 'On', 'Prefixed slot')]),
    ('07_keyboard_focus', [('click', 'OK'), ('click', 'Off', 'Prefixed slot'), ('key', 'C+DOWN_ARROW'),
                           ('key', 'C+DOWN_ARROW'), ('key', 'C+DOWN_ARROW'), ('key', 'C+RIGHT_ARROW')]),
    ('08_choose', [('click', 'Choose', 'Outfit · CC')]),
    ('09_choose_paged', [('click', 'Back'), ('click', 'Page >'), ('click', 'Choose', 'Many variants')]),
    ('10_all_tab', [('click', 'Back'), ('click', 'All')]),
    ('11_presets', [('click', 'Presets'), ('click', 'Save', 'Preset 2'), ('click', 'Store A')]),
    ('12_settings', [('click', 'Settings')]),
    ('13_disabled_why', [('click', 'Outfits'), ('click', 'Lune'), ('click', 'Undo'), ('click', 'Undo'),
                         ('click', 'Undo'), ('click', 'Undo')]),
]

DUMP = r'''
local function call(w, name) for i = #w._calls, 1, -1 do if w._calls[i][1] == name then return w._calls[i] end end end
local function col(c) if not c then return nil end return { c.R, c.G, c.B, c.A or 1 } end
function dumpWidget(w)
  local slot = w._slot
  local size = slot and call(slot, "SetSize")
  local pad = slot and call(slot, "SetPadding")
  local ownPad = call(w, "SetPadding")
  local wo, ho = call(w, "SetWidthOverride"), call(w, "SetHeightOverride")
  local ha = slot and call(slot, "SetHorizontalAlignment")
  local va = slot and call(slot, "SetVerticalAlignment")
  local wrap = call(w, "SetAutoWrapText")
  local d = { kind = w._kind, vis = w._vis, text = w._text, size = rawget(w, "Font") and rawget(w, "Font").Size or nil,
              color = w._color and col(w._color.SpecifiedColor) or nil, bg = col(w._bg), brush = col(w._brush),
              enabled = w._en ~= false,
              rule = size and size[2].SizeRule or nil, weight = size and size[2].Value or nil,
              pad = pad and { pad[2].Left, pad[2].Top, pad[2].Right, pad[2].Bottom } or nil,
              ownPad = ownPad and { ownPad[2].Left, ownPad[2].Top, ownPad[2].Right, ownPad[2].Bottom } or nil,
              wo = wo and wo[2] or nil, ho = ho and ho[2] or nil, halign = ha and ha[2] or nil, valign = va and va[2] or nil,
              wrap = wrap and wrap[2] or false, children = {} }
  for _, c in ipairs(w._children or {}) do d.children[#d.children + 1] = dumpWidget(c) end
  return d
end
function dumpMenu() local h = host(); if not h then return nil end return dumpWidget(h.WidgetTree.RootWidget) end
function builtWidgets() local n = 0; for _, w in ipairs(UMGW) do if not w._dead then n = n + 1 end end; return n end
'''


def srgb(c):
    if not c:
        return None
    def ch(x):
        x = max(0.0, min(1.0, float(x)))
        return 255 * (12.92 * x if x <= 0.0031308 else 1.055 * x ** (1 / 2.4) - 0.055)
    return f'rgba({ch(c[1]):.0f},{ch(c[2]):.0f},{ch(c[3]):.0f},{float(c[4]):.2f})'


def pad_css(p):
    return f'{p[2]}px {p[3]}px {p[4]}px {p[1]}px' if p else '0'


def to_html(d, parent_kind=None):
    if d is None or d.get('vis') == 1:                      # collapsed
        return ''
    kids = [d['children'][k] for k in sorted(d['children'])] if d.get('children') else []
    style = []
    if d.get('vis') == 2:
        style.append('visibility:hidden')
    if parent_kind == 'HorizontalBox':
        # a slot fills the row's height unless it is centred (UMG's default alignment is Fill)
        style.append('align-self:center' if d.get('valign') == 2 else 'align-self:stretch')
        if d.get('rule') == 1:
            # Slate shares all the free space among Fill slots by weight; CSS hands out only part
            # of it when the weights add up to less than 1, so scale them up (same proportions)
            style.append(f'flex:{100 * (d.get("weight") or 1)} 1 0;min-width:0')
        else:
            style.append('flex:0 0 auto')
    if d.get('pad'):
        style.append(f'margin:{pad_css(d.get("pad"))}')
    k = d.get('kind')
    inner = ''.join(to_html(c, k) for c in kids)
    if k == 'TextBlock':
        px = (d.get('size') or 24) * 96 / 72
        style += [f'font-size:{px:.1f}px', f'color:{srgb(d.get("color")) or "#fff"}',
                  'white-space:normal' if d.get('wrap') else 'white-space:nowrap;overflow:hidden']
        if parent_kind == 'Button':
            style.append('text-align:center')
        return f'<div class="t" style="{";".join(style)}">{html.escape(d.get("text") or "")}</div>'
    if k == 'Button':
        style += [f'background:{srgb(d.get("bg")) or "#ddd"}', 'border-radius:4px', 'padding:1px 2px',
                  'display:flex;align-items:center;justify-content:center;overflow:hidden']
        if not d.get('enabled'):
            style.append('opacity:0.55')
        return f'<div style="{";".join(style)}">{inner}</div>'
    if k == 'Border':
        style += [f'background:{srgb(d.get("brush")) or "transparent"}', f'padding:{pad_css(d.get("ownPad"))}']
        return f'<div style="{";".join(style)}">{inner}</div>'
    if k == 'SizeBox':
        if d.get('wo'):
            style.append(f'width:{d.get("wo")}px')
        if d.get('ho'):
            style.append(f'height:{d.get("ho")}px;display:flex;flex-direction:column')
        return f'<div style="{";".join(style)}"><div style="flex:1;display:flex;flex-direction:column">{inner}</div></div>'
    if k == 'HorizontalBox':
        style += ['display:flex;align-items:center;height:100%']
        return f'<div style="{";".join(style)}">{inner}</div>'
    if k == 'VerticalBox':
        style += ['display:flex;flex-direction:column']
        return f'<div style="{";".join(style)}">{inner}</div>'
    return f'<div style="{";".join(style)}">{inner}</div>'      # CanvasPanel etc.


def page(body, font_dir):
    faces = ''
    if font_dir and os.path.isfile(os.path.join(font_dir, 'Roboto.ttf')):
        faces = (f"@font-face{{font-family:R;src:url('file://{font_dir}/Roboto.ttf')}}"
                 f"@font-face{{font-family:R;font-weight:bold;src:url('file://{font_dir}/Roboto-Bold.ttf')}}")
    return (f'<!doctype html><meta charset="utf-8"><style>{faces}'
            'body{margin:0;background:#3a4a3a;font-family:R,Roboto,sans-serif}'
            '.t{line-height:1.25}#m{display:inline-block;padding:20px}</style>'
            f'<div id="m">{body}</div>')


def main():
    args = sys.argv[1:]
    chrome = font_dir = None
    if '--chrome' in args:
        i = args.index('--chrome'); chrome = args[i + 1]; del args[i:i + 2]
    if '--font-dir' in args:
        i = args.index('--font-dir'); font_dir = os.path.abspath(args[i + 1]); del args[i:i + 2]
    menu_src = main_src = None
    if '--menu' in args:
        i = args.index('--menu'); menu_src = os.path.abspath(args[i + 1]); del args[i:i + 2]
    zoom = 1
    if '--zoom' in args:
        i = args.index('--zoom'); zoom = float(args[i + 1]); del args[i:i + 2]
    if '--main' in args:
        i = args.index('--main'); main_src = os.path.abspath(args[i + 1]); del args[i:i + 2]
    if not args or args[0].startswith('-'):
        print(__doc__)
        return 2
    out = os.path.abspath(args[0])
    os.makedirs(out, exist_ok=True)
    variants_src = open(args[1], encoding='utf-8').read() if len(args) > 1 else menu_test.variants()
    chrome = chrome or shutil.which('chromium') or shutil.which('google-chrome')

    tmp = tempfile.mkdtemp(prefix='e33render_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    shutil.copy(main_src or os.path.join(SCRIPTS, 'main.lua'), os.path.join(scripts, 'main.lua'))
    shutil.copy(menu_src or os.path.join(SCRIPTS, 'menu.lua'), os.path.join(scripts, 'menu.lua'))
    open(os.path.join(scripts, 'variants.lua'), 'w', encoding='utf-8').write(variants_src)
    L = lua54.LuaRuntime(unpack_returned_tuples=True)
    L.execute(base.MOCK)
    L.execute(menu_test.UMG_MOCK)
    L.execute(base.SCENARIO)
    L.eval('function(src, name) local f, e = load(src, name); if not f then error(e) end; return f end')(
        open(os.path.join(scripts, 'main.lua'), encoding='utf-8').read(), '@' + os.path.join(scripts, 'main.lua'))()
    L.execute(DUMP)
    G = L.globals()
    for name, actions in SCENES:
        for a in actions:
            if a[0] == 'key':
                G.key(a[1])
            elif not G.click(*a[1:]):
                print(f'{name}: no button {a[1:]!r} on screen')
        d = L.eval('function() return dumpMenu() end')()
        tree = to_py(d)
        print(f'{name}: {G.builtWidgets()} widgets built, {count(tree)} on screen')
        htm = os.path.join(out, name + '.html')
        open(htm, 'w', encoding='utf-8').write(page(to_html(tree), font_dir))
        if chrome:
            png = os.path.join(out, name + '.png')
            subprocess.run([chrome, '--headless', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                            f'--screenshot={png}', '--window-size=760,820', f'--force-device-scale-factor={zoom}',
                            'file://' + htm],
                           capture_output=True, timeout=60)
            print(png if os.path.isfile(png) else f'{name}: screenshot failed')
    shutil.rmtree(tmp, ignore_errors=True)


def count(d):
    """Widgets drawn: the ones not collapsed (and not inside a collapsed one)."""
    if d is None or d.get('vis') == 1:
        return 0
    return 1 + sum(count(c) for c in (d.get('children') or {}).values())


def to_py(t):
    if t is None or not hasattr(t, 'items'):
        return t
    d = {}
    for k, v in t.items():
        d[k] = to_py(v)
    if isinstance(d.get('children'), dict):
        d['children'] = {int(k): v for k, v in d['children'].items()}
    return d


if __name__ == '__main__':
    sys.exit(main())
