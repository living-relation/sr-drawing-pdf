"""Sheet chrome: border, zones, title block, rev table, BOM, notes, balloons.

Coordinates are millimetres, origin at the bottom left. Size B is 431.8 x 279.4.
Text width for wrapping uses the same 0.82*height estimate as the drawings this
matches. The PDF writer centres text with real Helvetica widths.
"""
import math

PW, PH = 431.8, 279.4
TH = 3.0

STY = {
    'vis': (0.50, None),
    'hid': (0.25, (3.0, 1.5)),
    'ctr': (0.18, (8, 1.5, 1.5, 1.5)),
    'thin': (0.18, None),
    'dim': (0.18, None),
    'border': (0.70, None),
    'tb': (0.35, None),
    'phantom': (0.25, (8, 1.5, 1.5, 1.5, 1.5, 1.5)),
    'expl': (0.30, (0.4, 1.4)),
    'cut': (0.60, (10, 2, 2, 2)),
    'detail': (0.50, (7, 1.8)),
    'tan': (0.25, None),
}

# No edge-break line. A drawing that wants one passes its own tol text.
DEFAULT_TOL = (
    'DIMENSIONS ARE IN MILLIMETERS\n'
    'TOLERANCES:\n'
    '  X     \u00b10.5      X.X  \u00b10.2\n'
    '  X.XX  \u00b10.05    ANGLES \u00b10.5\u00b0\n'
    'SURFACE FINISH Ra 3.2 \u00b5m\n'
    'INTERPRET PER ASME Y14.5-2018'
)

REVLOG_COLS = (9, 66, 18, 15)
REVLOG_RH = 4.2
REVLOG_H = (1.8, 1.7)
REVLOG_HMIN = 1.3
REVLOG_MAX_H = 48.0
REVLOG_LP = 1.45

BOM_COLS = (9, 9, 44, 80, 40)
# handbuilt-cad drawing/asm.py bom_table(..., h=2.0). There is no bom_table.py.
# dwg.py turns that into points as h * (72/25.4) / 0.72, which is 7.874 pt
# in the filed FH-200 parts list.
BOM_TEXT_MM = 2.0
BOM_HEADS = ('ITEM', 'QTY', 'PART NUMBER', 'DESCRIPTION', 'MATERIAL / SPEC')
BALLOON_R = 5.2
BALLOON_TEXT_H = 4.4


class Sheet:
    """A list of drawing primitives. Items are tuples the PDF writer understands."""

    def __init__(self):
        self.items = []
        self.rects = []
        self.page_size = (PW, PH)

    def pl(self, pts, sty='thin', closed=False):
        self.items.append(('pl', [tuple(float(a) for a in p) for p in pts], sty, closed))

    def line(self, a, b, sty='thin'):
        self.pl([a, b], sty)

    def circle(self, c, r, sty='thin', n=48):
        pts = []
        for i in range(n + 1):
            t = 2 * math.pi * i / n
            pts.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
        self.pl(pts, sty)

    def txt(self, x, y, t, h=TH, ha='center', va='center', rot=0, bold=False, bg=False, layer='TEXT'):
        self.items.append(('tx', float(x), float(y), str(t), h, ha, va, rot, bool(bold), bool(bg), layer))

    def tri(self, pts):
        self.items.append(('tri', [tuple(float(a) for a in p) for p in pts]))


def _wrap(t, w, h, bold=False):
    """Wrap t to the column width w (mm) using the real font width. Never truncates."""
    from .font import text_width_mm
    avail = max(2.0, float(w) - 1.0)
    text = str(t)
    if text == '':
        return ['']
    lines = []
    for para in text.split('\n'):
        words = para.split(' ')
        cur = ''
        for word in words:
            pieces = _pieces(word, avail, h, bold)
            for extra, piece in enumerate(pieces):
                if extra and cur:
                    lines.append(cur)
                    cur = ''
                trial = piece if not cur else cur + ' ' + piece
                if cur and text_width_mm(trial, h, bold) > avail:
                    lines.append(cur)
                    cur = piece
                else:
                    cur = trial
        lines.append(cur)
    return lines or ['']


