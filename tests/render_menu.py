"""Render the in-game menu to PNG files, to look at layout changes without the game (needs lupa
and a Chromium; see docs/DEVELOPMENT.md).

usage: python tests/render_menu.py <out dir> [variants.lua] [--chrome PATH] [--font-dir DIR]

Runs the real main.lua and menu.lua in the UMG mock of test_lua_menu.py, walks the widget tree the
menu built (canvas > border > size box > vertical box > rows of text blocks and buttons) and draws
it as HTML with the same panel width, row height, font sizes, colours (linear -> sRGB) and slot
size rules (Auto / Fill), then screenshots it with headless Chromium. Text is Roboto, the default
UMG font, when --font-dir has Roboto.ttf / Roboto-Bold.ttf. It is an approximation of Slate's
layout, close enough to see crowded rows, cut captions and wrong highlights.

Edit SCENES below to choose which screens are drawn.
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
    ('03_fav_saved', [('click', 'Back'), ('click', 'On', 'Altered Flower'), ('click', 'Favorites'), ('click', 'Save look'),
                      ('click', 'Back'), ('click', 'Off', 'Altered Flower'), ('click', '>', 'Cheeki'),
                      ('click', 'On', 'Infernal Herald'), ('click', 'Favorites'), ('click', 'Save look')]),
    ('04_fav_use', [('click', 'Use')]),
    ('05_outfits_after', [('click', 'Back')]),
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
  local wrap = call(w, "SetAutoWrapText")
  local d = { kind = w._kind, vis = w._vis, text = w._text, size = rawget(w, "Font") and rawget(w, "Font").Size or nil,
              color = w._color and col(w._color.SpecifiedColor) or nil, bg = col(w._bg), brush = col(w._brush),
              enabled = w._en ~= false,
              rule = size and size[2].SizeRule or nil, weight = size and size[2].Value or nil,
              pad = pad and { pad[2].Left, pad[2].Top, pad[2].Right, pad[2].Bottom } or nil,
              ownPad = ownPad and { ownPad[2].Left, ownPad[2].Top, ownPad[2].Right, ownPad[2].Bottom } or nil,
              wo = wo and wo[2] or nil, ho = ho and ho[2] or nil, halign = ha and ha[2] or nil,
              wrap = wrap and wrap[2] or false, children = {} }
  for _, c in ipairs(w._children or {}) do d.children[#d.children + 1] = dumpWidget(c) end
  return d
end
function dumpMenu() local h = host(); if not h then return nil end return dumpWidget(h.WidgetTree.RootWidget) end
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
        if d.get('rule') == 1:
            style.append(f'flex:{d.get("weight") or 1} 1 0;min-width:0')
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
    out = os.path.abspath(args[0])
    os.makedirs(out, exist_ok=True)
    variants_src = open(args[1], encoding='utf-8').read() if len(args) > 1 else menu_test.variants()
    chrome = chrome or shutil.which('chromium') or shutil.which('google-chrome')

    tmp = tempfile.mkdtemp(prefix='e33render_')
    scripts = os.path.join(tmp, 'E33Wardrobe', 'Scripts')
    os.makedirs(scripts)
    for f in ('main.lua', 'menu.lua'):
        shutil.copy(os.path.join(SCRIPTS, f), scripts)
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
        htm = os.path.join(out, name + '.html')
        open(htm, 'w', encoding='utf-8').write(page(to_html(tree), font_dir))
        if chrome:
            png = os.path.join(out, name + '.png')
            subprocess.run([chrome, '--headless', '--disable-gpu', '--no-sandbox', '--hide-scrollbars',
                            f'--screenshot={png}', '--window-size=760,820', 'file://' + htm],
                           capture_output=True, timeout=60)
            print(png if os.path.isfile(png) else f'{name}: screenshot failed')
    shutil.rmtree(tmp, ignore_errors=True)


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
    main()
