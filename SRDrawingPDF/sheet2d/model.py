"""Serializable drawing document. JSON in, JSON out. No Fusion types."""
import copy

from .canvas import (
    BOM_COLS,
    BOM_COLS_COMPACT,
    PW,
    PH,
    BOM_TEXT_MM,
    bom_header_height,
    bom_row_cells,
    bom_row_height,
    revlog_rect,
    tol_lines,
    tol_max_lines,
)
from .revs import (
    REVLOG_MAX_ROWS,
    RevEntry,
    check_letter_matches,
    drawn_by,
    initials_problems,
    table_rows,
)

BUILTIN_SIZES = {
    'B': {
        'width': PW,
        'height': PH,
        'label': 'B (11x17)',
        'zones': [8, 4],
    },
}

TITLE_FIELDS = (
    'project', 'title', 'pn', 'rev', 'material', 'scale', 'units', 'date', 'drawn', 'source', 'tol',
)

_EMPTY_PROPS = {
    'project': '',
    'title': '',
    'pn': '',
    'rev': '',
    'material': 'SEE BOM',
    'scale': '',
    'units': 'mm',
    'date': '',
    'drawn': '',
    'source': '',
    'tol': None,
    'tol_tiers': None,
    'tol_angle': None,
}


def _entry_dict(e):
    e = e if isinstance(e, RevEntry) else RevEntry(e['rev'], e.get('desc', ''), e.get('by', ''), e.get('date', ''))
    return {'rev': e.rev, 'desc': e.desc, 'by': e.by, 'date': e.date}


def _as_entry(e):
    if isinstance(e, RevEntry):
        return e
    return RevEntry(str(e.get('rev') or ''), str(e.get('desc') or ''), str(e.get('by') or ''), str(e.get('date') or ''))


class DrawingDocument(object):
    def __init__(self):
        self.version = 1
        self.seq = 0
        self.draft = None
        self.properties = dict(_EMPTY_PROPS)
        self.revlog = []
        self.bom = []
        self.notes = []
        self.sheets = []
        self.sizes = {}
        self.hole_tol = None
        self.suggestions = []

    def to_dict(self):
        return {
            'version': 1,
            'seq': self.seq,
            'draft': self.draft,
            'properties': dict(self.properties),
            'revlog': [_entry_dict(e) for e in self.revlog],
            'bom': [dict(r) for r in self.bom],
            'notes': [dict(n) for n in self.notes],
            'sheets': copy.deepcopy(self.sheets),
            'sizes': copy.deepcopy(self.sizes),
            'hole_tol': copy.deepcopy(self.hole_tol),
            'suggestions': copy.deepcopy(self.suggestions),
        }

    @classmethod
    def from_dict(cls, data):
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValueError('document must be a dict or null')
        data = copy.deepcopy(data)
        version = data.get('version', 1)
        if version != 1:
            raise ValueError('unsupported drawing version %r' % version)
        doc = cls()
        doc.seq = int(data.get('seq') or 0)
        draft = data.get('draft')
        doc.draft = None if draft in (None, '') else int(draft)
        props = data.get('properties') or {}
        for key in _EMPTY_PROPS:
            if key in props:
                doc.properties[key] = props[key]
        doc.revlog = [_as_entry(e) for e in (data.get('revlog') or [])]
        doc.bom = list(data.get('bom') or [])
        doc.notes = list(data.get('notes') or [])
        doc.sheets = list(data.get('sheets') or [])
        doc.sizes = dict(data.get('sizes') or {})
        doc.hole_tol = data.get('hole_tol') or None
        doc.suggestions = list(data.get('suggestions') or [])
        for sug in doc.suggestions:
            _observe(doc, sug.get('id'))
        for sheet in doc.sheets:
            _observe(doc, sheet.get('id'))
            for el in sheet.get('elements') or []:
                _observe(doc, el.get('id'))
        for row in doc.bom:
            _observe(doc, row.get('key'))
        for note in doc.notes:
            _observe(doc, note.get('key'))
        return doc


def _observe(doc, id_):
    if not id_:
        return
    tail = ''
    for ch in str(id_)[::-1]:
        if ch.isdigit():
            tail = ch + tail
        else:
            break
    if tail:
        doc.seq = max(doc.seq, int(tail))


def alloc_id(doc, prefix):
    doc.seq += 1
    return '%s%d' % (prefix, doc.seq)


def size_of(doc, name):
    if name in doc.sizes:
        return doc.sizes[name]
    if name in BUILTIN_SIZES:
        return BUILTIN_SIZES[name]
    raise ValueError('unknown sheet size %r' % name)


