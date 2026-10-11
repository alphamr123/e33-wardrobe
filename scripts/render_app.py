"""Render the app's screens (mock data) to PNG, to look at the UI without Windows or the backend.

    python scripts/render_app.py OUT_DIR [--screens a,b,...] [--size 1200x760] [--fonts DIR] [--chrome PATH]

Opens app/ui/index.html?mock&screen=<name> in Playwright's Chromium for each screen. Windows has
Segoe UI; Linux doesn't, so for realistic text the script copies Roboto.ttf / Roboto-Bold.ttf from
--fonts (or $E33_RENDER_FONTS) into a temp dir and maps "Segoe UI" to it, only while rendering.
The app itself ships no fonts.

--check prints elements whose text is cut or wraps where it shouldn't (buttons, tabs, headers).
"""
import argparse
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE.parent / 'app' / 'ui' / 'index.html'

SCREENS = [
    'setup_not_found', 'setup_ok', 'setup_ue4ss_old',
    'mods_empty', 'mods_list', 'mods_details', 'mods_chic', 'tasks_running', 'confirm_remove',
    'mods_bulk', 'mods_expanded', 'mods_lune_color', 'ctx_details', 'ctx_modlist', 'image_viewer', 'confirm_bulk_remove',
    'gamelog_running', 'gamelog_idle', 'gamelog_filter', 'gamelog_last', 'gamelog_previous', 'drop_overlay', 'help',
]
DEFAULT_CHROME = os.path.expanduser('~/.cache/ms-playwright/chromium-1187/chrome-linux/chrome')
DEFAULT_FONTS = os.environ.get('E33_RENDER_FONTS')   # a folder with Roboto.ttf, to stand in for Segoe UI

CHECK_JS = r"""
() => {
  const out = [];
  const sel = '.btn, .tab, .minitab, .lv th, .sb, .dock-title span, legend, .status-line span, .infobar-text';
  for (const el of document.querySelectorAll(sel)) {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height || el.closest('[hidden]')) continue;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') continue;
    const cut = el.scrollWidth > el.clientWidth + 1 && cs.overflow !== 'visible';
    const lh = parseFloat(cs.lineHeight) || 18;
    const wraps = el.matches('.btn, .tab, .minitab') && el.scrollHeight > Math.max(el.clientHeight, lh) + 4;
    if (cut || wraps) out.push(`${cut ? 'cut' : 'wraps'}: <${el.tagName.toLowerCase()} class="${el.className}"> "${el.textContent.trim().slice(0, 60)}" (${Math.round(r.width)}px, needs ${el.scrollWidth}px)`);
  }
  // list cells cut with an ellipsis (the tooltip has the full text): reported as info
  for (const td of document.querySelectorAll('.lv td')) {
    if (td.closest('[hidden]') || !td.getClientRects().length) continue;
    if (td.scrollWidth > td.clientWidth + 1) {
      const lv = td.closest('.lv');
      out.push(`info, cell cut in #${lv && lv.id}: "${td.textContent.trim().slice(0, 50)}" (${td.clientWidth}px, needs ${td.scrollWidth}px)`);
    }
  }
  const vw = document.documentElement.clientWidth;
  if (document.documentElement.scrollWidth > vw + 1) out.push(`page scrolls horizontally: ${document.documentElement.scrollWidth} > ${vw}`);
  return out;
}
"""


def font_css(font_dir, tmp):
    """@font-face rules mapping "Segoe UI" to Roboto (copied into `tmp`), or '' when not found."""
    rules = []
    for fname, weight in (('Roboto.ttf', 400), ('Roboto-Bold.ttf', 700)):
        src = Path(font_dir) / fname
        if not src.is_file():
            continue
        dst = Path(tmp) / fname
        shutil.copyfile(src, dst)
        data = base64.b64encode(dst.read_bytes()).decode('ascii')
        weights = '400 500' if weight == 400 else '600 900'
        rules.append(f'@font-face{{font-family:"Segoe UI";font-weight:{weights};'
                     f'src:url(data:font/ttf;base64,{data}) format("truetype");}}')
    return '\n'.join(rules)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('out', help='folder for the PNGs')
    ap.add_argument('--screens', default=','.join(SCREENS), help='comma-separated screen names')
    ap.add_argument('--size', default='1200x760', help='viewport, WIDTHxHEIGHT')
    ap.add_argument('--fonts', default=DEFAULT_FONTS, help='folder with Roboto.ttf and Roboto-Bold.ttf')
    ap.add_argument('--chrome', default=DEFAULT_CHROME, help='Chromium executable (default: Playwright cache)')
    ap.add_argument('--suffix', default='', help='added to each file name, e.g. _small')
    ap.add_argument('--check', action='store_true', help='report cut or wrapping text')
    a = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    w, h = (int(x) for x in a.size.lower().split('x'))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    screens = [s.strip() for s in a.screens.split(',') if s.strip()]
    problems = 0
    with tempfile.TemporaryDirectory(prefix='e33fonts_') as tmp, sync_playwright() as pw:
        css = font_css(a.fonts, tmp) if a.fonts else ''
        if not css:
            print(f'note: no Roboto in {a.fonts}; rendering with system fonts', file=sys.stderr)
        # headless Chromium hides scrollbars by default; show them, as WebView2 does
        launch = {'args': ['--no-sandbox'], 'ignore_default_args': ['--hide-scrollbars']}
        if a.chrome and os.path.exists(a.chrome):
            launch['executable_path'] = a.chrome
        browser = pw.chromium.launch(**launch)
        for name in screens:
            ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1)
            page = ctx.new_page()
            errors = []
            page.on('pageerror', lambda e, errors=errors: errors.append(str(e)))
            page.on('console', lambda m, errors=errors: errors.append(m.text) if m.type == 'error' else None)
            if css:
                page.add_init_script(
                    "document.addEventListener('DOMContentLoaded',()=>{const s=document.createElement('style');"
                    f"s.textContent={json.dumps(css)};document.head.appendChild(s);}});")
            page.goto(f'{INDEX.as_uri()}?mock&screen={name}')
            page.wait_for_function('window.__e33_screen_ready === true', timeout=15000)
            page.evaluate('document.fonts.ready')
            page.wait_for_timeout(150)
            path = out / f'{name}{a.suffix}.png'
            page.screenshot(path=str(path))
            line = f'{path}'
            if a.check:
                found = page.evaluate(CHECK_JS)
                for f in found:
                    print(f'  [{name}] {f}')
                problems += len([f for f in found if not f.startswith('info')])
            for e in errors:
                print(f'  [{name}] page error: {e}')
                problems += 1
            print(line)
            ctx.close()
        browser.close()
    return 1 if (a.check and problems) else 0


if __name__ == '__main__':
    sys.exit(main())
