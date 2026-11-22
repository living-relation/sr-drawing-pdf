"""Vector PDF with DejaVu Sans embedded (the same family as the filed drawings).

Page space is points, origin bottom left. Drawing space is millimetres.
Characters the font does not have are reported, not silently replaced.
"""
import math

from .canvas import STY
from .font import face

MM = 72.0 / 25.4
# Light enough that table text stays readable. Drawn before the sheet content.
WATERMARK_GRAY = 0.90


# dwg.py draws text at fontsize = h * (72/25.4) / 0.72. That is the point size
# in the filed FH-200 PDF (BOM h=2.0 mm is 7.874 pt).
ENGINE_CAP = 0.72


def font_pt(h_mm, bold=False):
    """Point size for a text height h_mm, using the drawing engine's 0.72 factor."""
    return float(h_mm) * MM / ENGINE_CAP


def text_width_mm(text, h_mm, bold=False):
    from .font import text_width_mm as _width
    return _width(text, h_mm, bold)


def _cap_mm(h_mm, bold=False):
    return float(h_mm)


def _text_op(x_mm, y_mm, text, h_mm, bold, rot, missing, faces):
    loaded = faces[bool(bold)]
    ids, miss = loaded.glyphs(text)
    missing.extend(miss)
    size = font_pt(h_mm, bold)
    face_name = 'F2' if bold else 'F1'
    hexbody = ''.join('%04X' % gid for gid in ids)
    shown = '<%s> Tj' % hexbody
    size_s = '%.5f' % size
    if not rot:
        return 'BT /%s %s Tf %.3f %.3f Td %s ET' % (face_name, size_s, x_mm * MM, y_mm * MM, shown)
    ang = math.radians(rot)
    c, s = math.cos(ang), math.sin(ang)
    return 'BT /%s %s Tf %.4f %.4f %.4f %.4f %.3f %.3f Tm %s ET' % (
        face_name, size_s, c, s, -s, c, x_mm * MM, y_mm * MM, shown)


def _draw_text(ops, x, y, text, h, ha, va, rot, bold, missing, faces):
    lines = str(text).split('\n')
    pitch = h * 1.6
    cap = _cap_mm(h, bold)
    n = len(lines)
    if va == 'top':
        base0 = y - cap
    elif va == 'bottom':
        base0 = y + pitch * (n - 1)
    else:
        block = pitch * (n - 1)
        base0 = y + block / 2.0 - cap / 2.0
    ang = math.radians(rot or 0)
    c, s = math.cos(ang), math.sin(ang)
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
        # Offsets are along and across the text line, so rotated text keeps its anchor.
        lx = x + c * ox - s * oy
        ly = y + s * ox + c * oy
        ops.append(_text_op(lx, ly, line, h, bold, rot or 0, missing, faces))


def _watermark(ops, text, h, cx, cy, angle, missing, faces):
    tw = text_width_mm(text, h, True)
    cap = _cap_mm(h, True)
    ang = math.radians(angle)
    c, s = math.cos(ang), math.sin(ang)
    x = cx - c * (tw / 2.0) + s * (cap / 2.0)
    y = cy - s * (tw / 2.0) - c * (cap / 2.0)
    ops.append('q %.2f g' % WATERMARK_GRAY)
    ops.append(_text_op(x, y, text, h, True, angle, missing, faces))
    ops.append('Q')


def _poly(pts, close, op):
    x, y = pts[0]
    parts = ['%.3f %.3f m' % (x * MM, y * MM)]
    for px, py in pts[1:]:
        parts.append('%.3f %.3f l' % (px * MM, py * MM))
    if close:
        parts.append('h')
    parts.append(op)
    return ' '.join(parts)


def _used_chars(sheets):
    regular, bold = set(), set()
    for sheet in sheets:
        for it in sheet.items:
            if it[0] == 'tx':
                bucket = bold if it[8] else regular
                bucket.update(ch for ch in it[3] if ord(ch) >= 32)
            elif it[0] == 'wm':
                bold.update(ch for ch in it[3] if ord(ch) >= 32)
    return regular, bold


def page_stream(sheet, missing=None, faces=None):
    """Content stream bytes for one sheet. Missing characters are appended to `missing`."""
    if missing is None:
        missing = []
    if faces is None:
        faces = {False: face(False), True: face(True)}
    ops = ['0 g 0 G 1 J 1 j']
    for it in sheet.items:
        if it[0] != 'wm':
            continue
        _, x, y, text, h, ang = it
        _watermark(ops, text, h, x, y, ang, missing, faces)
    ops.append('0 g 0 G')
    for it in sheet.items:
        kind = it[0]
        if kind == 'wm':
            continue
        if kind == 'pl':
            _, pts, sty, closed = it
            width, dash = STY[sty]
            ops.append('%.3f w' % (width * MM))
            # Leaders end on the part. A round cap would read as a dot.
            ops.append('0 J' if sty == 'dim' else '1 J')
            if dash:
                ops.append('[%s] 0 d' % ' '.join('%.3f' % (d * MM) for d in dash))
            else:
                ops.append('[] 0 d')
            if len(pts) >= 2:
                ops.append(_poly(pts, closed, 'S'))
        elif kind == 'tri':
            ops.append('0 g')
            ops.append(_poly(it[1], True, 'f'))
        elif kind == 'tx':
            _, x, y, text, h, ha, va, rot, bold, bg, _layer = it
            if bg and text:
                tw = text_width_mm(text, h, bold)
                cap = _cap_mm(h, bold)
                if ha == 'left':
                    lx = x
                elif ha == 'right':
                    lx = x - tw
                else:
                    lx = x - tw / 2.0
                ops.append('q 1 g %.3f %.3f %.3f %.3f re f Q' % (
                    (lx - 0.4) * MM, (y - 0.3) * MM, (tw + 0.8) * MM, (cap + 0.4) * MM))
            _draw_text(ops, x, y, text, h, ha, va, rot, bold, missing, faces)
    return ('\n'.join(ops) + '\n').encode('ascii'), missing