def sheet_by_id(doc, sheet_id):
    for i, sheet in enumerate(doc.sheets):
        if sheet.get('id') == sheet_id:
            return i, sheet
    raise ValueError('no sheet %r' % sheet_id)


def find_element(doc, element_id):
    if not element_id:
        return None, None
    for sheet in doc.sheets:
        for el in sheet.get('elements') or []:
            if el.get('id') == element_id:
                return sheet, el
    return None, None


def item_of(doc, bom_key):
    for row in doc.bom:
        if row.get('key') == bom_key:
            return row.get('item')
    return None


def note_number(doc, note_key):
    for i, note in enumerate(doc.notes, 1):
        if note.get('key') == note_key:
            return i
    return None


def sheet_scale(doc, sheet):
    """The scale every view on this sheet uses unless it sets its own."""
    return sheet.get('scale') or doc.properties.get('scale') or ''


def resolved_view(doc, sheet, el):
    """A view with its scale filled in. A detail view's scale comes from its scale_mode."""
    if el.get('kind') != 'detail' or not el.get('detail'):
        return el
    from .detail import resolve_scale
    out = dict(el)
    parent_scale = None
    if el.get('parent'):
        psheet, parent = find_element(doc, el['parent'])
        if parent is not None:
            parent_scale = parent.get('scale') or sheet_scale(doc, psheet)
    out['scale'] = resolve_scale(el['detail'], parent_scale, sheet_scale(doc, sheet))
    return out


def notes_with_auto(doc):
    """User notes, then the hole tolerance note when the drawing has one.

    The automatic note goes last so it never renumbers a user note or a flag.
    """
    from .annotate import hole_note_text
    notes = list(doc.notes)
    text = hole_note_text(doc.hole_tol, doc.properties)
    if text:
        notes.append({'key': '_hole_tol', 'text': text})
    return notes


def resolved_title(doc, sheet, sheet_no, n_sheets):
    """Title-block fields for one sheet. Linked to the document, plus sheet n of m."""
    from .settings import title_info
    info = title_info(dict(doc.properties))
    info['units'] = info.get('units') or 'mm'
    if not info.get('material'):
        info['material'] = 'SEE BOM'
    if sheet.get('scale'):
        info['scale'] = sheet['scale']
    elif not info.get('scale'):
        info['scale'] = '-'
    if not info.get('drawn'):
        info['drawn'] = drawn_by(doc.revlog) or ''
    spec = size_of(doc, sheet.get('size') or 'B')
    info['size_label'] = spec.get('label') or sheet.get('size') or 'B'
    info['size'] = sheet.get('size') or 'B'
    if not info.get('tol'):
        from .annotate import block_text
        info['tol'] = block_text(doc.properties)
    info['draft'] = doc.draft
    info['revlog'] = table_rows(doc.revlog, REVLOG_MAX_ROWS) if sheet_no == 1 else None
    info['sheet_no'] = sheet_no
    info['n_sheets'] = n_sheets
    return info


BOM_ANCHORS = ('bottom_left', 'above_title', 'free')
FRAME_MARGIN = 10.0
TITLE_W = 178.0
TITLE_H = 52.0


def bom_anchor(el):
    """A region's anchor. Old regions with x1/ytop and no anchor are free."""
    return el.get('anchor') or 'free'


def _sheet_wh(doc, sheet):
    spec = size_of(doc, sheet.get('size') or 'B')
    return float(spec['width']), float(spec['height'])


def _capacity(doc, sheet, el):
    """Height a region may use: its max_height, else the room its anchor leaves."""
    max_h = float(el.get('max_height') or 0)
    if max_h > 0:
        return max_h
    anchor = bom_anchor(el)
    _w, height = _sheet_wh(doc, sheet)
    if anchor == 'bottom_left':
        return height - 2 * FRAME_MARGIN
    if anchor == 'above_title':
        return height - 2 * FRAME_MARGIN - TITLE_H - (7.0 if doc.draft else 0.0)
    return 0.0


def _place(doc, sheet, el, colw, used):
    """Right edge x1 and top y of a region holding `used` mm of table."""
    anchor = bom_anchor(el)
    width, _h = _sheet_wh(doc, sheet)
    if anchor == 'bottom_left':
        return FRAME_MARGIN + sum(colw), FRAME_MARGIN + used
    if anchor == 'above_title':
        base = FRAME_MARGIN + TITLE_H + (7.0 if doc.draft else 0.0)
        return width - FRAME_MARGIN, base + used
    return float(el.get('x1') or 0), float(el.get('ytop') or 0)


