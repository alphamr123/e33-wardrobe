"""The app end to end: the real UI (app/ui) and backend (app/backend) through the dev HTTP bridge,
driven in Chromium with Playwright, against a fake game. Writes screenshots when E33_SHOTS is set.

Needs: playwright (+ a Chromium: E33_CHROME or Playwright's own), and the fixtures of
test_relocate_e2e.py: E33_E2E_PAKS, E33_E2E_BASE (a texture for the image viewer), E33_RETOC; plus
E33_SAMPLE_ARCHIVES: a folder with a few mod archives (.zip/.7z) of one Nexus mod. Skips (exit 0
with a SKIP line) when something is missing.
"""
import datetime as dt
import glob
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tools')]



def link_or_copy(src, dst):
    """A hard link (no copy of a big fixture), or a copy when the fixture is on another drive."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)

def main():
    need = [os.environ.get(k) for k in ('E33_E2E_PAKS', 'E33_RETOC', 'E33_SAMPLE_ARCHIVES', 'E33_E2E_BASE')]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('SKIP: playwright not installed')
        return 0
    if not all(need):
        print('SKIP: set E33_E2E_PAKS, E33_E2E_BASE, E33_RETOC and E33_SAMPLE_ARCHIVES')
        return 0
    paks_src, retoc, samples, base = need
    archives = sorted(glob.glob(os.path.join(samples, '*.7z')) + glob.glob(os.path.join(samples, '*.zip')))[:3]
    shots = os.environ.get('E33_SHOTS')
    tmp = tempfile.mkdtemp(prefix='e33appui_')
    fails = 0

    def check(name, cond, extra=''):
        nonlocal fails
        print(('PASS ' if cond else 'FAIL ') + name + ('' if cond else f'   -> {extra}'))
        fails += (not cond)

    # a fake game: Paks from the fixture (hard links), UE4SS present, no menu yet
    game = os.path.join(tmp, 'Expedition 33')
    paks = os.path.join(game, 'Sandfall', 'Content', 'Paks')
    shutil.copytree(paks_src, paks, copy_function=link_or_copy)
    ue4ss = os.path.join(game, 'Sandfall', 'Binaries', 'Win64', 'ue4ss')
    os.makedirs(os.path.join(ue4ss, 'Mods'))
    open(os.path.join(ue4ss, 'UE4SS.dll'), 'wb').close()
    open(os.path.join(ue4ss, 'UE4SS.log'), 'w').write('[12:00:00.000] UE4SS - v3.0.1 Beta #0 - Git SHA #527a483b\n')
    os.environ['E33_APPDATA'] = os.path.join(tmp, 'appdata')
    os.environ['E33_RETOC'] = retoc
    os.environ['E33_OFFLINE'] = '1'                    # no network lookups in tests

    from app import e33app
    from app.backend.api import Api
    api = Api()
    srv = e33app.run_dev(api, 0)
    url = f'http://127.0.0.1:{srv.server_address[1]}/index.html'
    chrome = os.environ.get('E33_CHROME') or os.path.expanduser('~/.cache/ms-playwright/chromium-1187/chrome-linux/chrome')

    def shot(page, name):
        if shots:
            os.makedirs(shots, exist_ok=True)
            page.screenshot(path=os.path.join(shots, name + '.png'))

    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=chrome if os.path.isfile(chrome) else None, args=['--no-sandbox'])
        page = b.new_page(viewport={'width': 1200, 'height': 760})
        page.goto(url)
        page.wait_for_timeout(1500)
        text = page.inner_text('body')
        check('first run without a known game: the Setup tab opens and asks for the game folder',
              'pick this folder' in text, text[:400])
        shot(page, '1_setup_not_found')

        r = page.evaluate('(root) => window.e33.call("set_game_folder", root)', game)
        check('setting the game folder works (any folder inside the game counts)', r.get('ok'), r)
        page.reload()
        page.wait_for_timeout(1500)
        notice = page.inner_text('#mods-notice') if page.locator('#mods-notice').is_visible() else ''
        check('with the game set but no in-game menu, a bar above the mod list offers to install it',
              'not installed' in notice, notice)
        shot(page, '2a_mods_notice')
        page.locator('.tab[data-tab="setup"]').click()
        page.wait_for_timeout(500)
        text = page.inner_text('body')
        check('  the game, UE4SS (with its version) and the missing menu show', 'Expedition 33' in text
              and '3.0.1' in text, text[:600])
        page.locator('.tab[data-tab="mods"]').click()
        page.locator('#mods-notice [data-act="install-menu"]').click()
        page.wait_for_timeout(1500)
        check('  the bar goes away once it is installed', not page.locator('#mods-notice').is_visible())
        page.locator('.tab[data-tab="setup"]').click()
        page.wait_for_timeout(300)
        check('Install puts the in-game menu into ue4ss\\Mods', os.path.isfile(os.path.join(ue4ss, 'Mods', 'E33Wardrobe',
                                                                                          'Scripts', 'main.lua')))
        shot(page, '2_setup_ok')

        page.locator('.tab[data-tab="mods"]').click()
        page.evaluate('(paths) => window.e33.devDrop(paths)', archives)
        t0 = time.time()
        done = False
        while time.time() - t0 < 180:
            st = api.poll()
            if st['jobs'] and all(j['status'] in ('done', 'failed') for j in st['jobs']):
                done = True
                break
            if time.time() - t0 > 2 and not shots_taken.get('tasks'):
                shot(page, '3_tasks')
                shots_taken['tasks'] = True
            page.wait_for_timeout(300)
        jobs = api.poll()['jobs']
        check(f'dropping {len(archives)} archives of one Nexus mod makes one job, which finishes',
              done and len(jobs) == 1 and jobs[0]['status'] == 'done', jobs)
        page.wait_for_timeout(2500)
        mods = api.list_mods()
        check('  the mod is in the list, ready', len(mods) == 1 and mods[0]['state'] == 'ready', mods)
        text = page.inner_text('body')
        check('  and on screen', mods and mods[0]['name'] in text, text[:500])
        page.locator('text=' + mods[0]['name']).first.click()
        page.wait_for_timeout(1000)
        text = page.inner_text('body')
        check('  its details show menu rows and options', 'Menu rows' in text, text[:800])
        shot(page, '4_details')
        mod_a = mods[0]['id']
        det = api.mod_details(mod_a)
        labels = [o['label'] for r in det['rows'] for o in r['options']]

        # right-click in the details: Copy all details
        page.locator('#details-body .d-head').click(button='right')
        page.wait_for_timeout(200)
        menu = page.inner_text('#ctxmenu') if page.locator('#ctxmenu').is_visible() else ''
        check('right-click in the details opens Copy items (not the browser menu)',
              'Copy all details' in menu and 'Copy' in menu, menu)
        shot(page, '4b_details_menu')
        page.locator('#ctxmenu .mi', has_text='Copy all details').click()
        page.wait_for_timeout(500)
        copied = page.evaluate('() => window.e33.ui.lastCopy()') or ''
        rows_part = copied.split('\nNotes\n')[0].split('\nMenu rows\n')[-1]
        check('  Copy all details: name, then each row with every option and what it changes, as plain text',
              copied.startswith(mod_a) and all(f'\n  {lb}\n' in rows_part for lb in labels) and 'Changes: ' in rows_part
              and '\nOverlaps\n' in copied, copied[:600])

        # a second mod: a folder with a texture of the fixture game, for the image viewer
        second = os.path.join(tmp, 'drop', 'Second Outfit')
        make_texture_option(base, retoc, os.path.join(second, 'Opt_P'), tmp)
        page.evaluate('(paths) => window.e33.devDrop(paths)', [second])
        api._jobs.wait(300)
        page.wait_for_timeout(2500)
        names = sorted(m['id'] for m in api.list_mods())
        check('a dropped folder becomes a second mod', names == sorted([mod_a, 'Second Outfit']), names)
        page.locator('#modlist tbody tr[data-id="Second Outfit"] td:nth-child(2)').click()
        page.wait_for_timeout(1200)

        # the image viewer
        sw = page.locator('#optlist img.sw16')
        if sw.count():
            sw.first.click()
        else:
            page.evaluate('() => window.e33.ui.viewImage("opt", 0, 0)')
        page.wait_for_timeout(300)
        check('clicking a swatch opens the image viewer', page.locator('#viewer-layer .viewer').is_visible())
        t0 = time.time()
        while time.time() - t0 < 60 and 'Reading the texture' in page.inner_text('#v-info'):
            page.wait_for_timeout(200)
        info = page.inner_text('#v-info')
        nat = page.evaluate('() => document.querySelector("#v-img").naturalWidth')
        check('  it shows the texture from the prepared pak, with its name, game path and size',
              '/Game/' in info and ' x ' in info and nat > 64 and "Can't show" not in info, (info, nat))
        shot(page, '4c_viewer')
        page.mouse.move(600, 380)
        page.mouse.wheel(0, -300)
        page.wait_for_timeout(100)
        zoom = page.inner_text('#v-zoom')
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)
        check('  the mouse wheel zooms; Esc closes it', zoom.endswith('%') and not page.locator('#viewer-layer').is_visible(),
              zoom)

        # both ticked: Reinstall selected (2)
        for mid in names:
            page.locator(f'#modlist tbody tr[data-id="{mid}"] input[data-chk]').click()
        page.wait_for_timeout(200)
        tb = page.inner_text('#tb-reinstall')
        check('ticking both: the toolbar offers "Reinstall selected (2)" and "Remove selected (2)..."',
              tb == 'Reinstall selected (2)' and page.inner_text('#tb-remove') == 'Remove selected (2)...', tb)
        shot(page, '7_bulk_ticked')
        before = len(api.poll()['jobs'])
        page.locator('#tb-reinstall').click()
        page.wait_for_timeout(500)
        api._jobs.wait(600)
        new = api.poll()['jobs'][before:]
        check('  Reinstall selected: one reinstall job per ticked mod, all done',
              sorted(j['mod_id'] for j in new) == names and all(j['kind'] == 'reinstall' and j['status'] == 'done' for j in new),
              new)

        # 1.3: disable / enable, Edit rows, Tools > Check & repair
        page.locator('#modlist tbody tr[data-id="Second Outfit"] td:nth-child(2)').click()
        for mid in names:                                   # untick both first
            page.locator(f'#modlist tbody tr[data-id="{mid}"] input[data-chk]').click()
        page.wait_for_timeout(300)
        page.locator('#tb-disable').click()
        t0 = time.time()
        while time.time() - t0 < 10 and api.mod_details('Second Outfit').get('state') != 'disabled':
            page.wait_for_timeout(200)
        page.wait_for_timeout(800)
        lua_dir = os.path.join(ue4ss, 'Mods', 'E33Wardrobe')
        menu = open(os.path.join(lua_dir, 'Scripts', 'variants.lua'), encoding='utf-8').read()
        check('Disable in the toolbar: the mod is disabled, out of the menu list, shown greyed with a banner',
              api.mod_details('Second Outfit')['state'] == 'disabled' and '"Second Outfit"' not in menu
              and 'dis' in (page.get_attribute('#modlist tbody tr[data-id="Second Outfit"]', 'class') or '')
              and 'Disabled: the game' in page.inner_text('#details-body') and page.inner_text('#tb-disable') == 'Enable',
              page.inner_text('#details-body')[:300])
        shot(page, '7b_disabled')
        page.locator('#tb-disable').click()
        t0 = time.time()
        while time.time() - t0 < 10 and api.mod_details('Second Outfit').get('state') != 'ready':
            page.wait_for_timeout(200)
        check('  Enable puts it back', api.mod_details('Second Outfit')['state'] == 'ready')
        page.wait_for_timeout(800)
        page.locator('#btn-edit-rows').click()
        page.wait_for_timeout(500)
        page.locator('#ed-tree .tn.row').first.click()
        page.locator('[data-ed="rename"]').click()
        page.fill('#ed-name', 'Test row')
        page.keyboard.press('Enter')
        page.wait_for_timeout(100)
        shot(page, '7c_edit_rows')
        page.locator('.dlg-buttons .btn', has_text='OK').click()
        page.wait_for_timeout(1000)
        menu = open(os.path.join(lua_dir, 'Scripts', 'variants.lua'), encoding='utf-8').read()
        check('Edit rows: a renamed row is saved in fixes.json and reaches variants.lua',
              '"Test row"' in menu and os.path.isfile(os.path.join(lua_dir, 'fixes.json'))
              and 'Test row' in page.inner_text('#details-body') and 'Fixes' in page.inner_text('#details-body'), menu[:400])
        page.locator('#tb-tools').click()
        page.locator('#ctxmenu .mi', has_text='Check & repair').click()
        t0 = time.time()
        while time.time() - t0 < 15 and 'Checked' not in (page.inner_text('#modal-layer') if page.locator('#modal-layer').is_visible() else ''):
            page.wait_for_timeout(200)
        txt = page.inner_text('#modal-layer')
        check('Tools > Check & repair: checks every mod and says what it found', 'Checked 2 mods' in txt and 'no problems' in txt, txt[:300])
        shot(page, '7d_check')
        page.keyboard.press('Escape')
        page.wait_for_timeout(200)

        # the game log: click a problem to see only its lines
        menu_dir = os.path.join(ue4ss, 'Mods', 'E33Wardrobe')
        now = dt.datetime.now()
        t = lambda s: (now + dt.timedelta(seconds=s)).strftime('%H:%M:%S')   # noqa: E731
        with open(os.path.join(menu_dir, 'live_log_previous.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(f'{t(-900)} #1 session start {now:%Y-%m-%d} {t(-900)}\n{t(-890)} #2 log: could not load /Game/Old/T_Older.T_Older\n')
        with open(os.path.join(menu_dir, 'live_log.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
            f.write(f'{t(-20)} #1 session start {now:%Y-%m-%d} {t(-20)}\n'
                    f'{t(-10)} #2 log: could not load /Game/Mods/Test/T_Missing.T_Missing\n'
                    f'{t(-9)} #3 pass (Test: Row = Long Coat): 1 change(s)\n'
                    f'{t(-9)} #4   on screen: Test: Row = Long Coat: 1/2 asset(s)\n')
        page.locator('.tab[data-tab="log"]').click()
        t0 = time.time()
        while time.time() - t0 < 15 and 'T_Missing' not in page.inner_text('#problemlist'):
            page.wait_for_timeout(300)
        page.locator('#problemlist tbody tr', has_text='T_Missing').click()
        page.wait_for_timeout(400)
        view = page.inner_text('#logview')
        bar = page.inner_text('#log-itemfilter') if page.locator('#log-itemfilter').is_visible() else ''
        check('clicking a problem shows only its log lines, and says so',
              'could not load /Game/Mods/Test/T_Missing' in view and 'session start' not in view
              and 'Showing lines for' in bar and 'T_Missing' in bar, (view, bar))
        shot(page, '5_gamelog_filter')
        page.keyboard.press('Escape')
        page.wait_for_timeout(300)
        check('  Esc shows every line again', 'session start' in page.inner_text('#logview')
              and not page.locator('#log-itemfilter').is_visible())
        page.locator('#onscreenlist tbody tr', has_text='Long Coat').click()
        page.wait_for_timeout(300)
        view = page.inner_text('#logview')
        check('clicking an on-screen row shows the lines about that row', 'on screen: Test: Row' in view
              and 'pass (Test: Row' in view and 'T_Missing' not in view, view)
        page.locator('[data-act="log-show-all"]').click()
        page.select_option('#log-source', 'previous')
        t0 = time.time()
        while time.time() - t0 < 10 and 'T_Older' not in page.inner_text('#problemlist'):
            page.wait_for_timeout(300)
        check('Show: Previous session reads live_log_previous.txt with the same rules',
              'T_Older' in page.inner_text('#problemlist') and 'Previous session' in page.inner_text('#log-status'),
              page.inner_text('#log-status'))
        page.select_option('#log-source', 'this')
        page.locator('.tab[data-tab="mods"]').click()
        page.wait_for_timeout(300)

        # Delete with ticked mods: one dialog listing them, with "also delete files"
        for mid in names:
            page.locator(f'#modlist tbody tr[data-id="{mid}"] input[data-chk]').click()
        page.wait_for_timeout(200)
        page.locator('#modlist').focus()
        page.keyboard.press('Delete')
        page.wait_for_timeout(500)
        shot(page, '6_remove_dialog')
        dlg = page.inner_text('#modal-layer') if page.locator('#modal-layer').is_visible() else ''
        check('Delete with two ticked mods asks once, naming both, with the delete-files box',
              'Remove these 2 mods' in dlg and all(n in dlg for n in names) and 'Also delete their files' in dlg, dlg)
        page.locator('.dlg button', has_text='Remove 2 mods').click()
        page.wait_for_timeout(500)
        api._jobs.wait(300)
        page.wait_for_timeout(1500)
        mods = api.list_mods()
        check('  removing takes both out of the game (the library copies stay)',
              len(mods) == 2 and all(m['state'] == 'not_installed' for m in mods), mods)
        check('  and unticks them', page.inner_text('#tb-reinstall') in ('Reinstall', 'Install'), page.inner_text('#tb-reinstall'))
        b.close()
    srv.shutdown()
    api.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


shots_taken = {}


def make_texture_option(base, retoc, out_dir, tmp):
    """An option folder (zen .utoc/.ucas) holding the first texture of the fixture's legacy files."""
    import subprocess
    import e33legacy as L
    tex = None
    for dp, _ds, fs in sorted(os.walk(os.path.join(base, 'Sandfall', 'Content'))):
        for f in sorted(fs):
            if f.endswith('.uasset') and tex is None:
                try:
                    if L.read_package_info(os.path.join(dp, f))['main_class'] == 'Texture2D':
                        tex = os.path.join(dp, f[:-7])
                except Exception:
                    pass
    leg = os.path.join(tmp, 'tex_legacy')
    rel = os.path.relpath(tex, base)
    os.makedirs(os.path.dirname(os.path.join(leg, rel)), exist_ok=True)
    for ext in ('.uasset', '.uexp', '.ubulk'):
        if os.path.isfile(tex + ext):
            shutil.copyfile(tex + ext, os.path.join(leg, rel) + ext)
    os.makedirs(out_dir, exist_ok=True)
    subprocess.run([retoc, 'to-zen', '--version', 'UE5_4', leg, os.path.join(out_dir, 'Opt_P.utoc')],
                   capture_output=True, check=True)

if __name__ == '__main__':
    sys.exit(main())
