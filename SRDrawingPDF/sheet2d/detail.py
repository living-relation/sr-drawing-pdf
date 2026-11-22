"""Detail views, set up the way the SOLIDWORKS Detail View PropertyManager does.

The engine never adds a detail view on its own. The engineer adds one with
add_detail_view, or accepts a suggestion (suggest.py). Options follow the
SOLIDWORKS Detail View PropertyManager:

  Detail Circle   boundary: circle or profile; style: per_standard,
                  broken_circle (circle only), with_leader, no_leader,
                  connected; label (letter)
  Detail View     outline: none, full, jagged (+ jagged_intensity 1-5);
                  pin_position; scale_hatch
  Scale           scale_mode: sheet, parent, custom (+ scale)

Reference: SOLIDWORKS Help, "Detail View PropertyManager" and
"Detail Circle Styles".
"""
import math

DETAIL_STYLES = ('per_standard', 'broken_circle', 'with_leader', 'no_leader', 'connected')
DETAIL_OUTLINES = ('none', 'full', 'jagged')
DETAIL_BOUNDARIES = ('circle', 'profile')
SCALE_MODES = ('sheet', 'parent', 'custom')
SKIP_LETTERS = set('IOQ')


def next_letter(used):
    """Next free view letter, A..Z then AA.., skipping I, O and Q."""
    used = {str(u).upper() for u in used if u}
    n = 0
    while True:
        n += 1
        k, s = n, ''
        while k:
            k, r = divmod(k - 1, 26)
            s = chr(65 + r) + s
        if not (set(s) & SKIP_LETTERS) and s not in used:
            return s


def _ratio_text(v):
    """0.5 -> '1:2', 2 -> '2:1', 1.5 -> '3:2'."""
    from fractions import Fraction
    f = Fraction(v).limit_denominator(100)
    return '%d:%d' % (f.numerator, f.denominator)


def resolve_scale(detail, parent_scale, sheet_scale):
    """The scale text a detail view uses, from its scale_mode."""
    from .annotate import scale_value
    mode = detail.get('scale_mode') or 'custom'
    if mode == 'sheet':
        return sheet_scale or None
    if mode == 'parent':
        return parent_scale or sheet_scale or None
    if detail.get('scale'):
        return detail['scale']
    base = scale_value(parent_scale or sheet_scale) or 1.0
    return _ratio_text(base * 2.0)


def normalize_detail(args, current=None):
    d = dict(current or {})
    for key, allowed in (('style', DETAIL_STYLES), ('outline', DETAIL_OUTLINES),
                         ('boundary', DETAIL_BOUNDARIES), ('scale_mode', SCALE_MODES)):
        if key in args and args[key] is not None:
            if args[key] not in allowed:
                raise ValueError('%s must be one of %s' % (key, ', '.join(allowed)))
            d[key] = args[key]
    d.setdefault('style', 'per_standard')
    d.setdefault('outline', 'full')
    d.setdefault('boundary', 'circle')
    d.setdefault('scale_mode', 'custom')
    for key in ('cx', 'cy', 'r'):
        if key in args and args[key] is not None:
            d[key] = float(args[key])
    if 'points' in args and args['points'] is not None:
        d['points'] = [[float(p[0]), float(p[1])] for p in args['points']]
    if 'scale' in args:
        d['scale'] = args['scale'] or None
    if 'jagged_intensity' in args and args['jagged_intensity'] is not None:
        v = int(args['jagged_intensity'])
        if not 1 <= v <= 5:
            raise ValueError('jagged_intensity must be 1 to 5')
        d['jagged_intensity'] = v
    d.setdefault('jagged_intensity', 3)
    for key in ('pin_position', 'scale_hatch'):
        if key in args and args[key] is not None:
            d[key] = bool(args[key])
        d.setdefault(key, False)
    for key in ('label_x', 'label_y'):
        if key in args and args[key] is not None:
            d[key] = float(args[key])
    if d['boundary'] == 'circle':
        if not all(k in d for k in ('cx', 'cy', 'r')) or d['r'] <= 0:
            raise ValueError('a circle detail needs cx, cy and r > 0 (sheet mm on the parent view)')
    else:
        if len(d.get('points') or []) < 3:
            raise ValueError('a profile detail needs 3 or more points')
        if d['style'] == 'broken_circle':
            raise ValueError('broken_circle is not available for a profile (SOLIDWORKS: Circle only)')
    if d['scale_mode'] == 'custom' and d.get('scale'):
        from .annotate import scale_value
        if scale_value(d['scale']) is None:
            raise ValueError('scale must be a ratio like 2:1')
    return d


