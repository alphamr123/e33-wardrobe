"""E33 Wardrobe app: a window around app/ui (pywebview), or a small HTTP bridge for testing.

  E33 Wardrobe.exe                  the app (frozen with PyInstaller, see app/e33wardrobe.spec)
  python app/e33app.py              the same from the repository (needs: pip install pywebview py7zr)
  python app/e33app.py --dev 8765   serves app/ui and the API at http://127.0.0.1:8765 for a browser
                                    or Playwright (tests); no window, no file dialogs
"""
import argparse
import json
import os
import sys
import threading

FROZEN = getattr(sys, 'frozen', False)
ROOT = getattr(sys, '_MEIPASS', '') if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in (ROOT, os.path.join(ROOT, 'tools')):
    if p not in sys.path:
        sys.path.insert(0, p)
UI_DIR = os.path.join(ROOT, 'app', 'ui')

# The methods of API.md: the only ones the page can call.
METHODS = ['get_state', 'set_game_folder', 'pick_game_folder', 'detect_game', 'pick_files', 'pick_folder',
           'add_paths', 'poll', 'list_mods', 'mod_details', 'reinstall_mod', 'remove_mod', 'install_menu',
           'open_path', 'open_url', 'monitor', 'problems_text', 'get_settings', 'save_settings',
           'clear_jobs', 'pick_library_folder', 'reinstall_mods', 'remove_mods', 'texture_preview', 'monitor_file']


def js_api(api):
    """A class with exactly the API methods, forwarding to `api`. pywebview exposes every public
    attribute of the object it gets, recursively; this keeps the window and dialogs out of reach."""
    def forward(name):
        def method(self, *args):
            return getattr(api, name)(*args)
        method.__name__ = name
        return method
    return type('E33Api', (), {m: forward(m) for m in METHODS})()


class Dialogs:
    def __init__(self, window):
        self._window = window

    def folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        return r[0] if r else None

    def files(self):
        import webview
        r = self._window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=True,
                                            file_types=('Mod archives (*.zip;*.7z;*.rar)', 'All files (*.*)'))
        return list(r or [])


def run_window(api, debug=False):
    import webview
    from webview.dom import DOMEventHandler
    from app.backend.paths import app_version
    window = webview.create_window(f'E33 Wardrobe {app_version()}', url=os.path.join(UI_DIR, 'index.html'),
                                   js_api=js_api(api), width=1200, height=780, min_size=(980, 620),
                                   background_color='#2d2d30', text_select=True)
    api.dialogs = Dialogs(window)

    def on_drop(event):
        files = (event.get('dataTransfer') or {}).get('files') or []
        paths = [f.get('pywebviewFullPath') for f in files if f.get('pywebviewFullPath')]
        if paths:
            api.add_paths(paths)

    def on_loaded():
        window.dom.document.events.dragover += DOMEventHandler(lambda e: None, True, True)
        window.dom.document.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    window.events.closed += lambda: api.shutdown()
    webview.start(debug=debug, gui='edgechromium' if sys.platform == 'win32' else None)


def run_dev(api, port):
    """API over HTTP for tests: POST /api/<method> with a JSON list of arguments."""
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=UI_DIR, **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            name = self.path.split('?')[0].rsplit('/', 1)[-1]
            if not self.path.startswith('/api/') or name not in METHODS:
                self.send_error(404)
                return
            try:
                n = int(self.headers.get('Content-Length') or 0)
                args = json.loads(self.rfile.read(n) or b'[]')
                result = getattr(api, name)(*args)
                body = json.dumps(result).encode('utf-8')
                self.send_response(200)
            except Exception as e:      # the real app never raises to the page either
                body = json.dumps({'ok': False, 'error': f'{type(e).__name__}: {e}'}).encode('utf-8')
                self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'http://127.0.0.1:{srv.server_address[1]}/index.html', flush=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main(argv=None):
    ap = argparse.ArgumentParser(description='E33 Wardrobe app')
    ap.add_argument('--dev', type=int, metavar='PORT', help='serve the UI and API over HTTP instead of a window')
    ap.add_argument('--debug', action='store_true', help='window with developer tools')
    a = ap.parse_args(argv)
    from app.backend.api import Api
    api = Api()
    if a.dev is not None:
        srv = run_dev(api, a.dev)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            srv.shutdown()
        return 0
    run_window(api, a.debug)
    return 0


if __name__ == '__main__':
    sys.exit(main())
