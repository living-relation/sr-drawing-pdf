"""Fast drawing views for an assembly.

The exact hidden-line step (every edge against every face) does not finish on
a large assembly. These views use the fast path that did: tessellate once,
keep a depth buffer, draw only the visible feature edges, and join them.
Hidden edges are never returned. A mesh body's triangle edges are not drawn;
curved parts contribute silhouettes, rims and centre marks.

Centre lines use the sheet centre style. Tangent rims use the thin style.
Sharp edges use the visible weight.
"""
import array
import math
import time

VIEW_LIMIT_S = 120.0
VIEW_NAMES = ('front', 'top', 'right', 'trimetric')

# Toward the camera. A larger dot product is closer.
_TOWARD = {
    'front': (0.0, -1.0, 0.0),
    'top': (0.0, 0.0, 1.0),
    'right': (1.0, 0.0, 0.0),
    'trimetric': (1.0, -1.0, 0.85),
}

_BUF_W = 480
_BUF_H = 360


def _norm(v):
    x, y, z = v
    length = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / length, y / length, z / length)


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _add(a, b, s=1.0):
    return (a[0] + b[0] * s, a[1] + b[1] * s, a[2] + b[2] * s)


def _basis(name):
    toward = _norm(_TOWARD[name])
    hint = (0.0, 0.0, 1.0) if abs(toward[2]) < 0.85 else (0.0, 1.0, 0.0)
    right = _norm(_cross(hint, toward))
    up = _norm(_cross(toward, right))
    return toward, right, up


def build_benchmark_assembly(blocks=320, fasteners=100):
    """A chassis with several hundred parts. No CAD file is written.

    Shared sizes stand in for repeated hardware. Each item is one part.
    """
    parts = [('box', -20.0, -20.0, 0.0, 640.0, 460.0, 8.0)]
    # Corner posts and a back rail. The front stays open so the parts show.
    for x, y in ((0, 0), (592, 0), (0, 412), (592, 412)):
        parts.append(('box', x, y, 8.0, 12.0, 12.0, 36.0))
    parts.append(('box', 12.0, 412.0, 8.0, 580.0, 8.0, 28.0))
    cols, rows = 20, 16
    for i in range(blocks):
        c, r = i % cols, i // cols
        parts.append(('box', 18.0 + c * 29.0, 16.0 + r * 25.0, 8.0, 20.0, 16.0, 10.0 + (i % 5)))
    for i in range(fasteners):
        c, r = i % 20, i // 20
        parts.append(('cyl', 24.0 + c * 29.0, 22.0 + r * 70.0, 8.0, 2.2, 14.0, 2))
    return parts


def part_count(parts):
    return len(parts)


def _box_faces(part):
    _k, x, y, z, sx, sy, sz = part
    p = [
        (x, y, z), (x + sx, y, z), (x + sx, y + sy, z), (x, y + sy, z),
        (x, y, z + sz), (x + sx, y, z + sz), (x + sx, y + sy, z + sz), (x, y + sy, z + sz),
    ]
    # quads, outward
    quads = (
        (0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4),
        (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5),
    )
    edges = ((0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))
    return p, quads, edges


def _cyl_mesh(part, n=12):
    """Occlusion mesh only. Feature lines are computed separately."""
    _k, x, y, z, r, h, axis = part
    rings = []
    for t in (0.0, h):
        ring = []
        for i in range(n):
            a = 2 * math.pi * i / n
            c, s = math.cos(a) * r, math.sin(a) * r
            if axis == 2:
                ring.append((x + c, y + s, z + t))
            elif axis == 0:
                ring.append((x + t, y + c, z + s))
            else:
                ring.append((x + c, y + t, z + s))
        rings.append(ring)
    pts = rings[0] + rings[1]
    tris = []
    for i in range(n):
        j = (i + 1) % n
        tris.append((i, j, n + j))
        tris.append((i, n + j, n + i))
    for i in range(1, n - 1):
        tris.append((0, i + 1, i))
        tris.append((n, n + i, n + i + 1))
    return pts, tris


def _project_point(p, right, up, toward):
    return (_dot(p, right), _dot(p, up), _dot(p, toward))


def _camera_frame(parts, toward, right, up):
    xs, ys, zs = [], [], []
    for part in parts:
        if part[0] == 'box':
            pts, _q, _e = _box_faces(part)
        else:
            pts, _t = _cyl_mesh(part)
        for p in pts:
            u, v, d = _project_point(p, right, up, toward)
            xs.append(u)
            ys.append(v)
            zs.append(d)
    pad = 4.0
    return min(xs) - pad, max(xs) + pad, min(ys) - pad, max(ys) + pad, min(zs), max(zs)


