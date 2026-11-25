"""Mesh parts: what a real assembly (STEP or Fusion bodies) turns into."""
import math
import time

from sheet2d.project import _join, project_view


def _mesh_box(x, y, z, sx, sy, sz):
    p = [
        (x, y, z), (x + sx, y, z), (x + sx, y + sy, z), (x, y + sy, z),
        (x, y, z + sz), (x + sx, y, z + sz), (x + sx, y + sy, z + sz), (x, y + sy, z + sz),
    ]
    quads = ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (0, 4, 7, 3), (1, 2, 6, 5))
    tris = []
    for a, b, c, d in quads:
        tris.append((a, b, c))
        tris.append((a, c, d))
    edges = [([p[i], p[j]], 'vis') for i, j in (
        (0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4), (0, 4), (1, 5), (2, 6), (3, 7))]
    return ('mesh', p, tris, edges, [])


def _mesh_cylinder(r, h, n=24):
    """Z axis cylinder. Only the two rims are B-rep edges; the side keeps its inner edges for silhouettes."""
    ring0 = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n), 0.0) for i in range(n)]
    ring1 = [(x, y, h) for x, y, _z in ring0]
    pts = ring0 + ring1
    tris = []
    smooth = []
    for i in range(n):
        j = (i + 1) % n
        tris.append((i, j, n + j))
        tris.append((i, n + j, n + i))
        # inner edge from ring0[j] to ring1[j]; normals of the two side quads that share it
        a0 = 2 * math.pi * (i + 0.5) / n
        a1 = 2 * math.pi * (i + 1.5) / n
        smooth.append((pts[j], pts[n + j], (math.cos(a0), math.sin(a0), 0.0), (math.cos(a1), math.sin(a1), 0.0)))
    for i in range(1, n - 1):
        tris.append((0, i + 1, i))
        tris.append((n, n + i, n + i + 1))
    edges = [(ring0 + [ring0[0]], 'vis'), (ring1 + [ring1[0]], 'vis')]
    return ('mesh', pts, tris, edges, smooth)


def test_mesh_box_front_shows_its_outline_only():
    view = project_view([_mesh_box(0, 0, 0, 40, 20, 10)], 'front')
    assert 'hid' not in view['style_counts']
    assert view['lines']
    # A box seen square-on is one rectangle: the joined outline is at most four lines.
    assert len(view['lines']) <= 4


def test_a_box_behind_a_wall_is_hidden():
    wall = _mesh_box(-10, -5, -10, 80, 2, 40)
    behind = _mesh_box(20, 10, 0, 10, 10, 10)
    alone = project_view([wall], 'front')
    both = project_view([wall, behind], 'front')
    assert len(both['lines']) == len(alone['lines'])


def test_mesh_cylinder_side_view_has_silhouettes():
    side = project_view([_mesh_cylinder(5.0, 30.0)], 'front')
    xs = [p[0] for line in side['lines'] for p in line['pts']]
    assert min(xs) < -4.5 and max(xs) > 4.5  # both silhouettes at the radius
    assert 'hid' not in side['style_counts']


def test_join_is_fast_on_many_pieces():
    segments = []
    for row in range(200):
        for i in range(100):
            segments.append(((float(i), float(row)), (float(i + 1), float(row)), 'vis'))
    t0 = time.perf_counter()
    lines = _join(segments)
    assert time.perf_counter() - t0 < 5.0
    assert len(lines) == 200
