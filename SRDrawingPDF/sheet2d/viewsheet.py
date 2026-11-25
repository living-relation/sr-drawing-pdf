"""Put an assembly's front, top, right and trimetric views on a size B sheet.

One sheet scale for the standard views: the largest standard scale that fits
with room for dimensions (sr-drawing-pack ADR-035). Third-angle projection:
top above front, right to the right, aligned. The trimetric goes in the space
above the right view and below the rev table; when it only fits smaller it gets
its own standard scale, and the caption then prints that scale (ADR-026).

View lines are kept here, outside the drawing JSON, under the view's `geom`
key. render.py draws them when the key is known, otherwise the empty frame.
"""
import gc
import math
import time

from .canvas import PH, PW, VIEW_CAPTION_H, VIEW_SUB_H, revlog_rect
from .model import DrawingDocument
from .project import project_view, view_extent

# Largest first. handbuilt-cad dwg.STD_SCALES, plus 1:20 and 1:50 (ISO 5455) for machines.
STD_SCALES = (
    (10.0, '10:1'), (8.0, '8:1'), (5.0, '5:1'), (4.0, '4:1'), (3.0, '3:1'), (2.0, '2:1'),
    (1.5, '1.5:1'), (1.0, '1:1'), (2.0 / 3.0, '1:1.5'), (0.5, '1:2'), (0.4, '1:2.5'),
    (1.0 / 3.0, '1:3'), (0.25, '1:4'), (0.2, '1:5'), (0.1, '1:10'), (0.05, '1:20'), (0.02, '1:50'),
)
# Space for the views on size B: inside the border, above the title and tolerance blocks.
REGION = (16.0, 67.0, PW - 16.0, PH - 16.0)
GAP = 16.0           # between views, room for dimensions
CAPTION_ROOM = 9.0   # under a view that prints a caption
PX_PER_MM = 4.0      # depth-buffer pixels per printed millimetre
MAX_BUF = 1800
STYLE = {'vis': 'vis', 'thin': 'thin', 'ctr': 'ctr'}

_GEOM = {}


def register_view_geometry(key, view):
    """Keep a view's lines (model units) for render.py. Returns key."""
    _GEOM[key] = {'lines': view['lines'], 'extent': view['extent'], 'name': view.get('name')}
    return key


def view_geometry(key):
    return _GEOM.get(key) if key else None


def clear_view_geometry(prefix=''):
    for key in [k for k in _GEOM if k.startswith(prefix)]:
        del _GEOM[key]


def draw_view_lines(sh, el, geom, scale, caption=None):
    """The view's visible lines, centred in its frame at `scale`, then its caption."""
    x, y, w, h = float(el['x']), float(el['y']), float(el['w']), float(el['h'])
    u0, u1, v0, v1 = geom['extent']
    s = float(scale or 1.0)
    cx, cy = x + w / 2.0, y + h / 2.0
    uc, vc = (u0 + u1) / 2.0, (v0 + v1) / 2.0
    for line in geom['lines']:
        sty = STYLE.get(line['style'], 'thin')
        if line['kind'] == 'circle':
            c = line['c']
            r = line['r'] * s
            sh.circle((cx + (c[0] - uc) * s, cy + (c[1] - vc) * s), r, sty, n=max(12, min(72, int(r * 4))))
            continue
        sh.pl([(cx + (p[0] - uc) * s, cy + (p[1] - vc) * s) for p in line['pts']], sty)
    yy = y - 2.0
    for i, text in enumerate(caption or []):
        hh = VIEW_CAPTION_H if i == 0 and not text.startswith('SCALE ') else VIEW_SUB_H
        sh.txt(x + w / 2, yy, text, h=hh, bold=(hh == VIEW_CAPTION_H), va='top')
        yy -= hh * 1.6


def _size(ext):
    return ext[1] - ext[0], ext[3] - ext[2]