def _paint(z, w, h, u0, v0, d0, u1, v1, d1, u2, v2, d2, scale, origin, shade=None, tone=180):
    x0, y0 = (u0 - origin[0]) * scale, (v0 - origin[1]) * scale
    x1, y1 = (u1 - origin[0]) * scale, (v1 - origin[1]) * scale
    x2, y2 = (u2 - origin[0]) * scale, (v2 - origin[1]) * scale
    minx = int(min(x0, x1, x2))
    maxx = int(max(x0, x1, x2)) + 1
    miny = int(min(y0, y1, y2))
    maxy = int(max(y0, y1, y2)) + 1
    if maxx < 0 or maxy < 0 or minx >= w or miny >= h:
        return
    if minx < 0:
        minx = 0
    if miny < 0:
        miny = 0
    if maxx > w:
        maxx = w
    if maxy > h:
        maxy = h
    area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if -1e-4 < area < 1e-4:
        return
    inv = 1.0 / area
    for py in range(miny, maxy):
        yy = py + 0.5
        row = py * w
        for px in range(minx, maxx):
            xx = px + 0.5
            w0 = ((x1 - xx) * (y2 - yy) - (x2 - xx) * (y1 - yy)) * inv
            if w0 < 0:
                continue
            w1 = ((x2 - xx) * (y0 - yy) - (x0 - xx) * (y2 - yy)) * inv
            if w1 < 0:
                continue
            w2 = 1.0 - w0 - w1
            if w2 < 0:
                continue
            depth = w0 * d0 + w1 * d1 + w2 * d2
            i = row + px
            if depth > z[i]:
                z[i] = depth
                if shade is not None:
                    shade[i] = tone


def _sample_depth(z, w, h, u, v, scale, origin):
    x = int((u - origin[0]) * scale)
    y = int((v - origin[1]) * scale)
    if x < 0 or y < 0 or x >= w or y >= h:
        return None
    return z[y * w + x]


def _edge_runs(z, w, h, a, b, right, up, toward, scale, origin, eps, samples=8):
    pts = []
    vis = []
    for i in range(samples + 1):
        t = i / float(samples)
        p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)
        u, v, d = _project_point(p, right, up, toward)
        buf = _sample_depth(z, w, h, u, v, scale, origin)
        pts.append((u, v))
        vis.append(buf is not None and d >= buf - eps)
    runs = []
    start = None
    for i, ok in enumerate(vis):
        if ok and start is None:
            start = i
        elif not ok and start is not None:
            if i - 1 > start:
                runs.append((pts[start], pts[i - 1]))
            start = None
    if start is not None and samples > start:
        runs.append((pts[start], pts[samples]))
    return runs


def _join(segments):
    """Join collinear pieces that share an end. HQ draws continuous lines."""
    unused = []
    for a, b, style in segments:
        if abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6:
            continue
        unused.append([a, b, style])
    out = []
    used = [False] * len(unused)
    for i, seg in enumerate(unused):
        if used[i]:
            continue
        used[i] = True
        chain = [seg[0], seg[1]]
        style = seg[2]
        grew = True
        while grew:
            grew = False
            for j, other in enumerate(unused):
                if used[j] or other[2] != style:
                    continue
                if _near(chain[-1], other[0]) and _colinear(chain[-2], chain[-1], other[1]):
                    chain.append(other[1])
                    used[j] = True
                    grew = True
                elif _near(chain[-1], other[1]) and _colinear(chain[-2], chain[-1], other[0]):
                    chain.append(other[0])
                    used[j] = True
                    grew = True
                elif _near(chain[0], other[1]) and _colinear(other[0], chain[0], chain[1]):
                    chain.insert(0, other[0])
                    used[j] = True
                    grew = True
                elif _near(chain[0], other[0]) and _colinear(other[1], chain[0], chain[1]):
                    chain.insert(0, other[1])
                    used[j] = True
                    grew = True
        out.append({'kind': 'poly', 'pts': chain, 'style': style})
    return out


