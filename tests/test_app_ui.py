"""The app end to end: the real UI (app/ui) and backend (app/backend) through the dev HTTP bridge,
driven in Chromium with Playwright, against a fake game. Writes screenshots when E33_SHOTS is set.

Needs: playwright (+ a Chromium: E33_CHROME or Playwright's own), and the fixtures of
test_relocate_e2e.py: E33_E2E_PAKS, E33_RETOC; plus E33_SAMPLE_ARCHIVES: a folder with a few mod
archives (.zip/.7z) of one Nexus mod. Skips (exit 0 with a SKIP line) when something is missing.
"""
import glob
import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path[:0] = [ROOT, os.path.join(ROOT, 'tools')]


def main():
    need = [os.environ.get(k) for k in ('E33_E2E_PAKS', 'E33_RETOC', 'E33_SAMPLE_ARCHIVES')]
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('SKIP: playwright not installed')
        return 0
    if not all(need):
        print('SKIP: set E33_E2E_PAKS, E33_RETOC and E33_SAMPLE_ARCHIVES')
        return 0
    paks_src, retoc, samples = need
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
    shutil.copytree(paks_src, paks, copy_function=os.link)
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

        page.locator('.tab[data-tab="log"]').click()
        page.wait_for_timeout(1500)
        shot(page, '5_gamelog')
        page.locator('.tab[data-tab="mods"]').click()
        page.wait_for_timeout(500)
        page.keyboard.press('Delete')
        page.wait_for_timeout(500)
        shot(page, '6_remove_dialog')
        dlg = page.inner_text('body')
        check('Delete asks before removing', 'Remove' in dlg, dlg[-400:])
        page.locator('.dlg button', has_text='Remove').last.click()
        t0 = time.time()
        while time.time() - t0 < 60 and (api.poll()['busy'] or (api.list_mods() and api.list_mods()[0]['state'] in ('ready', 'working'))):
            page.wait_for_timeout(300)
        mods = api.list_mods()
        check('  removing takes it out of the game (the library copy stays)', mods and mods[0]['state'] == 'not_installed',
              mods)
        b.close()
    srv.shutdown()
    api.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
    print(f'\n{fails} failure(s)')
    return 1 if fails else 0


shots_taken = {}

if __name__ == '__main__':
    sys.exit(main())