def boundary_center(d):
    if d['boundary'] == 'circle':
        return d['cx'], d['cy'], d['r']
    pts = d['points']
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    r = max(math.hypot(p[0] - cx, p[1] - cy) for p in pts)
    return cx, cy, r


def _arc(cx, cy, r, a0, a1, n=40):
    return [(cx + r * math.cos(a0 + (a1 - a0) * i / n), cy + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def draw_detail_mark(sh, d, letter, frame=None):
    """The detail circle (or profile) and its letter on the parent view."""
    cx, cy, r = boundary_center(d)
    style = d.get('style') or 'per_standard'
    h = 3.4
    if d['boundary'] == 'profile':
        sh.pl([tuple(p) for p in d['points']], 'detail', closed=True)
    elif style == 'broken_circle':
        gap = math.radians(28)
        mid = math.radians(45)
        sh.pl(_arc(cx, cy, r, mid + gap / 2, mid + 2 * math.pi - gap / 2), 'detail')
    else:
        sh.pl(_arc(cx, cy, r, 0, 2 * math.pi, 64), 'detail', closed=True)
    ang = math.radians(45)
    edge = (cx + r * math.cos(ang), cy + r * math.sin(ang))
    if style == 'broken_circle' and d['boundary'] == 'circle':
        sh.txt(edge[0], edge[1], letter, h=h, bold=True)
        return
    if style in ('with_leader', 'per_standard'):
        lx = d.get('label_x', cx + (r + 8) * math.cos(ang))
        ly = d.get('label_y', cy + (r + 8) * math.sin(ang))
        sh.line(edge, (lx - 1.5, ly - 1.5), 'thin')
        sh.txt(lx, ly, letter, h=h, bold=True)
    elif style == 'no_leader':
        sh.txt(d.get('label_x', edge[0] + 2.5), d.get('label_y', edge[1] + 2.5), letter, h=h, bold=True)
    elif style == 'connected':
        sh.txt(d.get('label_x', edge[0] + 2.5), d.get('label_y', edge[1] + 2.5), letter, h=h, bold=True)
        if frame is not None:
            fx = min(max(cx, frame['x']), frame['x'] + frame['w'])
            fy = min(max(cy, frame['y']), frame['y'] + frame['h'])
            vx, vy = fx - cx, fy - cy
            dist = math.hypot(vx, vy)
            if dist > r:
                sh.line((cx + vx / dist * r, cy + vy / dist * r), (fx, fy), 'thin')


def draw_detail_outline(sh, d, frame, ratio):
    """Outline drawn around the enlarged area inside the detail view frame."""
    outline = d.get('outline') or 'full'
    if outline == 'none':
        return
    fx = frame['x'] + frame['w'] / 2
    fy = frame['y'] + frame['h'] / 2
    cx, cy, r = boundary_center(d)
    R = min(r * ratio, frame['w'] / 2 - 1, frame['h'] / 2 - 1)
    if d['boundary'] == 'profile':
        k = R / r if r else 1.0
        pts = [(fx + (p[0] - cx) * k, fy + (p[1] - cy) * k) for p in d['points']]
    else:
        pts = _arc(fx, fy, R, 0, 2 * math.pi, 72)
    if outline == 'jagged':
        amp = 0.35 * int(d.get('jagged_intensity') or 3)
        out = []
        for i, (x, y) in enumerate(pts):
            vx, vy = x - fx, y - fy
            dist = math.hypot(vx, vy) or 1.0
            k = amp * (1 if i % 2 else -1) * (0.6 + 0.4 * ((i * 7919) % 5) / 4.0)
            out.append((x + vx / dist * k, y + vy / dist * k))
        pts = out
    sh.pl(pts, 'thin', closed=True)