def _near(a, b, tol=0.15):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _colinear(a, b, c, tol=0.2):
    dx1, dy1 = b[0] - a[0], b[1] - a[1]
    dx2, dy2 = c[0] - b[0], c[1] - b[1]
    return abs(dx1 * dy2 - dy1 * dx2) <= tol * (abs(dx1) + abs(dy1) + abs(dx2) + abs(dy2) + 1.0)


def project_view(parts, name, mode='hq', buf_w=_BUF_W, buf_h=_BUF_H):
    """One view. mode 'hq' is the fast joined view. mode 'exact' tests every edge against every triangle."""
    if name not in _TOWARD:
        raise ValueError('view must be one of %s' % ', '.join(VIEW_NAMES))
    if mode not in ('hq', 'exact'):
        raise ValueError("mode must be 'hq' or 'exact'")
    toward, right, up = _basis(name)
    if mode == 'exact':
        return _exact_view(parts, toward, right, up)
    u0, u1, v0, v1, _d0, _d1 = _camera_frame(parts, toward, right, up)
    scale = min((buf_w - 2) / max(u1 - u0, 1e-6), (buf_h - 2) / max(v1 - v0, 1e-6))
    origin = (u0, v0)
    eps = 1.2
    z = array.array('f', [-1e30] * (buf_w * buf_h))
    shade = array.array('B', bytes(buf_w * buf_h))
    light = _norm(_add(toward, up, 0.65))
    for part in parts:
        if part[0] == 'box':
            pts, quads, _e = _box_faces(part)
            for q in quads:
                a, b, c, d = (pts[i] for i in q)
                n = _cross(_add(b, a, -1), _add(d, a, -1))
                facing = _dot(n, toward)
                if facing <= 0:
                    continue
                tone = int(70 + 130 * max(0.0, _dot(_norm(n), light)))
                pa, pb, pc, pd = (_project_point(p, right, up, toward) for p in (a, b, c, d))
                _paint(z, buf_w, buf_h, pa[0], pa[1], pa[2], pb[0], pb[1], pb[2], pc[0], pc[1], pc[2], scale, origin, shade, tone)
                _paint(z, buf_w, buf_h, pa[0], pa[1], pa[2], pc[0], pc[1], pc[2], pd[0], pd[1], pd[2], scale, origin, shade, tone)
        else:
            pts, tris = _cyl_mesh(part)
            proj = [_project_point(p, right, up, toward) for p in pts]
            for i, j, k in tris:
                n = _cross(_add(pts[j], pts[i], -1), _add(pts[k], pts[i], -1))
                tone = int(60 + 140 * max(0.0, _dot(_norm(n), light)))
                _paint(z, buf_w, buf_h,
                       proj[i][0], proj[i][1], proj[i][2],
                       proj[j][0], proj[j][1], proj[j][2],
                       proj[k][0], proj[k][1], proj[k][2], scale, origin, shade, tone)
    segments = []
    circles = []
    for part in parts:
        if part[0] == 'box':
            pts, _q, edges = _box_faces(part)
            for i, j in edges:
                for a, b in _edge_runs(z, buf_w, buf_h, pts[i], pts[j], right, up, toward, scale, origin, eps):
                    segments.append((a, b, 'vis'))
        else:
            segments.extend(_cyl_features(part, z, buf_w, buf_h, right, up, toward, scale, origin, eps, circles))
    lines = _join(segments) if mode == 'hq' else [
        {'kind': 'poly', 'pts': [a, b], 'style': style} for a, b, style in segments]
    lines.extend(circles)
    return {
        'name': name, 'lines': lines, 'style_counts': _counts(lines),
        'shade': shade, 'buf': (buf_w, buf_h, origin, scale),
    }


def _counts(lines):
    counts = {}
    for line in lines:
        counts[line['style']] = counts.get(line['style'], 0) + 1
    return counts