def _pieces(word, avail, h, bold):
    """Split a word that is wider than the column. Shorter words stay whole."""
    from .font import text_width_mm
    if text_width_mm(word, h, bold) <= avail:
        return [word]
    parts = []
    cur = ''
    for ch in word:
        trial = cur + ch
        if cur and text_width_mm(trial, h, bold) > avail:
            parts.append(cur)
            cur = ch
        else:
            cur = trial
    if cur:
        parts.append(cur)
    return parts or ['']


def _edges(x0, cols):
    xs = [x0]
    for w in cols:
        xs.append(xs[-1] + w)
    return xs


def revlog_layout(rows, max_h=REVLOG_MAX_H):
    """Wrapped cell lines and row heights for the rev log.

    Returns (cells, heights, (hd, ho), total_height).
    """
    if isinstance(rows, int):
        rows = [None] * rows
    hd, ho = REVLOG_H
    while True:
        cells = []
        hts = []
        for e in (rows or [None]):
            c = ('-', '(NO REV LOG)', '', '') if e is None else (e.rev, e.desc, e.by, e.date)
            ls = []
            for k, x in enumerate(c):
                if k in (1, 2):
                    ls.append(_wrap(x, REVLOG_COLS[k], hd if k == 1 else ho))
                else:
                    ls.append([str(x)])
            n = max(len(line) for line in ls)
            cells.append(ls)
            hts.append(max(REVLOG_RH, n * max(hd, ho) * REVLOG_LP + 1.4))
        tot = REVLOG_RH * 2 + sum(hts)
        if tot <= max_h or max(hd, ho) <= REVLOG_HMIN + 1e-9:
            return cells, hts, (hd, ho), tot
        hd = round(max(REVLOG_HMIN, hd - 0.1), 2)
        ho = round(max(REVLOG_HMIN, ho - 0.1), 2)


def revlog_rect(rows, x1=PW - 10, y1=PH - 10):
    tot = revlog_layout(rows)[3]
    return (x1 - sum(REVLOG_COLS), y1 - tot, x1, y1)


