"""Turn a drawing document into sheet primitives and a PDF."""
from .canvas import Sheet, draw_balloon, draw_bom, draw_frame, draw_note_flag, draw_notes, draw_view_box
from .model import _bom_colw, _bom_text_h, item_of, layout_bom, note_number, resolved_title, size_of
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
                draw_view_box(canvas, el)
            elif kind == 'bom':
                seg = by_region.get(el.get('id'))
                if seg and seg['rows']:
                    styled = dict(el)
                    styled['text_h'] = _bom_text_h(el, first_bom, seg['continued'])
                    styled['colw'] = list(_bom_colw(el, first_bom, seg['continued']))
                    draw_bom(canvas, [row_by_key[k] for k in seg['rows'] if k in row_by_key], styled, seg['continued'])
            elif kind == 'notes':
                draw_notes(
                    canvas, float(el['x']), float(el['y']), doc.notes,
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


def export_pdf(doc, path):
    sheets = render_sheets(doc)
    missing = write_pdf(sheets, path)
    return len(sheets), missing
