"""Real views from Fusion meshes: edge finding, the dump format, one-scale layout, and the sheet."""
import json
import math
import os
import struct

import pytest

from sheet2d.meshparts import load_fusion_dump, mesh_features, place
from sheet2d.scene import build_scene
from sheet2d.viewsheet import STD_SCALES, build_view_sheet, clear_view_geometry, layout

IDENT = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


def _fusion_box(sx, sy, sz):
    """A box meshed the way Fusion does it: each face has its own four nodes."""
    c = [(x, y, z) for x in (0.0, sx) for y in (0.0, sy) for z in (0.0, sz)]
    faces = ((0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5))
    pts, tris = [], []
    for a, b, cc, d in faces:
        n = len(pts)
        pts += [c[a], c[b], c[cc], c[d]]
        tris += [(n, n + 1, n + 2), (n, n + 2, n + 3)]
    return pts, tris


def _fusion_cylinder(r, h, n=24):
    """Side face with shared nodes (one face), caps with their own nodes."""
    ring = [(r * math.cos(2 * math.pi * i / n), r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    pts = [(x, y, 0.0) for x, y in ring] + [(x, y, h) for x, y in ring]
    tris = []
    for i in range(n):
        j = (i + 1) % n
        tris += [(i, j, n + j), (i, n + j, n + i)]
    for z, flip in ((0.0, True), (h, False)):
        base = len(pts)
        pts += [(x, y, z) for x, y in ring]
        for i in range(1, n - 1):
            tris.append((base, base + i + 1, base + i) if flip else (base, base + i, base + i + 1))
    return pts, tris


def test_box_draws_only_its_twelve_edges():
    edges, smooth = mesh_features(*_fusion_box(10, 20, 30))
    assert len(edges) == 12
    assert all(style == 'vis' for _poly, style in edges)
    assert smooth == []  # face diagonals are never drawn


def test_cylinder_keeps_rims_and_silhouette_edges():
    edges, smooth = mesh_features(*_fusion_cylinder(5.0, 10.0))
    assert len(edges) == 48 and all(style == 'vis' for _p, style in edges)  # two rims
    assert len(smooth) == 24  # side seams, for silhouettes
    # cap triangles are flat: none of their inner edges is drawn or kept
    assert all(abs(a[2] - b[2]) > 1.0 for a, b, _n1, _n2 in smooth)


def _write_dump(folder, bodies, placements, units='cm'):
    with open(os.path.join(folder, 'occurrences.json'), 'w', encoding='utf-8') as handle:
        json.dump({'document': 'Test Assy', 'units': units,
                   'bodies': [{'key': k, 'comp': 'c', 'body': 0, 'name': k} for k in bodies],
                   'placements': placements}, handle)
    with open(os.path.join(folder, 'mesh_00000.bin'), 'wb') as handle:
        for key, (pts, tris) in bodies.items():
            k = key.encode('utf-8')
            flat = [v for p in pts for v in p]
            idx = [i for t in tris for i in t]
            handle.write(struct.pack('<I', len(k)) + k + struct.pack('<II', len(flat), len(idx)))
            handle.write(struct.pack('<%df' % len(flat), *flat))
            handle.write(struct.pack('<%di' % len(idx), *idx))


def test_dump_reuses_one_mesh_for_each_placement(tmp_path):
    moved = list(IDENT)
    moved[3] = 5.0  # 5 cm along x
    _write_dump(str(tmp_path), {'box#0': _fusion_box(1, 2, 3)}, [
        {'key': 'box#0', 'occ': 'a:1', 'xf': IDENT},
        {'key': 'box#0', 'occ': 'a:2', 'xf': moved},
        {'key': 'gone#0', 'occ': 'b:1', 'xf': IDENT},
    ])
    parts, info = load_fusion_dump(str(tmp_path))
    assert info['document'] == 'Test Assy'
    assert info['unique_bodies'] == 1 and info['placements'] == 3 and info['missing'] == 1
    assert len(parts) == 2
    xs0 = [p[0] for p in parts[0][1]]
    xs1 = [p[0] for p in parts[1][1]]
    assert max(xs0) == pytest.approx(10.0)  # cm to mm
    assert min(xs1) == pytest.approx(50.0) and max(xs1) == pytest.approx(60.0)


def test_place_rotates_normals_without_scaling_them():
    rot = [0.0, -1.0, 0, 0, 1.0, 0.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]  # 90 deg about z
    pts, tris = _fusion_cylinder(1.0, 1.0, n=8)
    edges, smooth = mesh_features(pts, tris)
    part = place((pts, tris, edges, smooth), rot, 10.0)
    for _a, _b, n1, _n2 in part[4]:
        assert math.sqrt(sum(v * v for v in n1)) == pytest.approx(1.0)


def test_layout_one_scale_and_third_angle_alignment():
    ext = {'front': (0, 400, 0, 200), 'top': (0, 400, 0, 150), 'right': (0, 150, 0, 200),
           'trimetric': (0, 300, 0, 250)}
    plan = layout(ext, (253.8, 240.0, 421.8, 263.8))
    f, t, r = plan['frames']['front'], plan['frames']['top'], plan['frames']['right']
    assert plan['label'] in [label for _s, label in STD_SCALES]
    assert t[0] == f[0] and t[2] == f[2]  # top above front, same width
    assert t[1] > f[1] + f[3]
    assert r[1] == f[1] and r[3] == f[3]  # right beside front, same height
    assert r[0] > f[0] + f[2]
    # the next bigger standard scale would not fit
    bigger = [s for s, _l in STD_SCALES if s > plan['scale']]
    if bigger:
        s = min(bigger)
        assert 400 * s + 16 + 150 * s > 399.8 - 16 or 200 * s + 16 + 150 * s > 263.4 - 67
    tri = plan['trimetric']
    assert tri['scale'] <= plan['scale']
    assert tri['frame'][0] >= r[0] - 1e-9


def test_layout_refuses_when_nothing_fits():
    big = (0, 1e6, 0, 1e6)
    with pytest.raises(ValueError):
        layout({'front': big, 'top': big, 'right': big, 'trimetric': big}, (253.8, 240.0, 421.8, 263.8))


def test_sheet_with_real_views_draws_lines_in_the_editor(tmp_path):
    pts, tris = _fusion_box(120, 60, 40)
    edges, smooth = mesh_features(pts, tris)
    parts = [place((pts, tris, edges, smooth), IDENT)]
    doc, report = build_view_sheet(parts, 'Box Test', key='t-box', source='Fusion')
    views = [el for s in doc['sheets'] for el in s['elements'] if el.get('type') == 'view']
    assert sorted(v['label'] for v in views) == ['FRONT', 'RIGHT', 'TOP', 'TRIMETRIC']
    assert all(v.get('geom') for v in views)
    assert report['scale'] and len(report['views']) == 4
    with_lines = build_scene(doc)['svg'].count(' L ')
    clear_view_geometry('t-box')
    frames_only = build_scene(doc)['svg'].count(' L ')
    assert with_lines >= frames_only + 10  # the box outlines are drawn, not empty frames
    from sheet2d.model import DrawingDocument
    from sheet2d.render import export_pdf
    out = tmp_path / 'box.pdf'
    export_pdf(DrawingDocument.from_dict(doc), str(out))
    assert out.stat().st_size > 1000
