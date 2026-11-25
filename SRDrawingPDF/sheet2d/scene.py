"""What the local sheet editor draws.

Coordinates in the scene boxes are millimetres, origin at the bottom left,
the same as the sheet. The SVG uses the same numbers with y flipped so the
page is right side up in a browser.

Every primitive is drawn. Centerlines and hidden lines are not dropped and
are not turned into something else.
"""
import math

from .canvas import BALLOON_R, STY, bom_header_height, bom_row_cells, bom_row_height
from .commands import execute
from .font import text_width_mm
from .model import DrawingDocument, _bom_colw, _bom_text_h, bom_regions, layout_bom, size_of
from .render import dimension_text, render_sheets
from .suggest import status_bar
from .annotate import hole_callout_lines

# A highlight drawn over the sheet. It does not replace any line.
MARK = '#c98400'


def build_scene(document, sheet_id=None, selected_key=None):
    """JSON for one sheet: the SVG, BOM hit boxes, the selection, and suggestions."""
    doc = document if isinstance(document, DrawingDocument) else DrawingDocument.from_dict(document)
    if not doc.sheets:
        raise ValueError('the drawing has no sheets')
    sheet = _sheet(doc, sheet_id)
    spec = size_of(doc, sheet.get('size') or 'B')
    width, height = float(spec['width']), float(spec['height'])
    rendered = render_sheets(doc)
    canvas = rendered[doc.sheets.index(sheet)]
    pieces = piece_geometry(doc, sheet.get('id'))
    selection = _selection(doc, selected_key)
    marks = _marks(selection, sheet.get('id'))
    marks['boxes'] = _mark_boxes(sheet, marks)
    svg = render_svg(canvas.items, width, height, pieces, marks)
    dims, callouts = _readouts(doc, sheet)
    return {
        'sheet': {'id': sheet.get('id'), 'name': sheet.get('name') or '', 'width': width, 'height': height},
        'sheets': [{'id': s.get('id'), 'name': s.get('name') or ''} for s in doc.sheets],
        'svg': svg,
        'pieces': pieces,
        'bom': [_bom_row(r, pieces) for r in doc.bom],
        'selection': selection,
        'status_bar': status_bar(doc.suggestions),
        'suggestions': [dict(s) for s in doc.suggestions if s.get('status', 'open') == 'open'],
        'dimensions': dims,
        'callouts': callouts,
    }


def piece_geometry(doc, sheet_id):
    """BOM pieces on one sheet, with a box for the header and for each row."""
    if isinstance(doc, dict):
        doc = DrawingDocument.from_dict(doc)
    layout = layout_bom(doc)
    regions = {el.get('id'): el for _s, el in bom_regions(doc)}
    first = None
    for el in regions.values():
        first = el
        break
    rows = {r.get('key'): r for r in doc.bom}
    out = []
    for seg in layout['segments']:
        if seg.get('sheet') != sheet_id or not seg.get('rows'):
            continue
        el = regions.get(seg.get('id')) or {}
        continued = bool(seg.get('continued'))
        h = _bom_text_h(el, first, continued)
        colw = _bom_colw(el, first, continued)
        x1 = float(seg['x1'])
        top = float(seg['ytop'])
        x0 = x1 - sum(colw)
        header = bom_header_height(h, continued)
        boxes = []
        y = top - header
        for key in seg['rows']:
            row = rows.get(key) or {}
            hh, _wrapped = bom_row_height(bom_row_cells(row), colw, h)
            boxes.append({
                'key': key,
                'item': row.get('item'),
                'pn': row.get('pn') or '',
                'desc': row.get('desc') or '',
                'x0': x0, 'y0': y - hh, 'x1': x1, 'y1': y,
            })
            y -= hh
        out.append({
            'id': seg.get('id'),
            'sheet': seg.get('sheet'),
            'anchor': seg.get('anchor'),
            'x0': x0, 'y0': float(seg['bottom']), 'x1': x1, 'y1': top,
            'x1_edge': x1, 'ytop': top,
            'header': {'x0': x0, 'y0': top - header, 'x1': x1, 'y1': top},
            'rows': boxes,
        })
    return out