class _Doc(object):
    def __init__(self):
        self.objs = []

    def add(self, make):
        num = len(self.objs) + 1
        self.objs.append(make(num))
        return num


def _font_objects(doc, loaded, base_name):
    data = loaded.data
    file_id = doc.add(lambda n: _font_file(n, data))
    desc_id = doc.add(lambda n: _descriptor(n, base_name, loaded, file_id))
    uni_id = doc.add(lambda n: _stream(n, loaded.tounicode()))
    cid_id = doc.add(lambda n: _cidfont(n, base_name, loaded, desc_id))
    return doc.add(lambda n: _type0(n, base_name, cid_id, uni_id))


def write_pdf(sheets, path):
    """Write sheets to a PDF file. Returns characters the font could not draw.

    Each face is subset to the glyphs this PDF uses.
    """
    regular_chars, bold_chars = _used_chars(sheets)
    faces = {
        False: face(False).subset(regular_chars),
        True: face(True).subset(bold_chars),
    }
    doc = _Doc()
    regular = _font_objects(doc, faces[False], _subset_tag(regular_chars) + '+DejaVuSans')
    bold = _font_objects(doc, faces[True], _subset_tag(bold_chars) + '+DejaVuSans-Bold')
    missing = []
    page_ids = []
    # Parent id is assigned after the page objects. Reserve it by counting.
    parent = len(doc.objs) + 2 * len(sheets) + 1
    for sh in sheets:
        data, _miss = page_stream(sh, missing, faces)
        cid = doc.add(lambda n, data=data: _stream(n, data))
        w_mm, h_mm = sh.page_size
        pid = doc.add(lambda n, cid=cid, w=w_mm * MM, h=h_mm * MM: _page(
            n, parent, cid, w, h, regular, bold))
        page_ids.append(pid)
    doc.add(lambda n: _pages(n, page_ids))
    doc.add(lambda n, pages=parent: _catalog(n, pages))
    _write_objects(path, doc.objs)
    seen = []
    for char in missing:
        if char not in seen:
            seen.append(char)
    return seen


def _subset_tag(chars):
    """Six capital letters naming a font subset, as the PDF spec asks (same chars, same tag)."""
    import hashlib
    digest = hashlib.sha1(''.join(sorted(set(chars))).encode('utf-8')).digest()
    return ''.join(chr(ord('A') + b % 26) for b in digest[:6])


def _stream(num, data):
    head = ('%d 0 obj\n<< /Length %d >>\nstream\n' % (num, len(data))).encode('ascii')
    return head + data + b'endstream\nendobj\n'


def _font_file(num, data):
    head = ('%d 0 obj\n<< /Length %d /Length1 %d >>\nstream\n' % (num, len(data), len(data))).encode('ascii')
    return head + data + b'\nendstream\nendobj\n'


def _descriptor(num, name, loaded, file_id):
    scale = 1000.0 / loaded.upem
    x0, y0, x1, y1 = loaded.bbox
    box = '%.0f %.0f %.0f %.0f' % (x0 * scale, y0 * scale, x1 * scale, y1 * scale)
    return (
        '%d 0 obj\n<< /Type /FontDescriptor /FontName /%s /Flags 32 '
        '/FontBBox [%s] /ItalicAngle 0 /Ascent %.0f /Descent %.0f /CapHeight %.0f /StemV 80 '
        '/FontFile2 %d 0 R >>\nendobj\n' % (
            num, name, box, loaded.ascent * scale, loaded.descent * scale, loaded.cap * scale, file_id)
    ).encode('ascii')


def _cidfont(num, name, loaded, desc_id):
    return (
        '%d 0 obj\n<< /Type /Font /Subtype /CIDFontType2 /BaseFont /%s '
        '/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> '
        '/FontDescriptor %d 0 R /DW 500 /CIDToGIDMap /Identity /W [%s] >>\nendobj\n' % (
            num, name, desc_id, loaded.width_pdf())
    ).encode('ascii')


def _type0(num, name, cid_id, uni_id):
    return (
        '%d 0 obj\n<< /Type /Font /Subtype /Type0 /BaseFont /%s /Encoding /Identity-H '
        '/DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>\nendobj\n' % (num, name, cid_id, uni_id)
    ).encode('ascii')


def _page(num, parent, content, w, h, regular, bold):
    return (
        '%d 0 obj\n<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] '
        '/Contents %d 0 R /Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>\nendobj\n' % (
            num, parent, w, h, content, regular, bold)
    ).encode('ascii')


def _pages(num, kids):
    refs = ' '.join('%d 0 R' % k for k in kids)
    return ('%d 0 obj\n<< /Type /Pages /Kids [%s] /Count %d >>\nendobj\n' % (num, refs, len(kids))).encode('ascii')


def _catalog(num, pages):
    return ('%d 0 obj\n<< /Type /Catalog /Pages %d 0 R >>\nendobj\n' % (num, pages)).encode('ascii')


def _write_objects(path, objects):
    out = bytearray(b'%PDF-1.4\n')
    offsets = []
    for obj in objects:
        offsets.append(len(out))
        out += obj
    xref_at = len(out)
    n = len(objects) + 1
    xref = ['xref', '0 %d' % n, '0000000000 65535 f ']
    for off in offsets:
        xref.append('%010d 00000 n ' % off)
    trailer = 'trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (n, len(objects), xref_at)
    out += ('\n'.join(xref) + '\n').encode('ascii')
    out += trailer.encode('ascii')
    with open(path, 'wb') as f:
        f.write(out)