def revlog_table(sh, rows, x1=PW - 10, y1=PH - 10):
    """Rev | Description | By | Date in the top-right corner. Returns the rect."""
    cells, hts, (hd, ho), tot = revlog_layout(rows)
    x0, y0 = x1 - sum(REVLOG_COLS), y1 - tot
    rh = REVLOG_RH
    xs = _edges(x0, REVLOG_COLS)
    sh.pl([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 'tb', closed=True)
    sh.line((x0, y1 - rh), (x1, y1 - rh), 'thin')
    sh.items.append(('tx', (x0 + x1) / 2, y1 - rh / 2, 'REVISIONS', 2.2, 'center', 'center', 0, True, False, 'TEXT'))
    yt = y1 - rh
    for k, hdr in enumerate(('REV', 'DESCRIPTION', 'BY', 'DATE')):
        sh.items.append(('tx', (xs[k] + xs[k + 1]) / 2, yt - rh / 2, hdr, 1.8, 'center', 'center', 0, True, False, 'TEXT'))
    yt -= rh
    sh.line((x0, yt), (x1, yt), 'thin')
    for ls, r in zip(cells, hts):
        for k, lines in enumerate(ls):
            h = hd if k == 1 else ho
            lp = max(hd, ho) * REVLOG_LP
            ytop = yt - r / 2 + (len(lines) - 1) * lp / 2
            for i, t in enumerate(lines):
                y = ytop - i * lp
                if k == 1:
                    sh.items.append(('tx', xs[k] + 1, y, t, h, 'left', 'center', 0, False, False, 'TEXT'))
                else:
                    sh.items.append(('tx', (xs[k] + xs[k + 1]) / 2, y, t, h, 'center', 'center', 0, k == 0, False, 'TEXT'))
        yt -= r
        if yt > y0 + 1e-6:
            sh.line((x0, yt), (x1, yt), 'thin')
    for a in xs[1:-1]:
        sh.line((a, y0), (a, y1 - rh), 'thin')
    sh.rects.append((x0, y0, x1, y1))
    return (x0, y0, x1, y1)


def _row_label(j):
    if 0 <= j < 26:
        return chr(ord('A') + j)
    return str(j + 1)


def draw_frame(sh, info, sheet_no, n_sheets, width=None, height=None, zones=(8, 4)):
    """Border,  zone grid, title block, third-angle symbol, tolerance block.

    Sheet 1 also gets the rev table when info['revlog'] is a list (maybe empty).
    info['draft'] (an int) adds the draft stamp and a watermark item.
    """
    from .settings import title_info
    info = title_info(dict(info))
    width = PW if width is None else float(width)
    height = PH if height is None else float(height)
    cols, rows = int(zones[0]), int(zones[1])
    m = 10.0
    sh.pl([(m, m), (width - m, m), (width - m, height - m), (m, height - m)], 'border', closed=True)
    sh.pl([(5, 5), (width - 5, 5), (width - 5, height - 5), (5, height - 5)], 'thin', closed=True)
    for i in range(1, cols):
        x = m + i * (width - 2 * m) / cols
        sh.line((x, 5), (x, m), 'thin')
        sh.line((x, height - 5), (x, height - m), 'thin')
    for i in range(cols):
        x = m + (i + 0.5) * (width - 2 * m) / cols
        lab = str(cols - i)
        sh.txt(x, 7.5, lab, h=2.5)
        sh.txt(x, height - 7.5, lab, h=2.5)
    for j in range(1, rows):
        y = m + j * (height - 2 * m) / rows
        sh.line((5, y), (m, y), 'thin')
        sh.line((width - 5, y), (width - m, y), 'thin')
    for j in range(rows):
        y = m + (j + 0.5) * (height - 2 * m) / rows
        lab = _row_label(j)
        sh.txt(7.5, y, lab, h=2.5)
        sh.txt(width - 7.5, y, lab, h=2.5)

    x1 = width - m
    x0 = x1 - 178
    y0 = m
    y1 = y0 + 52
    sh.pl([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], 'tb', closed=True)

    def box(a, b, c, d, label, val, vh=3.2, bold=False):
        sh.pl([(a, b), (c, b), (c, d), (a, d)], 'thin', closed=True)
        sh.txt(a + 1, d - 1, label, h=1.8, ha='left', va='top')
        sh.txt((a + c) / 2, (b + d) / 2 - 1.2, val, h=vh, bold=bold)

    title = info.get('title') or ''
    material = info.get('material') or '-'
    source = info.get('source') or ''
    box(x0, y1 - 10, x1, y1, 'COMPANY / PROJECT', info.get('project') or '', 3.2, True)
    box(x0, y1 - 24, x1, y1 - 10, 'TITLE', title, 4.6 if len(title) < 38 else 3.6, True)
    box(x0, y1 - 34, x0 + 90, y1 - 24, 'PART / DWG NO.', info.get('pn') or '', 3.2, True)
    box(x0 + 90, y1 - 34, x0 + 110, y1 - 24, 'REV', info.get('rev') or '', 3.6, True)
    box(x0 + 110, y1 - 34, x1, y1 - 24, 'MATERIAL', material, 2.6 if len(material) > 22 else 3.0)
    box(x0, y0 + 8, x0 + 30, y1 - 34, 'SCALE', info.get('scale') or '-', 3.0)
    box(x0 + 30, y0 + 8, x0 + 52, y1 - 34, 'UNITS', info.get('units') or 'mm', 3.0)
    box(x0 + 52, y0 + 8, x0 + 80, y1 - 34, 'SIZE', info.get('size_label') or 'B (11x17)', 2.6)
    box(x0 + 80, y0 + 8, x0 + 108, y1 - 34, 'SHEET', '%s OF %s' % (sheet_no, n_sheets), 3.0)
    box(x0 + 108, y0 + 8, x0 + 140, y1 - 34, 'DATE', info.get('date') or '', 2.8)
    drawn = info.get('drawn') or ''
    box(x0 + 140, y0 + 8, x1, y1 - 34, 'DRAWN', drawn, 3.0 if len(drawn) < 20 else 2.4)
    box(x0, y0, x0 + 140, y0 + 8, 'SOURCE', source, min(2.0, 2.0 * 86 / max(1, len(source))))

    a, b = x0 + 140, y0
    sh.pl([(a, b), (x1, b), (x1, b + 8), (a, b + 8)], 'thin', closed=True)
    cx, cy = a + 11, b + 4
    sh.pl([(cx - 6, cy - 2.2), (cx - 1.5, cy - 1.2), (cx - 1.5, cy + 1.2), (cx - 6, cy + 2.2)], 'thin', closed=True)
    sh.line((cx - 7, cy), (cx - 0.5, cy), 'ctr')
    sh.circle((cx + 4, cy), 2.2, 'thin')
    sh.circle((cx + 4, cy), 1.0, 'thin')
    sh.txt(a + 27, cy, '3RD ANGLE', h=1.8)

    tx0 = x0 - 92
    sh.pl([(tx0, y0), (x0, y0), (x0, y0 + 40), (tx0, y0 + 40)], 'tb', closed=True)
    sh.txt(tx0 + 2, y0 + 38, 'UNLESS OTHERWISE SPECIFIED:', h=2.2, ha='left', va='top', bold=True)
    sh.txt(tx0 + 2, y0 + 33.5, info.get('tol') or DEFAULT_TOL, h=2.2, ha='left', va='top')

    if info.get('draft'):
        label = 'DRAFT %s, NOT RELEASED' % int(info['draft'])
        sh.pl([(x0, y1), (x1, y1), (x1, y1 + 7), (x0, y1 + 7)], 'tb', closed=True)
        sh.txt((x0 + x1) / 2, y1 + 3.5, label, h=3.0, bold=True)
        sh.items.append(('wm', width / 2, height / 2, label, 16, 32))

    if sheet_no == 1 and info.get('revlog') is not None:
        revlog_table(sh, info['revlog'], x1=width - 10, y1=height - 10)


def bom_row_cells(row):
    desc = str(row.get('desc') or '')
    if not row.get('shown', True) and '(NOT SHOWN)' not in desc:
        desc = desc + ' (NOT SHOWN)'
    return [
        str(row.get('item', '')),
        str(row.get('qty', '')),
        str(row.get('pn') or ''),
        desc,
        str(row.get('mat') or ''),
    ]


def bom_row_height(cells, colw, h):
    wrapped = [_wrap(c, colw[i], h) for i, c in enumerate(cells)]
    nl = max(len(w) for w in wrapped)
    rh = h * 2.1
    hh = rh * (1 + 0.75 * (nl - 1))
    return hh, wrapped


def bom_header_height(h, continued):
    rh = h * 2.1
    band = rh * 1.2
    if continued:
        band += rh
    return band


def draw_bom(sh, rows, el, continued):
    """Draw one BOM segment. `rows` are already the rows that fit here."""
    h = float(BOM_TEXT_MM if el.get('text_h') is None else el.get('text_h'))
    colw = tuple(float(c) for c in (el.get('colw') or BOM_COLS))
    x1 = float(el['x1'])
    top = float(el['ytop'])
    x0 = x1 - sum(colw)
    rh = h * 2.1
    y = top
    if continued:
        sh.pl([(x0, y), (x1, y), (x1, y - rh), (x0, y - rh)], 'tb', closed=True)
        sh.txt((x0 + x1) / 2, y - rh / 2, 'BILL OF MATERIALS (CONT.)', h=h, bold=True)
        y -= rh
    grid_top = y
    sh.pl([(x0, y), (x1, y), (x1, y - rh * 1.2), (x0, y - rh * 1.2)], 'tb', closed=True)
    xs = _edges(x0, colw)
    for i, hd in enumerate(BOM_HEADS):
        sh.txt((xs[i] + xs[i + 1]) / 2, y - rh * 0.6, hd, h=h, bold=True)
    y -= rh * 1.2
    for row in rows:
        cells = bom_row_cells(row)
        hh, wrapped = bom_row_height(cells, colw, h)
        sh.pl([(x0, y), (x1, y), (x1, y - hh), (x0, y - hh)], 'thin', closed=True)
        for i, lines in enumerate(wrapped):
            t = '\n'.join(lines)
            if i < 2:
                sh.txt((xs[i] + xs[i + 1]) / 2, y - hh / 2, t, h=h)
            else:
                sh.txt(xs[i] + 1, y - hh / 2, t, h=h, ha='left')
        y -= hh
    for xx in xs[1:-1]:
        sh.line((xx, grid_top), (xx, y), 'thin')
    sh.pl([(x0, top), (x1, top), (x1, y), (x0, y)], 'tb', closed=True)
    return y


def draw_notes(sh, x, y, notes, h=2.6, width=136):
    sh.txt(x, y, 'NOTES:', h=3.0, ha='left', va='top', bold=True)
    yy = y - 5
    for i, note in enumerate(notes, 1):
        text = note.get('text') if isinstance(note, dict) else str(note)
        body = '\n'.join(_wrap(str(text).replace('\n', ' '), width, h))
        # Hang the wrapped lines under the number.
        if '\n' in body:
            first, rest = body.split('\n', 1)
            rest = '\n'.join('     ' + line for line in rest.split('\n'))
            body = first + '\n' + rest
        line = '%d.  %s' % (i, body)
        sh.txt(x, yy, line, h=h, ha='left', va='top')
        nh = h * 1.6 * (line.count('\n') + 1)
        yy -= nh + 1.0
    return yy


def draw_balloon(sh, x, y, ax, ay, number, r=None):
    """Circled item number. The leader ends on the part: no arrowhead and no dot."""
    from .font import text_width_mm
    label = str(number)
    h = BALLOON_TEXT_H
    if r is None:
        r = max(BALLOON_R, text_width_mm(label, h, True) / 2.0 + 1.4)
    sh.circle((x, y), r, 'tb')
    sh.txt(x, y, label, h=h, bold=True)
    dx, dy = ax - x, ay - y
    dist = math.hypot(dx, dy)
    if dist > r:
        sh.line((x + dx / dist * r, y + dy / dist * r), (ax, ay), 'dim')


def draw_note_flag(sh, x, y, ax, ay, number):
    s = 4.2
    pts = [(x, y + s), (x + s * 0.92, y - s * 0.72), (x - s * 0.92, y - s * 0.72)]
    sh.pl(pts, 'tb', closed=True)
    sh.txt(x, y - 0.5, str(number), h=3.2, bold=True)
    dx, dy = ax - x, ay - y
    dist = math.hypot(dx, dy)
    if dist > s:
        sh.line((x + dx / dist * s, y + dy / dist * s), (ax, ay), 'dim')


def draw_view_box(sh, el):
    x, y = float(el['x']), float(el['y'])
    w, h = float(el['w']), float(el['h'])
    sh.pl([(x, y), (x + w, y), (x + w, y + h), (x, y + h)], 'thin', closed=True)
    t = 3.0
    sh.line((x, y + t), (x + t, y), 'thin')
    sh.line((x + w - t, y + h), (x + w, y + h - t), 'thin')
    sh.txt(x + w / 2, y + h / 2 + 2.2, el.get('label') or 'VIEW', h=3.4, bold=True)
    scale = el.get('scale')
    sub = ('SCALE %s' % scale) if scale else 'VIEW FRAME'
    sh.txt(x + w / 2, y + h / 2 - 3.2, sub, h=2.2)