def render_svg(items, width, height, pieces=None, marks=None):
    """SVG text for one sheet. `items` are the canvas primitives, unchanged."""
    pieces = pieces or []
    marks = marks or {}
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %.3f %.3f" preserveAspectRatio="xMidYMid meet">'
        % (width, height),
        '<rect width="%.3f" height="%.3f" fill="#ffffff"/>' % (width, height),
    ]
    for it in items:
        if it[0] == 'wm':
            parts.append(_wm(it, height))
    for box in _under_marks(pieces, marks):
        parts.append(_box(box, height, 'fill="%s" fill-opacity="0.35" stroke="none"' % MARK))
    run_sty, run_d = None, []
    for it in items:
        if it[0] == 'wm':
            continue
        if it[0] == 'pl' and len(it[1]) >= 2:
            # Lines in a row with one style share one path: a real view is tens of thousands of lines.
            if it[2] != run_sty and run_d:
                parts.append(_path(''.join(run_d), height, run_sty))
                run_d = []
            run_sty = it[2]
            run_d.append(_d(it[1], height, it[3]))
            continue
        if run_d:
            parts.append(_path(''.join(run_d), height, run_sty))
            run_d = []
        parts.append(_item(it, height))
    if run_d:
        parts.append(_path(''.join(run_d), height, run_sty))
    for box in _over_marks(pieces, marks):
        parts.append(box if isinstance(box, str) else _box(
            box, height, 'fill="none" stroke="%s" stroke-width="1.1" data-highlight="%s"' % (MARK, _esc(box.get('id') or ''))))
    for piece in pieces:
        head = piece['header']
        parts.append(_hit(head, height, {
            'data-drag': piece['id'],
            'data-x1': '%.4f' % piece['x1_edge'],
            'data-ytop': '%.4f' % piece['ytop'],
        }))
        for row in piece['rows']:
            parts.append(_hit(row, height, {'data-key': row['key'], 'data-piece': piece['id']}))
    parts.append('</svg>')
    return ''.join(parts)


def _sheet(doc, sheet_id):
    if sheet_id is None:
        return doc.sheets[0]
    for sheet in doc.sheets:
        if sheet.get('id') == sheet_id:
            return sheet
    raise ValueError('no sheet %r' % sheet_id)


def _selection(doc, key):
    if not key:
        return None
    try:
        return execute(doc.to_dict(), 'select_bom_row', {'key': key})['result']
    except ValueError:
        return None


def _marks(selection, sheet_id):
    if not selection:
        return {'views': set(), 'balloons': set(), 'row': None}
    views, balloons = set(), set()
    for hit in selection.get('highlight') or []:
        if hit.get('sheet') != sheet_id:
            continue
        if hit.get('type') == 'view':
            views.add(hit.get('element'))
        elif hit.get('type') == 'balloon':
            balloons.add(hit.get('element'))
    return {'views': views, 'balloons': balloons, 'row': selection.get('key')}


def _bom_row(row, pieces):
    on_sheet = False
    for piece in pieces:
        if any(r['key'] == row.get('key') for r in piece['rows']):
            on_sheet = True
    return {
        'key': row.get('key'),
        'item': row.get('item'),
        'pn': row.get('pn') or '',
        'desc': row.get('desc') or '',
        'mat': row.get('mat') or '',
        'on_sheet': on_sheet,
    }


def _readouts(doc, sheet):
    dims, callouts = [], []
    for el in sheet.get('elements') or []:
        if el.get('type') == 'dim':
            dims.append({'id': el.get('id'), 'text': dimension_text(doc, sheet, el)})
        elif el.get('type') == 'hole':
            callouts.append({
                'id': el.get('id'),
                'text': '\n'.join(hole_callout_lines(el, doc.hole_tol, doc.properties)),
            })
    return dims, callouts


def _under_marks(pieces, marks):
    key = marks.get('row')
    if not key:
        return []
    boxes = []
    for piece in pieces:
        for row in piece['rows']:
            if row['key'] == key:
                boxes.append(dict(row, id=key))
    return boxes


def _mark_boxes(sheet, marks):
    """Stroke boxes for highlighted views and balloons. The geometry under them stays."""
    boxes = []
    for el in sheet.get('elements') or []:
        if el.get('type') == 'view' and el.get('id') in marks['views']:
            pad = 1.2
            boxes.append({
                'id': el.get('id'),
                'x0': float(el['x']) - pad,
                'y0': float(el['y']) - pad,
                'x1': float(el['x']) + float(el['w']) + pad,
                'y1': float(el['y']) + float(el['h']) + pad,
            })
        elif el.get('type') == 'balloon' and el.get('id') in marks['balloons']:
            r = BALLOON_R + 1.6
            boxes.append({
                'id': el.get('id'),
                'x0': float(el['x']) - r,
                'y0': float(el['y']) - r,
                'x1': float(el['x']) + r,
                'y1': float(el['y']) + r,
            })
    return boxes


