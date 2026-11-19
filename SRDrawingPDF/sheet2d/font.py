"""DejaVu Sans, embedded in the PDF. Metrics come from the font file."""
import os
import struct

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
_FACES = {}


def _tables(data):
    count = struct.unpack('>H', data[4:6])[0]
    out = {}
    for i in range(count):
        tag, _sum, offset, length = struct.unpack('>4sIII', data[12 + i * 16:28 + i * 16])
        out[tag] = data[offset:offset + length]
    return out


def _cmap(table):
    _version, ntables = struct.unpack('>HH', table[:4])
    chosen = None
    for i in range(ntables):
        platform, encoding, offset = struct.unpack('>HHI', table[4 + i * 8:12 + i * 8])
        fmt = struct.unpack('>H', table[offset:offset + 2])[0]
        # Windows Unicode BMP (format 4) or full repertoire (format 12).
        if (platform, encoding, fmt) in ((3, 1, 4), (0, 3, 4), (3, 10, 12), (0, 4, 12)):
            rank = 2 if fmt == 12 else 1
            if chosen is None or rank > chosen[0]:
                chosen = (rank, fmt, offset)
    if chosen is None:
        raise ValueError('DejaVu font has no Unicode cmap')
    _rank, fmt, offset = chosen
    if fmt == 12:
        return _cmap12(table, offset)
    return _cmap4(table, offset)


def _cmap4(table, offset):
    seg_x2 = struct.unpack('>H', table[offset + 6:offset + 8])[0]
    seg = seg_x2 // 2
    end_at = offset + 14
    ends = struct.unpack('>%dH' % seg, table[end_at:end_at + 2 * seg])
    start_at = end_at + 2 * seg + 2
    starts = struct.unpack('>%dH' % seg, table[start_at:start_at + 2 * seg])
    delta_at = start_at + 2 * seg
    deltas = struct.unpack('>%dh' % seg, table[delta_at:delta_at + 2 * seg])
    range_at = delta_at + 2 * seg
    ranges = struct.unpack('>%dH' % seg, table[range_at:range_at + 2 * seg])
    mapping = {}
    for i in range(seg):
        start, end = starts[i], ends[i]
        if start == 0xFFFF:
            break
        for code in range(start, end + 1):
            if ranges[i] == 0:
                gid = (code + deltas[i]) & 0xFFFF
            else:
                pos = range_at + 2 * i + ranges[i] + 2 * (code - start)
                gid = struct.unpack('>H', table[pos:pos + 2])[0]
                if gid:
                    gid = (gid + deltas[i]) & 0xFFFF
            if gid:
                mapping[code] = gid
    return mapping


def _cmap12(table, offset):
    ngroups = struct.unpack('>I', table[offset + 12:offset + 16])[0]
    mapping = {}
    pos = offset + 16
    for _i in range(ngroups):
        start, end, glyph = struct.unpack('>III', table[pos:pos + 12])
        pos += 12
        for code in range(start, end + 1):
            mapping[code] = glyph + (code - start)
    return mapping