def _cyl_features(part, z, w, h, right, up, toward, scale, origin, eps, circles):
    _k, x, y, z0, r, height, axis = part
    axis_v = [(1, 0, 0), (0, 1, 0), (0, 0, 1)][axis]
    base = [x, y, z0]
    top = _add(tuple(base), axis_v, height)
    align = abs(_dot(axis_v, toward))
    segs = []
    if align > 0.92:
        # End view: one circle and a centre mark. No tessellation edges.
        near = tuple(top) if _dot(axis_v, toward) > 0 else tuple(base)
        cu, cv, cd = _project_point(near, right, up, toward)
        buf = _sample_depth(z, w, h, cu, cv, scale, origin)
        if buf is not None and cd >= buf - eps - r:
            circles.append({'kind': 'circle', 'c': (cu, cv), 'r': r, 'style': 'vis'})
            arm = max(2.5, r * 0.85)
            segs.append(((cu - arm, cv), (cu + arm, cv), 'ctr'))
            segs.append(((cu, cv - arm), (cu, cv + arm), 'ctr'))
        return segs
    side = _norm(_cross(axis_v, toward))
    for sign in (1.0, -1.0):
        a = _add(tuple(base), side, sign * r)
        b = _add(tuple(top), side, sign * r)
        for p, q in _edge_runs(z, w, h, a, b, right, up, toward, scale, origin, eps):
            segs.append((p, q, 'vis'))
    # Centreline along the axis when the body is in front.
    mid = _add(tuple(base), axis_v, height * 0.5)
    mu, mv, md = _project_point(mid, right, up, toward)
    buf = _sample_depth(z, w, h, mu, mv, scale, origin)
    if buf is not None and md >= buf - eps - r:
        au = _project_point(tuple(base), right, up, toward)
        bu = _project_point(tuple(top), right, up, toward)
        segs.append(((au[0], au[1]), (bu[0], bu[1]), 'ctr'))
    # Rims are tangent edges: drawn thin, not as a ring of mesh edges.
    ortho = _norm(_cross(side, axis_v))
    for origin_pt in (tuple(base), tuple(top)):
        rim = []
        for i in range(24):
            ang = 2 * math.pi * i / 24
            c, s = math.cos(ang) * r, math.sin(ang) * r
            rim.append((
                origin_pt[0] + side[0] * c + ortho[0] * s,
                origin_pt[1] + side[1] * c + ortho[1] * s,
                origin_pt[2] + side[2] * c + ortho[2] * s,
            ))
        prev = rim[-1]
        for p in rim:
            for a, b in _edge_runs(z, w, h, prev, p, right, up, toward, scale, origin, eps, samples=2):
                segs.append((a, b, 'thin'))
            prev = p
    return segs


def _exact_view(parts, toward, right, up):
    """Slow path: each feature edge is tested against every triangle. For timing only."""
    tris = []
    edges = []
    for part in parts:
        if part[0] != 'box':
            continue
        pts, quads, ed = _box_faces(part)
        for q in quads:
            a, b, c, d = (pts[i] for i in q)
            tris.append((a, b, c))
            tris.append((a, c, d))
        for i, j in ed:
            edges.append((pts[i], pts[j]))
    kept = 0
    for a, b in edges:
        mid = ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)
        md = _dot(mid, toward)
        hidden = False
        mu, mv = _dot(mid, right), _dot(mid, up)
        for t0, t1, t2 in tris:
            if _tri_hides(mu, mv, md, t0, t1, t2, right, up, toward):
                hidden = True
                break
        if not hidden:
            kept += 1
    return {'name': 'exact', 'lines': [], 'kept_edges': kept, 'triangles': len(tris), 'style_counts': {}}


def _tri_hides(u, v, depth, a, b, c, right, up, toward):
    pa, pb, pc = (_project_point(p, right, up, toward) for p in (a, b, c))
    area = (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pc[0] - pa[0]) * (pb[1] - pa[1])
    if -1e-8 < area < 1e-8:
        return False
    w0 = ((pb[0] - u) * (pc[1] - v) - (pc[0] - u) * (pb[1] - v)) / area
    w1 = ((pc[0] - u) * (pa[1] - v) - (pa[0] - u) * (pc[1] - v)) / area
    w2 = 1.0 - w0 - w1
    if w0 < -1e-6 or w1 < -1e-6 or w2 < -1e-6:
        return False
    tri_d = w0 * pa[2] + w1 * pb[2] + w2 * pc[2]
    return tri_d > depth + 0.4


def time_view_set(parts, names=VIEW_NAMES, mode='hq'):
    """Seconds per view, plus the mesh/setup inside the first view. Total is the full set."""
    views = []
    total = 0.0
    for name in names:
        t0 = time.perf_counter()
        view = project_view(parts, name, mode=mode)
        dt = time.perf_counter() - t0
        total += dt
        view['seconds'] = dt
        views.append(view)
    return {'parts': part_count(parts), 'mode': mode, 'views': views, 'total': total, 'limit': VIEW_LIMIT_S}