def bom_regions(doc):
    regions = []
    for sheet in doc.sheets:
        for el in sheet.get('elements') or []:
            if el.get('type') == 'bom':
                regions.append((sheet, el))
    return regions


def layout_bom(doc):
    """Split BOM rows across placed regions (table pieces), in sheet order then element order.

    A later region is a continuation table with its own header. A region made
    by split_table carries start_key: it starts at that row, and the region
    before it stops there. Rows that do not fit are listed in overflow (not drawn).
    """
    regions = bom_regions(doc)
    segments = []
    idx = 0
    rows = doc.bom
    index_of = {r.get('key'): i for i, r in enumerate(rows)}
    starts = [index_of.get(el.get('start_key')) if el.get('start_key') else None for _s, el in regions]
    first = regions[0][1] if regions else None
    skipped = []
    for n, (sheet, el) in enumerate(regions):
        start = starts[n]
        if start is not None and start > idx:
            skipped.extend(r.get('key') for r in rows[idx:start])
            idx = start
        stop = len(rows)
        bounded = False
        for later in starts[n + 1:]:
            if later is not None and later > idx:
                stop = later
                bounded = True
                break
        continued = any(seg['rows'] for seg in segments)
        h = _bom_text_h(el, first, continued)
        colw = _bom_colw(el, first, continued)
        cap = _capacity(doc, sheet, el)
        taken = []
        used = 0.0
        if cap > 0:
            used = bom_header_height(h, continued)
            while idx < stop:
                hh, _wrapped = bom_row_height(bom_row_cells(rows[idx]), colw, h)
                if taken and used + hh > cap + 1e-6:
                    break
                taken.append(rows[idx].get('key'))
                used += hh
                idx += 1
            if not taken:
                used = 0.0
            if bounded and idx < stop:
                skipped.extend(r.get('key') for r in rows[idx:stop])
                idx = stop
        x1, top = _place(doc, sheet, el, colw, used)
        segments.append({
            'id': el.get('id'),
            'sheet': sheet.get('id'),
            'continued': continued,
            'anchor': bom_anchor(el),
            'rows': taken,
            'x1': round(x1, 4),
            'ytop': round(top, 4),
            'bottom': round(top - used, 4),
        })
    overflow = skipped + [r.get('key') for r in rows[idx:]]
    return {'segments': segments, 'overflow': overflow}


def _bom_text_h(el, first, continued):
    """Continuation tables use the first table's text size unless one is set."""
    if el.get('text_h') is not None:
        return float(el['text_h'])
    if continued and first is not None and first.get('text_h') is not None:
        return float(first['text_h'])
    return BOM_TEXT_MM


def _bom_colw(el, first, continued):
    colw = el.get('colw')
    if not colw and continued and first is not None and first.get('colw'):
        colw = first.get('colw')
    if not colw and bom_anchor(el) == 'bottom_left':
        # Narrow enough to sit left of the block tolerance box on size B.
        colw = BOM_COLS_COMPACT
    return tuple(float(c) for c in (colw or BOM_COLS))


def _overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _bom_warnings(doc, warnings):
    counts = {}
    for row in doc.bom:
        counts.setdefault(row.get('item'), []).append(row.get('key'))
    for item, keys in counts.items():
        if len(keys) > 1:
            warnings.append('duplicate BOM item number %s (%s)' % (item, ', '.join(str(k) for k in keys)))
    rows = table_rows(doc.revlog, REVLOG_MAX_ROWS)
    first = None
    for sheet in doc.sheets:
        for el in sheet.get('elements') or []:
            if el.get('type') == 'bom' and first is None:
                first = el
    layout = layout_bom(doc)
    seg_by_id = {seg['id']: seg for seg in layout['segments']}
    for index, sheet in enumerate(doc.sheets):
        width, height = _sheet_wh(doc, sheet)
        margin = FRAME_MARGIN
        title = (width - margin - TITLE_W - 92.0, margin, width - margin, margin + TITLE_H)
        rev = revlog_rect(rows, x1=width - margin, y1=height - margin) if index == 0 else None
        for el in sheet.get('elements') or []:
            if el.get('type') != 'bom':
                continue
            seg = seg_by_id.get(el.get('id'))
            if bom_anchor(el) == 'free' and float(el.get('max_height') or 0) <= 0:
                warnings.append('BOM region %s has no height' % el.get('id'))
                continue
            if not seg or not seg['rows']:
                continue
            colw = _bom_colw(el, first, seg['continued'])
            box = (seg['x1'] - sum(colw), seg['bottom'], seg['x1'], seg['ytop'])
            if box[0] < -0.01 or box[1] < -0.01 or box[2] > width + 0.01 or box[3] > height + 0.01:
                warnings.append('BOM region %s runs off the sheet' % el.get('id'))
            if _overlap(box, title):
                warnings.append('BOM region %s overlaps the title block' % el.get('id'))
            if rev is not None and _overlap(box, rev):
                warnings.append('BOM region %s overlaps the rev table' % el.get('id'))