class Face(object):
    def __init__(self, path=None, data=None):
        if data is None:
            data = open(path, 'rb').read()
        self._load(data)

    def _load(self, data):
        self.data = data
        self._widths = None
        self._tounicode = None
        tables = _tables(self.data)
        head = tables[b'head']
        self.upem = struct.unpack('>H', head[18:20])[0]
        self.bbox = struct.unpack('>hhhh', head[36:44])
        hhea = tables[b'hhea']
        self.ascent, self.descent = struct.unpack('>hh', hhea[4:8])
        nmetrics = struct.unpack('>H', hhea[34:36])[0]
        maxp = tables[b'maxp']
        nglyphs = struct.unpack('>H', maxp[4:6])[0]
        hmtx = tables[b'hmtx']
        advances = []
        lsbs = []
        for i in range(nmetrics):
            adv, lsb = struct.unpack('>Hh', hmtx[i * 4:i * 4 + 4])
            advances.append(adv)
            lsbs.append(lsb)
        extra = hmtx[nmetrics * 4:]
        last = advances[-1] if advances else 0
        for i in range(nglyphs - nmetrics):
            advances.append(last)
            lsbs.append(struct.unpack('>h', extra[i * 2:i * 2 + 2])[0] if len(extra) >= (i + 1) * 2 else 0)
        self.advances = advances
        self.lsbs = lsbs
        self.glyph_blobs = _glyph_blobs(tables, head, nglyphs)
        self._src_tables = tables
        os2 = tables.get(b'OS/2')
        cap = None
        if os2 and len(os2) >= 90 and struct.unpack('>H', os2[:2])[0] >= 2:
            cap = struct.unpack('>h', os2[88:90])[0]
        self.cap = cap or int(self.upem * 0.72)
        self.cmap = _cmap(tables[b'cmap'])

    def glyph_id(self, char):
        return self.cmap.get(ord(char), 0)

    def has(self, char):
        return ord(char) in self.cmap

    def width_mm(self, text, h_mm):
        total = 0
        for char in text:
            total += self.advances[self.glyph_id(char)]
        return total * float(h_mm) / float(self.cap)

    def glyphs(self, text):
        ids = []
        missing = []
        for char in text:
            gid = self.glyph_id(char)
            if gid == 0 and char != '\x00':
                if ord(char) not in self.cmap:
                    missing.append(char)
            ids.append(gid)
        return ids, missing

    def width_pdf(self):
        """CID width array in 1000-em units. Cached."""
        if self._widths is None:
            scale = 1000.0 / self.upem
            parts = []
            gid = 0
            chunk = 64
            while gid < len(self.advances):
                nums = [str(int(round(a * scale))) for a in self.advances[gid:gid + chunk]]
                parts.append('%d [%s]' % (gid, ' '.join(nums)))
                gid += chunk
            self._widths = ' '.join(parts)
        return self._widths

    def tounicode(self):
        if self._tounicode is None:
            lines = [
                '/CIDInit /ProcSet findresource begin',
                '12 dict begin',
                'begincmap',
                '/CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> def',
                '/CMapName /DejaVu-UTF16 def',
                '/CMapType 2 def',
                '1 begincodespacerange',
                '<0000> <FFFF>',
                'endcodespacerange',
            ]
            pairs = []
            for code, gid in sorted(self.cmap.items()):
                if gid <= 0 or gid > 0xFFFF or code > 0x10FFFF:
                    continue
                if code > 0xFFFF:
                    high = 0xD800 + ((code - 0x10000) >> 10)
                    low = 0xDC00 + ((code - 0x10000) & 0x3FF)
                    uni = '%04X%04X' % (high, low)
                else:
                    uni = '%04X' % code
                pairs.append('<%04X> <%s>' % (gid, uni))
            for i in range(0, len(pairs), 100):
                block = pairs[i:i + 100]
                lines.append('%d beginbfchar' % len(block))
                lines.extend(block)
                lines.append('endbfchar')
            lines.extend(['endcmap', 'CMapName currentdict /CMap defineresource pop', 'end', 'end'])
            self._tounicode = ('\n'.join(lines) + '\n').encode('ascii')
        return self._tounicode

    def subset(self, chars):
        """A new face whose font program contains only these characters (plus .notdef)."""
        wanted = {0}
        keep_chars = []
        for char in chars:
            code = ord(char)
            if code < 32 or code > 0xFFFF:
                continue
            gid = self.cmap.get(code, 0)
            if not gid:
                continue
            wanted.add(gid)
            keep_chars.append(code)
        pending = list(wanted)
        while pending:
            gid = pending.pop()
            for comp in _components(self.glyph_blobs[gid] if gid < len(self.glyph_blobs) else b''):
                if comp not in wanted and comp < len(self.glyph_blobs):
                    wanted.add(comp)
                    pending.append(comp)
        order = [0] + sorted(g for g in wanted if g)
        gid_map = {old: new for new, old in enumerate(order)}
        blobs = []
        for old in order:
            blob = self.glyph_blobs[old] if old < len(self.glyph_blobs) else b''
            blobs.append(_remap_components(blob, gid_map))
        char_map = {}
        for code in keep_chars:
            char_map[code] = gid_map[self.cmap[code]]
        data = _build_ttf(self, blobs, order, char_map)
        return Face(data=data)


def _glyph_blobs(tables, head, nglyphs):
    loca = tables[b'loca']
    glyf = tables[b'glyf']
    fmt = struct.unpack('>h', head[50:52])[0]
    offsets = []
    if fmt == 0:
        count = nglyphs + 1
        for i in range(count):
            offsets.append(struct.unpack('>H', loca[i * 2:i * 2 + 2])[0] * 2)
    else:
        count = nglyphs + 1
        for i in range(count):
            offsets.append(struct.unpack('>I', loca[i * 4:i * 4 + 4])[0])
    blobs = []
    for i in range(nglyphs):
        blobs.append(glyf[offsets[i]:offsets[i + 1]])
    return blobs


def _components(blob):
    if len(blob) < 10:
        return []
    contours = struct.unpack('>h', blob[:2])[0]
    if contours >= 0:
        return []
    found = []
    pos = 10
    while pos + 4 <= len(blob):
        flags, gid = struct.unpack('>HH', blob[pos:pos + 4])
        found.append(gid)
        pos += 4
        pos += 4 if flags & 1 else 2
        if flags & 8:
            pos += 2
        elif flags & 64:
            pos += 4
        elif flags & 128:
            pos += 8
        if not (flags & 32):
            break
    return found


def _remap_components(blob, gid_map):
    if len(blob) < 10 or struct.unpack('>h', blob[:2])[0] >= 0:
        return blob
    out = bytearray(blob)
    pos = 10
    while pos + 4 <= len(out):
        flags, gid = struct.unpack('>HH', out[pos:pos + 4])
        struct.pack_into('>H', out, pos + 2, gid_map.get(gid, 0))
        pos += 4
        pos += 4 if flags & 1 else 2
        if flags & 8:
            pos += 2
        elif flags & 64:
            pos += 4
        elif flags & 128:
            pos += 8
        if not (flags & 32):
            break
    return bytes(out)