def _over_marks(pieces, marks):
    """Strokes only. The sheet lines underneath stay."""
    out = list(marks.get('boxes') or [])
    key = marks.get('row')
    for piece in pieces:
        for row in piece['rows']:
            if row['key'] == key:
                out.append(dict(row, id=key))
    return out


def _item(it, height):
    kind = it[0]
    if kind == 'pl':
        _k, pts, sty, closed = it
        return _poly(pts, height, sty, closed)
    if kind == 'tri':
        return _poly(it[1], height, None, True, fill='#111111')
    if kind == 'tx':
        return _text(it, height)
    return ''


def _poly(pts, height, sty, closed, fill='none'):
    if len(pts) < 2:
        return ''
    return _path(_d(pts, height, closed), height, sty, fill)


def _d(pts, height, closed):
    d = ['M %.3f %.3f' % (pts[0][0], height - pts[0][1])]
    for x, y in pts[1:]:
        d.append(' L %.3f %.3f' % (x, height - y))
    if closed:
        d.append(' Z')
    return ''.join(d) + ' '


def _path(d, height, sty, fill='none'):
    if sty is None:
        width, dash = 0.2, None
        cap = 'round'
    else:
        width, dash = STY.get(sty, STY['thin'])
        cap = 'butt' if sty == 'dim' else 'round'
    d = d.rstrip()
    dash_attr = ''
    if dash:
        dash_attr = ' stroke-dasharray="%s"' % ' '.join('%.3f' % n for n in dash)
    stroke = 'none' if fill != 'none' else '#111111'
    return '<path d="%s" fill="%s" stroke="%s" stroke-width="%.3f" stroke-linecap="%s" stroke-linejoin="round"%s/>' % (
        d, fill, stroke, width, cap, dash_attr)


def _text(it, height):
    _k, x, y, text, h, ha, va, rot, bold, _bg, _layer = it
    lines = str(text).split('\n')
    pitch = h * 1.6
    n = len(lines)
    if va == 'top':
        base0 = y - h
    elif va == 'bottom':
        base0 = y + pitch * (n - 1)
    else:
        base0 = y + pitch * (n - 1) / 2.0 - h / 2.0
    ang = math.radians(rot or 0)
    c, s = math.cos(ang), math.sin(ang)
    weight = '700' if bold else '400'
    size = float(h) / 0.72
    chunks = []
    for i, line in enumerate(lines):
        if line == '':
            continue
        tw = text_width_mm(line, h, bold)
        if ha == 'left':
            ox = 0.0
        elif ha == 'right':
            ox = -tw
        else:
            ox = -tw / 2.0
        oy = base0 - y - i * pitch
        lx = x + c * ox - s * oy
        ly = y + s * ox + c * oy
        sx, sy = lx, height - ly
        turn = ''
        if rot:
            turn = ' transform="rotate(%.3f %.3f %.3f)"' % (-(rot or 0), sx, sy)
        chunks.append(
            '<text x="%.3f" y="%.3f" font-family="DejaVu Sans" font-size="%.3f" font-weight="%s" '
            'fill="#111111" text-anchor="start" dominant-baseline="alphabetic"%s>%s</text>'
            % (sx, sy, size, weight, turn, _esc(line)))
    return ''.join(chunks)


def _wm(it, height):
    _k, x, y, text, h, ang = it
    sx, sy = x, height - y
    size = float(h) / 0.72
    return (
        '<text x="%.3f" y="%.3f" font-family="DejaVu Sans" font-size="%.3f" font-weight="700" '
        'fill="#e4e4e4" text-anchor="middle" dominant-baseline="central" '
        'transform="rotate(%.3f %.3f %.3f)" pointer-events="none">%s</text>'
        % (sx, sy, size, -(ang or 0), sx, sy, _esc(text)))


def _box(box, height, attrs):
    x = box['x0']
    y = height - box['y1']
    w = box['x1'] - box['x0']
    h = box['y1'] - box['y0']
    return '<rect x="%.3f" y="%.3f" width="%.3f" height="%.3f" %s/>' % (x, y, w, h, attrs)


def _hit(box, height, data):
    attrs = ' '.join('%s="%s"' % (k, _esc(v)) for k, v in data.items())
    return _box(box, height, 'fill="#000000" fill-opacity="0" stroke="none" %s' % attrs)


def _esc(text):
    return (str(text)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))