def document_warnings(doc):
    warnings = []
    rows = table_rows(doc.revlog, REVLOG_MAX_ROWS)
    try:
        check_letter_matches(doc.properties.get('rev') or '', rows)
    except ValueError as exc:
        warnings.append(str(exc))
    warnings.extend(initials_problems(doc.revlog))
    layout = layout_bom(doc)
    if layout['overflow']:
        warnings.append('BOM rows do not fit: %s' % ', '.join(str(k) for k in layout['overflow']))
    _bom_warnings(doc, warnings)
    from .annotate import block_text
    n_tol = len(tol_lines(doc.properties.get('tol') or block_text(doc.properties)))
    if n_tol > tol_max_lines():
        warnings.append('tolerance text needs %d lines; the block fits %d' % (n_tol, tol_max_lines()))
    keys = {r.get('key') for r in doc.bom}
    note_keys = {n.get('key') for n in doc.notes}
    for sheet in doc.sheets:
        for el in sheet.get('elements') or []:
            if el.get('type') == 'balloon' and el.get('bom_key') not in keys:
                warnings.append('balloon %s has no BOM row' % el.get('id'))
            if el.get('type') == 'note_flag' and el.get('note_key') not in note_keys:
                warnings.append('note flag %s has no note' % el.get('id'))
    _annotation_warnings(doc, warnings)
    return warnings


def _annotation_warnings(doc, warnings):
    from .annotate import hole_note_text, is_default_name, same_scale, scale_value
    letters = {}
    has_notes_block = False
    for sheet in doc.sheets:
        sc = sheet_scale(doc, sheet)
        for el in sheet.get('elements') or []:
            kind = el.get('type')
            if kind == 'notes':
                has_notes_block = True
            elif kind == 'view':
                vk = el.get('kind') or 'standard'
                if vk in ('detail', 'section'):
                    if not el.get('letter'):
                        warnings.append('%s view %s has no letter' % (vk, el.get('id')))
                    else:
                        letters.setdefault(str(el['letter']).upper(), []).append(el.get('id'))
                if el.get('scale') not in (None, '') and scale_value(el.get('scale')) is None \
                        and str(el.get('scale')).strip().upper() != 'AS SHOWN':
                    warnings.append('view %s scale %r is not a ratio like 1:2' % (el.get('id'), el.get('scale')))
                if vk == 'standard' and el.get('show_label') and is_default_name(el.get('label')) \
                        and same_scale(el.get('scale'), sc):
                    warnings.append('view %s is a default view at the sheet scale; it normally has no label'
                                    % el.get('id'))
                if vk == 'detail' and el.get('detail'):
                    _ps, parent = find_element(doc, el.get('parent'))
                    if parent is None or parent.get('type') != 'view':
                        warnings.append('detail view %s has no parent view' % el.get('id'))
            elif kind == 'dim' and el.get('tol'):
                from .render import dimension_text
                tol = el['tol']
                bare = dimension_text(doc, sheet, dict(el, tol=None, role=None))
                if tol.get('kind') in ('pm', 'dev') and dimension_text(doc, sheet, el) == bare:
                    warnings.append('dimension %s tolerance matches the block tolerance and does not print'
                                    % el.get('id'))
        if not sc:
            for el in sheet.get('elements') or []:
                if el.get('type') == 'view':
                    warnings.append('sheet %s has no scale in the title block' % sheet.get('id'))
                    break
    for letter, ids in letters.items():
        if len(ids) > 1:
            warnings.append('view letter %s is used more than once (%s)' % (letter, ', '.join(ids)))
    if doc.properties.get('tol') and doc.properties.get('tol_tiers'):
        warnings.append('the custom tol text replaces the tolerance tiers in the title block')
    if hole_note_text(doc.hole_tol, doc.properties) and not has_notes_block:
        warnings.append('the hole tolerance note has no notes block to print in')
