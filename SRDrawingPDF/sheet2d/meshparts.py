"""Mesh parts for sheet2d.project from triangle meshes (Fusion bodies or any mesher).

A mesh part is ('mesh', points, triangles, edges, smooth):
  edges  - (polyline, style): the body's own edges. 'vis' where the faces meet at an
           angle, 'thin' where they meet tangent (a fillet boundary, for example).
  smooth - (a, b, n1, n2): inner mesh edges of curved faces with the normals on both
           sides, so each view can find its silhouettes.

Fusion meshes a body face by face, so a node on a face boundary is repeated once
per face. That is how the body's edges are found here: an edge whose two
triangles do not share node numbers is a face boundary. Edges inside one face
are never drawn, so a coarse mesh never looks like a mesh.

Pure Python. No Fusion import.
"""
import array
import json
import math
import os
import struct

CREASE_DEG = 20.0
CURVED_DEG = 0.5


def mesh_features(pts, tris, weld=1e-4):
    """(edges, smooth) for one body. pts are (x, y, z) tuples; tris index into pts."""
    q = 1.0 / weld
    weld_id = {}
    wid = []
    for p in pts:
        key = (int(round(p[0] * q)), int(round(p[1] * q)), int(round(p[2] * q)))
        wid.append(weld_id.setdefault(key, len(weld_id)))
    normals = []
    edge_map = {}
    for t, (i, j, k) in enumerate(tris):
        a, b, c = pts[i], pts[j], pts[k]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length <= 0.0:
            normals.append(None)
            continue
        normals.append((nx / length, ny / length, nz / length))
        for s, e in ((i, j), (j, k), (k, i)):
            ws, we = wid[s], wid[e]
            if ws == we:
                continue
            key = (ws, we) if ws < we else (we, ws)
            edge_map.setdefault(key, []).append((t, s, e))
    cos_crease = math.cos(math.radians(CREASE_DEG))
    cos_curved = math.cos(math.radians(CURVED_DEG))
    edges = []
    smooth = []
    for uses in edge_map.values():
        _t0, s, e = uses[0]
        a, b = pts[s], pts[e]
        if len(uses) != 2:
            edges.append(([a, b], 'vis'))  # open or non-manifold edge
            continue
        (t1, s1, e1), (t2, s2, e2) = uses
        n1, n2 = normals[t1], normals[t2]
        cos = n1[0] * n2[0] + n1[1] * n2[1] + n1[2] * n2[2]
        same_face = {s1, e1} == {s2, e2}
        if same_face:
            if cos < cos_curved:
                smooth.append((a, b, n1, n2))
        elif cos < cos_crease:
            edges.append(([a, b], 'vis'))
        else:
            edges.append(([a, b], 'thin'))
            if cos < cos_curved:
                smooth.append((a, b, n1, n2))
    return edges, smooth


def _xf(m, p):
    x, y, z = p
    return (m[0] * x + m[1] * y + m[2] * z + m[3],
            m[4] * x + m[5] * y + m[6] * z + m[7],
            m[8] * x + m[9] * y + m[10] * z + m[11])


def _xv(m, n):
    x, y, z = n
    v = (m[0] * x + m[1] * y + m[2] * z, m[4] * x + m[5] * y + m[6] * z, m[8] * x + m[9] * y + m[10] * z)
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) or 1.0
    return (v[0] / length, v[1] / length, v[2] / length)


def place(body, matrix, scale=1.0):
    """One mesh part: a unique body's mesh and features moved by a 4x4 row-major matrix."""
    pts, tris, edges, smooth = body
    m = list(matrix)
    m = [m[0] * scale, m[1] * scale, m[2] * scale, m[3] * scale,
         m[4] * scale, m[5] * scale, m[6] * scale, m[7] * scale,
         m[8] * scale, m[9] * scale, m[10] * scale, m[11] * scale]
    rot = m[:3] + [0.0] + m[4:7] + [0.0] + m[8:11] + [0.0]
    return ('mesh', [_xf(m, p) for p in pts], tris,
            [([_xf(m, p) for p in poly], style) for poly, style in edges],
            [(_xf(m, a), _xf(m, b), _xv(rot, n1), _xv(rot, n2)) for a, b, n1, n2 in smooth])


def read_meshes(path):
    """{key: (pts, tris)} from one mesh_*.bin written by fusion_read.mesh_step."""
    out = {}
    with open(path, 'rb') as handle:
        data = handle.read()
    pos = 0
    while pos < len(data):
        (klen,) = struct.unpack_from('<I', data, pos)
        pos += 4
        key = data[pos:pos + klen].decode('utf-8')
        pos += klen
        nn, ni = struct.unpack_from('<II', data, pos)
        pos += 8
        nodes = array.array('f')
        nodes.frombytes(data[pos:pos + 4 * nn])
        pos += 4 * nn
        idx = array.array('i')
        idx.frombytes(data[pos:pos + 4 * ni])
        pos += 4 * ni
        pts = [(nodes[i], nodes[i + 1], nodes[i + 2]) for i in range(0, nn, 3)]
        tris = [(idx[i], idx[i + 1], idx[i + 2]) for i in range(0, ni, 3)]
        out[key] = (pts, tris)
    return out


def load_fusion_dump(folder):
    """(parts, info) from a folder written by fusion_read: millimetres, one part per placement."""
    with open(os.path.join(folder, 'occurrences.json'), encoding='utf-8') as handle:
        occ = json.load(handle)
    scale = 10.0 if occ.get('units', 'cm') == 'cm' else 1.0
    meshes = {}
    for name in sorted(os.listdir(folder)):
        if name.startswith('mesh_') and name.endswith('.bin'):
            meshes.update(read_meshes(os.path.join(folder, name)))
    bodies = {}
    for key, (pts, tris) in meshes.items():
        edges, smooth = mesh_features(pts, tris)
        bodies[key] = (pts, tris, edges, smooth)
    parts = []
    for item in occ['placements']:
        body = bodies.get(item['key'])
        if body is not None:
            parts.append(place(body, item['xf'], scale))
    names = {}
    for b in occ['bodies']:
        names[b['key']] = b.get('name') or ''
    return parts, {
        'document': occ.get('document') or '',
        'unique_bodies': len(bodies),
        'placements': len(occ['placements']),
        'missing': len(occ['placements']) - len(parts),
        'triangles': sum(len(p[2]) for p in parts),
        'names': names,
    }