def layout(extents, rev_rect, region=REGION, gap=GAP):
    """Frames and scales. extents: name -> (u0, u1, v0, v1). Returns dict or raises."""
    L, B, R, T = region
    xf, zf = _size(extents['front'])
    _xt, yt = _size(extents['top'])
    yr, _zr = _size(extents['right'])
    rx0, ry0 = rev_rect[0] - 3.0, rev_rect[1] - 3.0
    for s, label in STD_SCALES:
        wf, hf, ht, wr = xf * s, zf * s, yt * s, yr * s
        bw, bh = wf + gap + wr, hf + gap + ht
        if bw > R - L or bh > T - B:
            continue
        x0 = L
        top_hits_rev = x0 + wf > rx0
        t_eff = ry0 if top_hits_rev else T
        if bh > t_eff - B:
            continue
        y0 = B + max(0.0, (t_eff - B - bh) / 2.0)
        frames = {
            'front': (x0, y0, wf, hf),
            'top': (x0, y0 + hf + gap, wf, ht),
            'right': (x0 + wf + gap, y0, wr, hf),
        }
        out = {'scale': s, 'label': label, 'frames': frames}
        # Trimetric: right of the top view, above the right view, under the rev table.
        tx0 = x0 + wf + gap
        ty0 = y0 + hf + gap
        ty1 = ry0 if tx0 < rev_rect[2] and R > rx0 else T
        bw2, bh2 = R - tx0, ty1 - ty0
        tw, th = _size(extents['trimetric'])
        for s2, label2 in STD_SCALES:
            if s2 > s + 1e-12:
                continue
            room = 0.0 if abs(s2 - s) < 1e-12 else CAPTION_ROOM
            if tw * s2 <= bw2 and th * s2 + room <= bh2:
                out['trimetric'] = {
                    'scale': s2, 'label': label2,
                    'frame': (tx0 + (bw2 - tw * s2) / 2.0, ty0 + room + (bh2 - room - th * s2) / 2.0, tw * s2, th * s2),
                }
                break
        return out
    raise ValueError('the views do not fit on one size B sheet at any standard scale')


def build_view_sheet(parts, title, key='asm', source='', date='', draft=1, px_per_mm=PX_PER_MM):
    """(drawing dict, report). Four views of `parts` on one size B sheet."""
    from .commands import execute
    t0 = time.perf_counter()
    names = ('front', 'top', 'right', 'trimetric')
    extents = {n: view_extent(parts, n) for n in names}
    doc = None

    def run(command, **args):
        nonlocal doc
        out = execute(doc, command, args)
        doc = out['document']
        return out['result']

    run('add_sheet', id='s1', name='Sheet 1')
    for field, value in (('title', title), ('material', 'SEE BOM'), ('units', 'mm'),
                         ('source', source), ('date', date)):
        if value:
            run('set_title', field=field, value=value)
    if draft:
        run('set_draft', n=draft)
    rev = revlog_rect(DrawingDocument.from_dict(doc).revlog)
    plan = layout(extents, rev)
    run('set_title', field='scale', value=plan['label'])
    report = {'scale': plan['label'], 'views': []}
    was = gc.isenabled()
    gc.disable()
    try:
        for n in names:
            if n == 'trimetric':
                if 'trimetric' not in plan:
                    continue
                frame, s, label = plan['trimetric']['frame'], plan['trimetric']['scale'], plan['trimetric']['label']
            else:
                frame, s, label = plan['frames'][n], plan['scale'], plan['label']
            bw = int(min(MAX_BUF, max(240, math.ceil(frame[2] * px_per_mm))))
            bh = int(min(MAX_BUF, max(180, math.ceil(frame[3] * px_per_mm))))
            t = time.perf_counter()
            view = project_view(parts, n, buf_w=bw, buf_h=bh)
            dt = time.perf_counter() - t
            gkey = register_view_geometry('%s:%s' % (key, n), view)
            args = dict(id='v_' + n, sheet='s1', x=frame[0], y=frame[1], w=frame[2], h=frame[3],
                        label=n.upper(), geom=gkey)
            if label != plan['label']:
                args['scale'] = label
            run('place_view', **args)
            report['views'].append({'name': n, 'seconds': dt, 'buffer': (bw, bh), 'lines': len(view['lines']),
                                    'scale': label})
    finally:
        if was:
            gc.enable()
    report['seconds'] = time.perf_counter() - t0
    return doc, report