def _checksum(data):
    padded = data + b'\x00' * ((4 - len(data) % 4) % 4)
    total = 0
    for i in range(0, len(padded), 4):
        total = (total + struct.unpack('>I', padded[i:i + 4])[0]) & 0xFFFFFFFF
    return total


def _encode_cmap4(char_map):
    """Format 4 cmap. char_map is unicode code -> new glyph id."""
    codes = sorted(c for c in char_map if c <= 0xFFFF)
    segments = [(code, code, char_map[code]) for code in codes]
    segments.append((0xFFFF, 0xFFFF, 0))
    seg = len(segments)
    entry = 0
    while (1 << (entry + 1)) <= seg:
        entry += 1
    search = (1 << entry) * 2
    body = struct.pack(
        '>HHHHHHH', 4, 16 + 8 * seg, 0, seg * 2, search, entry, seg * 2 - search)
    body += struct.pack('>%dH' % seg, *[end for _start, end, _gid in segments])
    body += struct.pack('>H', 0)
    body += struct.pack('>%dH' % seg, *[start for start, _end, _gid in segments])
    deltas = []
    for start, _end, gid in segments:
        delta = (gid - start) & 0xFFFF
        if delta >= 0x8000:
            delta -= 0x10000
        deltas.append(delta)
    body += struct.pack('>%dh' % seg, *deltas)
    body += struct.pack('>%dH' % seg, *([0] * seg))
    table = struct.pack('>HH', 0, 1) + struct.pack('>HHI', 3, 1, 12) + body
    return table


def _minimal_post(src):
    # Format 3 drops the glyph-name list. Keep the metrics from the source header.
    if src and len(src) >= 32:
        head = bytearray(src[:32])
        struct.pack_into('>I', head, 0, 0x00030000)
        return bytes(head)
    return struct.pack('>I', 0x00030000) + b'\x00' * 28


def _build_ttf(src, blobs, order, char_map):
    glyf = bytearray()
    offsets = [0]
    for blob in blobs:
        glyf += blob
        if len(glyf) % 2:
            glyf += b'\x00'
        offsets.append(len(glyf))
    loca = b''.join(struct.pack('>I', off) for off in offsets)
    hmtx = b''.join(
        struct.pack('>Hh', src.advances[old] if old < len(src.advances) else 0,
                    src.lsbs[old] if old < len(src.lsbs) else 0)
        for old in order)
    maxp = bytearray(src._src_tables[b'maxp'])
    struct.pack_into('>H', maxp, 4, len(order))
    hhea = bytearray(src._src_tables[b'hhea'])
    struct.pack_into('>H', hhea, 34, len(order))
    head = bytearray(src._src_tables[b'head'])
    struct.pack_into('>I', head, 8, 0)  # checksumAdjustment
    struct.pack_into('>h', head, 50, 1)  # long loca
    tables = {
        b'cmap': _encode_cmap4(char_map),
        b'glyf': bytes(glyf),
        b'head': bytes(head),
        b'hhea': bytes(hhea),
        b'hmtx': hmtx,
        b'loca': loca,
        b'maxp': bytes(maxp),
        b'name': src._src_tables[b'name'],
        b'post': _minimal_post(src._src_tables.get(b'post', b'')),
    }
    if b'OS/2' in src._src_tables:
        tables[b'OS/2'] = src._src_tables[b'OS/2']
    return _pack_sfnt(tables)


def _pack_sfnt(tables):
    tags = sorted(tables)
    n = len(tags)
    entry = 0
    while (1 << (entry + 1)) <= n:
        entry += 1
    search = (1 << entry) * 16
    header = struct.pack('>IHHHH', 0x00010000, n, search, entry, n * 16 - search)
    directory = bytearray(n * 16)
    offset = 12 + n * 16
    blobs = []
    for i, tag in enumerate(tags):
        data = tables[tag]
        struct.pack_into('>4sIII', directory, i * 16, tag, _checksum(data), offset, len(data))
        blobs.append(data)
        offset += len(data)
        pad = (4 - len(data) % 4) % 4
        blobs.append(b'\x00' * pad)
        offset += pad
    font = header + bytes(directory) + b''.join(blobs)
    # checksumAdjustment makes the font sum to 0xB1B0AFBA. The directory still
    # records the head checksum from before this write; viewers do not require it.
    head_at = struct.unpack('>I', directory[tags.index(b'head') * 16 + 8:tags.index(b'head') * 16 + 12])[0]
    adjust = (0xB1B0AFBA - _checksum(font)) & 0xFFFFFFFF
    font = bytearray(font)
    struct.pack_into('>I', font, head_at + 8, adjust)
    return bytes(font)


def face(bold=False):
    key = 'bold' if bold else 'regular'
    if key not in _FACES:
        name = 'DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'
        _FACES[key] = Face(os.path.join(_DIR, name))
    return _FACES[key]


def text_width_mm(text, h_mm, bold=False):
    return face(bold).width_mm(str(text), h_mm)


def cap_ratio(bold=False):
    loaded = face(bold)
    return float(loaded.cap) / float(loaded.upem)
