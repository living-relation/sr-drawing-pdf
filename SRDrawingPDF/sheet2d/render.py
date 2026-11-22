"""Turn a drawing document into sheet primitives and a PDF."""
from .annotate import dim_measure, dim_text, hole_callout_lines, scale_value, view_caption
from .canvas import (
    Sheet, draw_balloon, draw_bom, draw_dimension, draw_frame, draw_hole_callout, draw_note_flag, draw_notes,
    draw_view_box,
)
from .model import (
    _bom_colw, _bom_text_h, find_element, item_of, layout_bom, note_number, notes_with_auto, resolved_title,
    sheet_scale, size_of,
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
                draw_view_box(canvas, el, view_caption(el, sheet_scale(doc, sheet)))
            elif kind == 'dim':
                draw_dimension(canvas, el, dimension_text(doc, sheet, el), basic=(el.get('tol') or {}).get('kind') == 'basic')
            elif kind == 'hole':
                draw_hole_callout(canvas, el, hole_callout_lines(el, doc.hole_tol))
            elif kind == 'bom':
                seg = by_region.get(el.get('id'))
                if seg and seg['rows']:
                    styled = dict(el)
                    styled['text_h'] = _bom_text_h(el, first_bom, seg['continued'])
                    styled['colw'] = list(_bom_colw(el, first_bom, seg['continued']))
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
        out.append(canvas)
    return out


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
    return dim_text(value, tol, prefix=prefix, decimals=el.get('decimals'))


def export_pdf(doc, path):
    sheets = render_sheets(doc)
    missing = write_pdf(sheets, path)
    return len(sheets), missing
