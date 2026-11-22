"""Turn a drawing document into sheet primitives and a PDF."""
from .annotate import dim_measure, dim_text, hole_callout_lines, scale_value, view_caption
from .detail import draw_detail_mark, draw_detail_outline
from .canvas import (
    Sheet, draw_balloon, draw_bom, draw_dimension, draw_frame, draw_hole_callout, draw_note_flag, draw_notes,
    draw_view_box,
)
from .model import (
    _bom_colw, _bom_text_h, find_element, item_of, layout_bom, note_number, notes_with_auto, resolved_title,
    resolved_view, sheet_scale, size_of,
)
from .pdf import write_pdf


def render_sheets(doc):
    """One canvas.Sheet per document sheet, in order."""
    if not doc.sheets:
        raise ValueError('the drawing has no sheets')
    layout = layout_bom(doc)
    by_region = {seg['id']: seg for seg in layout['segments']}
    row_by_key = {r.get('key'): r for r in doc.bom}
    first_bom = None
    for sheet in doc.sheets:
        for el in sheet.get('elements') or []:
            if el.get('type') == 'bom':
                first_bom = el
                break
        if first_bom is not None:
            break
    n = len(doc.sheets)
    out = []
    for index, sheet in enumerate(doc.sheets, 1):
        spec = size_of(doc, sheet.get('size') or 'B')
        canvas = Sheet()
        canvas.page_size = (float(spec['width']), float(spec['height']))
        info = resolved_title(doc, sheet, index, n)
        zones = spec.get('zones') or [8, 4]
        draw_frame(
            canvas, info, index, n,
            width=spec['width'], height=spec['height'], zones=tuple(zones))
        for el in sheet.get('elements') or []:
            kind = el.get('type')
            if kind == 'view':
                shown = resolved_view(doc, sheet, el)
                draw_view_box(canvas, shown, view_caption(shown, sheet_scale(doc, sheet)))
                if el.get('kind') == 'detail' and el.get('detail'):
                    draw_detail_outline(canvas, el['detail'], el, _detail_ratio(doc, sheet, el, shown))
            elif kind == 'dim':
                draw_dimension(canvas, el, dimension_text(doc, sheet, el), basic=(el.get('tol') or {}).get('kind') == 'basic')
            elif kind == 'hole':
                draw_hole_callout(canvas, el, hole_callout_lines(el, doc.hole_tol, doc.properties))
            elif kind == 'bom':
                seg = by_region.get(el.get('id'))
                if seg and seg['rows']:
                    styled = dict(el)
                    styled['text_h'] = _bom_text_h(el, first_bom, seg['continued'])
                    styled['colw'] = list(_bom_colw(el, first_bom, seg['continued']))
                    styled['x1'] = seg['x1']
                    styled['ytop'] = seg['ytop']
                    draw_bom(canvas, [row_by_key[k] for k in seg['rows'] if k in row_by_key], styled, seg['continued'])
            elif kind == 'notes':
                draw_notes(
                    canvas, float(el['x']), float(el['y']), notes_with_auto(doc),
                    h=float(el.get('text_h') or 2.6), width=float(el.get('width') or 136))
            elif kind == 'balloon':
                number = item_of(doc, el.get('bom_key'))
                if number is not None:
                    draw_balloon(canvas, float(el['x']), float(el['y']), float(el['ax']), float(el['ay']), number)
            elif kind == 'note_flag':
                number = note_number(doc, el.get('note_key'))
                if number is not None:
                    draw_note_flag(canvas, float(el['x']), float(el['y']), float(el['ax']), float(el['ay']), number)
        _detail_marks(doc, sheet, canvas)
        out.append(canvas)
    return out


def _detail_ratio(doc, sheet, el, shown):
    """Detail scale over parent scale: how much bigger the area is in the detail frame."""
    dv = scale_value(shown.get('scale'))
    pv = None
    if el.get('parent'):
        psheet, parent = find_element(doc, el['parent'])
        if parent is not None:
            pv = scale_value(parent.get('scale') or sheet_scale(doc, psheet))
    if pv is None:
        pv = scale_value(sheet_scale(doc, sheet))
    return (dv / pv) if dv and pv else 2.0


def _detail_marks(doc, sheet, canvas):
    """Detail circles drawn on parent views that sit on this sheet."""
    ids = {el.get('id') for el in sheet.get('elements') or []}
    for other in doc.sheets:
        for el in other.get('elements') or []:
            if el.get('type') == 'view' and el.get('kind') == 'detail' and el.get('detail') \
                    and el.get('parent') in ids:
                frame = el if other is sheet else None
                draw_detail_mark(canvas, el['detail'], el.get('letter') or '?', frame)


def dimension_text(doc, sheet, el):
    """The text a dimension prints: its value plus its own tolerance.

    With no tol of its own, a hole position dimension uses the drawing's hole
    position tolerance, and anything else prints the value only (the
    title-block general tolerance applies).
    """
    tol = el.get('tol')
    if not tol and el.get('role') == 'hole_position':
        tol = (doc.hole_tol or {}).get('position')
    if not tol and el.get('role') == 'hole_size':
        tol = (doc.hole_tol or {}).get('size')
    value = el.get('value')
    if value in (None, ''):
        scale = None
        if el.get('view'):
            _s, view = find_element(doc, el['view'])
            if view is not None:
                scale = scale_value(view.get('scale'))
        if scale is None:
            scale = scale_value(sheet_scale(doc, sheet)) or 1.0
        value = round(dim_measure(el) / scale, 6)
    prefix = el.get('prefix') or ''
    return dim_text(value, tol, prefix=prefix, decimals=el.get('decimals'), props=doc.properties)


def export_pdf(doc, path):
    sheets = render_sheets(doc)
    missing = write_pdf(sheets, path)
    return len(sheets), missing
