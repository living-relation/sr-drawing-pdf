"""The local sheet page: sample sheet, BOM click, move, split, and a detail suggestion."""
import json
import os
import sys
import threading
import urllib.request

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, 'dev'))

from sheet2d.scene import render_svg  # noqa: E402
from sheet_demo import Demo, serve  # noqa: E402


def test_centerlines_and_hidden_lines_stay():
    svg = render_svg([
        ('pl', [(0, 0), (10, 0)], 'hid', False),
        ('pl', [(0, 2), (10, 2)], 'ctr', False),
    ], 20, 20)
    assert 'stroke-dasharray="3.000 1.500"' in svg
    assert 'stroke-dasharray="8.000 1.500 1.500 1.500"' in svg
    assert svg.count('<path') == 2
    assert 'display:none' not in svg and 'visibility="hidden"' not in svg


def test_sample_sheet_shows_block_rule_and_centerline():
    scene = Demo().scene()
    svg = scene['svg']
    assert '140.00' in svg and '140.05' not in svg
    assert '100.00' in svg and '100.00 \u00b10.05' not in svg
    assert '64.0 \u00b10.1' in svg
    assert 'stroke-dasharray="8.000 1.500 1.500 1.500"' in svg
    assert scene['status_bar']['indicator'] == {'symbol': '!', 'color': 'yellow'}
    assert scene['status_bar']['open'] == 2
    assert any(p['anchor'] == 'bottom_left' for p in scene['pieces'])
    assert any(p['anchor'] == 'above_title' for p in scene['pieces'])


def test_click_row_highlights_and_shows_thumbnail():
    demo = Demo()
    scene = demo.command('select_bom_row', {'key': 'p1'})
    sel = scene['selection']
    assert sel['thumbnail'].startswith('data:image/svg+xml')
    assert sel['pn'] == 'SR-S-101'
    ids = {h['element'] for h in sel['highlight']}
    assert 'v1' in ids and 'b1' in ids and 'v4' in ids
    assert 'data-highlight="v1"' in scene['svg']
    assert 'data-highlight="b1"' in scene['svg']
    assert 'data-highlight="p1"' in scene['svg']


def test_split_and_drag_a_bom_piece():
    demo = Demo()
    scene = demo.command('split_table', {'row': 'p3', 'where': 'below'})
    assert len(scene['pieces']) == 3
    new = next(p for p in scene['pieces'] if p['rows'][0]['key'] == 'p4')
    # Under the rev table, right of the top view, above the section view.
    assert new['x0'] > 220 and new['x1'] <= 422
    assert 200 < new['y0'] and new['y1'] < 248
    moved = demo.command('move_bom', {'id': new['id'], 'x1': 260, 'ytop': 150})
    piece = next(p for p in moved['pieces'] if p['id'] == new['id'])
    assert abs(piece['x1_edge'] - 260) < 0.1
    assert abs(piece['ytop'] - 150) < 0.1


def test_accept_suggestion_adds_a_detail_and_clears_one_bang():
    demo = Demo()
    scene = demo.scene()
    sid = scene['suggestions'][0]['id']
    scene = demo.command('accept_suggestion', {'id': sid})
    assert scene['status_bar']['open'] == 1
    assert scene['status_bar']['indicator']['symbol'] == '!'
    assert 'DETAIL' in scene['svg']
    scene = demo.command('dismiss_suggestion', {'id': scene['suggestions'][0]['id']})
    assert scene['status_bar'] == {'indicator': None, 'open': 0, 'items': []}


def test_page_serves_the_editor():
    demo = Demo()
    httpd = serve(port=0, demo=demo)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        base = 'http://127.0.0.1:%d' % port
        html = urllib.request.urlopen(base + '/').read().decode('utf-8')
        assert 'Split below' in html and 'id="bang"' in html
        scene = json.loads(urllib.request.urlopen(base + '/api/scene').read().decode('utf-8'))
        assert '140.00' in scene['svg']
        font = urllib.request.urlopen(base + '/font/DejaVuSans.ttf')
        assert font.status == 200 and font.read(4) == b'\x00\x01\x00\x00'
    finally:
        httpd.shutdown()