def render_views_png(parts, path, names=VIEW_NAMES, px=520):
    """Four views on one image. Shading has no mesh edges; lines are drawn on top."""
    tiles = []
    for name in names:
        t0 = time.perf_counter()
        view = project_view(parts, name)
        view['seconds'] = time.perf_counter() - t0
        tiles.append(view)
    # Bounds
    spans = []
    for view in tiles:
        xs, ys = [], []
        for line in view['lines']:
            if line['kind'] == 'circle':
                cx, cy = line['c']
                xs.extend((cx - line['r'], cx + line['r']))
                ys.extend((cy - line['r'], cy + line['r']))
            else:
                for p in line['pts']:
                    xs.append(p[0])
                    ys.append(p[1])
        spans.append((min(xs), max(xs), min(ys), max(ys)) if xs else (0, 1, 0, 1))
    gap = 16
    w, h = px * 2 + gap * 3, px * 2 + gap * 3
    rgb = bytearray([248]) * (w * h * 3)
    # Third angle: top above front, right beside front. Trimetric sits upper right.
    slots = {
        'top': (gap, gap),
        'trimetric': (px + gap * 2, gap),
        'front': (gap, px + gap * 2),
        'right': (px + gap * 2, px + gap * 2),
    }
    for view, span in zip(tiles, spans):
        ox, oy = slots[view['name']]
        _blit_view(rgb, w, h, ox, oy, px, view, span)
    _write_png(path, w, h, rgb)
    return tiles


def _blit_view(rgb, w, h, ox, oy, px, view, span):
    u0, u1, v0, v1 = span
    scale = (px - 8) / max(u1 - u0, v1 - v0, 1e-6)
    shade, (bw, bh, origin, bscale) = view.get('shade'), view.get('buf', (0, 0, (0, 0), 1))
    if shade is not None and bw:
        for sy in range(bh):
            for sx in range(bw):
                tone = shade[sy * bw + sx]
                if not tone:
                    continue
                u = origin[0] + (sx + 0.5) / bscale
                v = origin[1] + (sy + 0.5) / bscale
                x = int(ox + 4 + (u - u0) * scale)
                y = int(oy + px - 4 - (v - v0) * scale)
                if 0 <= x < w and 0 <= y < h:
                    i = (y * w + x) * 3
                    rgb[i:i + 3] = bytes((tone, tone, tone))
    def pix(p):
        return (int(ox + 4 + (p[0] - u0) * scale), int(oy + px - 4 - (p[1] - v0) * scale))
    for line in view['lines']:
        shade = {'vis': (20, 20, 20), 'thin': (90, 90, 90), 'ctr': (40, 90, 140)}.get(line['style'], (0, 0, 0))
        width = 2 if line['style'] == 'vis' else 1
        if line['kind'] == 'circle':
            cx, cy = pix(line['c'])
            rad = max(1, int(line['r'] * scale))
            _circle(rgb, w, h, cx, cy, rad, shade, width)
            continue
        pts = [pix(p) for p in line['pts']]
        dash = line['style'] == 'ctr'
        for a, b in zip(pts, pts[1:]):
            _line(rgb, w, h, a, b, shade, width, dash)


def _line(rgb, w, h, a, b, color, width, dash):
    x0, y0 = a
    x1, y1 = b
    dx, dy = abs(x1 - x0), abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx - dy
    step = 0
    while True:
        if not dash or (step // 6) % 2 == 0:
            _dot_px(rgb, w, h, x0, y0, color, width)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
        step += 1


def _circle(rgb, w, h, cx, cy, rad, color, width):
    n = max(24, rad)
    prev = None
    for i in range(n + 1):
        a = 2 * math.pi * i / n
        p = (int(cx + rad * math.cos(a)), int(cy + rad * math.sin(a)))
        if prev:
            _line(rgb, w, h, prev, p, color, width, False)
        prev = p


def _dot_px(rgb, w, h, x, y, color, width):
    for dy in range(-(width // 2), width // 2 + 1):
        yy = y + dy
        if yy < 0 or yy >= h:
            continue
        row = yy * w
        for dx in range(-(width // 2), width // 2 + 1):
            xx = x + dx
            if 0 <= xx < w:
                i = (row + xx) * 3
                rgb[i:i + 3] = bytes(color)


def _write_png(path, w, h, rgb):
    import struct
    import zlib
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)
        raw.extend(rgb[y * stride:(y + 1) * stride])

    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
    ihdr = struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)
    png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', ihdr) + chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + chunk(b'IEND', b'')
    with open(path, 'wb') as handle:
        handle.write(png)
