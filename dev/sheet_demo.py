"""Local sheet editor. No Fusion.

From the repo folder:

  python dev/sheet_demo.py

Then open http://127.0.0.1:8765/

Real views instead of the sample (four views on a B sheet at one scale):

  python dev/sheet_demo.py --fusion DUMP_FOLDER   (written by fusion_read.py)
  python dev/sheet_demo.py --step FILE.step       (needs OCP)
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ADDIN = os.path.join(_ROOT, 'SRDrawingPDF')
if _ADDIN not in sys.path:
    sys.path.insert(0, _ADDIN)

from sheet2d.commands import execute  # noqa: E402
from sheet2d.model import DrawingDocument, layout_bom  # noqa: E402
from sheet2d.sample import build_sample  # noqa: E402
from sheet2d.scene import build_scene  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
_HTML = os.path.join(_HERE, 'editor.html')
_FONTS = os.path.join(_ADDIN, 'sheet2d', 'fonts')
# First accepted detail sits just above the section view. The next uses the
# same band, to the left, only if that spot is still open.
# Leave room under the frame for the DETAIL caption, above the section view.
_SLOTS = ((312.0, 176.0, 78.0, 32.0), (220.0, 176.0, 78.0, 32.0))
# A new split piece hangs under the rev table and to the right of the top
# view. It is 182 mm wide, so the right edge is 412 (sheet is 431.8).
_SPLIT = {'anchor': 'free', 'x1': 412.0, 'ytop': 245.0, 'max_height': 60.0}


class Demo(object):
    """One sample drawing and the editor actions the page can call."""

    def __init__(self, build=None):
        self._build = build or build_sample
        self.doc = self._build()
        self.sheet_id = 's1'
        self.selected = None

    def scene(self):
        return build_scene(self.doc, self.sheet_id, self.selected)

    def command(self, name, args=None):
        args = dict(args or {})
        if name == 'reset':
            self.doc = self._build()
            self.sheet_id = 's1'
            self.selected = None
            return self.scene()
        if name == 'set_sheet':
            self.sheet_id = args.get('sheet') or self.sheet_id
            return self.scene()
        if name == 'select_bom_row':
            self.selected = args.get('key')
            scene = self.scene()
            if self.selected and scene.get('selection') is None:
                self.selected = None
                raise ValueError('no BOM row %r' % args.get('key'))
            return scene
        if name == 'move_bom':
            args = self._with_height(args)
        elif name == 'split_table':
            for key, value in _SPLIT.items():
                args.setdefault(key, value)
            if 'row' not in args and self.selected:
                args['row'] = self.selected
        elif name == 'accept_suggestion':
            x, y, w, h = self._slot()
            args.setdefault('sheet', self.sheet_id)
            args.setdefault('x', x)
            args.setdefault('y', y)
            args.setdefault('w', w)
            args.setdefault('h', h)
        elif name != 'dismiss_suggestion':
            raise ValueError('unknown command %r' % name)
        out = execute(self.doc, name, args)
        self.doc = out['document']
        scene = self.scene()
        scene['result'] = out['result']
        return scene

    def _with_height(self, args):
        if args.get('max_height'):
            return args
        layout = layout_bom(DrawingDocument.from_dict(self.doc))
        seg = next((s for s in layout['segments'] if s.get('id') == args.get('id')), None)
        if seg is None:
            return args
        height = float(seg['ytop']) - float(seg['bottom'])
        if height > 0:
            args['max_height'] = round(height, 3)
        return args

    def _slot(self):
        n = 0
        for sheet in self.doc['sheets']:
            for el in sheet.get('elements') or []:
                if el.get('type') == 'view' and el.get('kind') == 'detail':
                    n += 1
        return _SLOTS[min(n, len(_SLOTS) - 1)]


def make_handler(demo):
    html = open(_HTML, encoding='utf-8').read()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def do_GET(self):
            path = urlparse(self.path).path
            if path in ('/', '/index.html'):
                self._send(200, 'text/html; charset=utf-8', html.encode('utf-8'))
                return
            if path == '/api/scene':
                self._send(200, 'application/json', _dump(demo.scene()))
                return
            if path.startswith('/font/'):
                name = os.path.basename(path)
                font = os.path.join(_FONTS, name)
                if os.path.isfile(font) and name.endswith('.ttf'):
                    self._send(200, 'font/ttf', open(font, 'rb').read())
                    return
            self.send_error(404)

        def do_POST(self):
            if urlparse(self.path).path != '/api/command':
                self.send_error(404)
                return
            n = int(self.headers.get('Content-Length') or 0)
            try:
                body = json.loads(self.rfile.read(n).decode('utf-8') or '{}')
            except ValueError:
                self._send(400, 'application/json', _dump({'error': 'bad json'}))
                return
            try:
                scene = demo.command(body.get('command'), body.get('args') or {})
            except ValueError as exc:
                self._send(400, 'application/json', _dump({'error': str(exc)}))
                return
            self._send(200, 'application/json', _dump(scene))

        def _send(self, code, ctype, data):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    return Handler


def _dump(obj):
    return json.dumps(obj).encode('utf-8')


def serve(host='127.0.0.1', port=8765, demo=None):
    demo = demo or Demo()
    httpd = ThreadingHTTPServer((host, port), make_handler(demo))
    return httpd


def real_views(fusion=None, step=None, title=None):
    """A document builder for the editor: the four views of a real assembly."""
    from sheet2d.viewsheet import build_view_sheet
    if fusion:
        from sheet2d.meshparts import load_fusion_dump
        parts, info = load_fusion_dump(fusion)
        name = title or info['document'] or os.path.basename(os.path.normpath(fusion))
        source = 'Fusion'
    else:
        from step_mesh import load_step
        parts, _info = load_step(step)
        name = title or os.path.splitext(os.path.basename(step))[0]
        source = 'STEP'
    doc, report = build_view_sheet(parts, name, source=source)
    print('Views at %s in %.1f s' % (report['scale'], report['seconds']))
    return lambda: json.loads(json.dumps(doc))


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description='Local sheet editor')
    ap.add_argument('port', nargs='?', type=int, default=8765)
    ap.add_argument('--fusion', help='folder written by fusion_read.py')
    ap.add_argument('--step', help='STEP file (needs OCP)')
    ap.add_argument('--title')
    args = ap.parse_args(argv[1:])
    port = args.port
    demo = None
    if args.fusion or args.step:
        demo = Demo(real_views(args.fusion, args.step, args.title))
    httpd = serve(port=port, demo=demo)
    print('Sheet editor: http://127.0.0.1:%d/' % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
