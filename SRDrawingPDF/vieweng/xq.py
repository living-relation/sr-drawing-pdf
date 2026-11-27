"""XQ exact lines: real STEP edges, visibility from a GPU depth buffer.

Ported from sr-drawing-pack research/render-tests/xq_render.py (ADR-051, ADR-052).
Needs OCP, VTK and numpy. Without them the engine reports that it cannot run.

Visible edges only: tangent edges are thin solid lines, never dashes. Short
breaks in a visible run are closed. Trimetric round edges that are ellipses
are fitted as ellipses. A STEP file is read once and cached by its hash.
"""
import json
import os
import re

from sheet2d.engines.curves import analytic_curve, bridge_gaps, fit_chain
from vieweng.window import _draw_depth, _offscreen_window

PAPER_PX = 0.02
PAPER_DEFL = 0.02
SMOOTH_DEG = 30.0
# One depth picture never asks the graphics driver for more than this on a side.
# A larger view is drawn in tiles and stitched. 16384 in one buffer crashed a driver.
TILE = 4096
MAX_RES = 8192


class XqEngine(object):
    name = 'xq'
    label = 'XQ exact lines'

    def available(self):
        missing = [name for name in ('numpy', 'vtk', 'OCP') if not _imports(name)]
        if missing:
            return False, 'XQ needs %s' % ', '.join(missing)
        return True, ''

    def project_view(self, name, parts=None, step=None, **opts):
        views, _timing = self.project_views((name,), step=step, **opts)
        return views[name]

    def project_views(self, names, parts=None, step=None, **opts):
        ok, why = self.available()
        if not ok:
            raise RuntimeError(why)
        if not step:
            raise ValueError('the XQ engine reads a STEP file')
        mode = opts.get('mode') or 'exact'
        if mode not in ('exact', 'quick'):
            raise ValueError('XQ mode must be exact or quick')
        return _render(step, tuple(names), workers=opts.get('workers'), mode=mode,
                       tangents=opts.get('tangents', True))


def _imports(name):
    try:
        __import__(name)
        return True
    except Exception:
        return False


def cache_dir():
    folder = os.environ.get('SRDP_CACHE') or os.path.join(
        os.path.expanduser('~'), '.cache', 'sr-drawing-pdf', 'xq')
    os.makedirs(folder, exist_ok=True)
    return folder


def _hash(path):
    import hashlib
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def load_shape(step):
    """(shape, seconds, from_step, names). The second call reads the cached brep.

    names is one string per solid, in the same order. The brep cache does not
    keep names, so they are stored beside it. An old cache has no names.
    """
    import time
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape
    t0 = time.perf_counter()
    # r2: the cached shape keeps each part's assembly position. Older caches do not.
    cache = os.path.join(cache_dir(), _hash(step) + '.r2.brep')
    names_path = cache + '.names.json'
    if os.path.isfile(cache):
        shape = TopoDS_Shape()
        BinTools.Read_s(shape, cache)
        names = []
        if os.path.isfile(names_path):
            try:
                with open(names_path, encoding='utf-8') as handle:
                    names = json.load(handle)
            except (OSError, ValueError):
                names = []
        return shape, time.perf_counter() - t0, False, names
    shape, names = _read_step(step)
    tmp = cache + '.%d.tmp' % os.getpid()
    BinTools.Write_s(shape, tmp)
    os.replace(tmp, cache)
    names_tmp = names_path + '.%d.tmp' % os.getpid()
    with open(names_tmp, 'w', encoding='utf-8') as handle:
        json.dump(list(names), handle)
    os.replace(names_tmp, names_path)
    return shape, time.perf_counter() - t0, True, names


def _read_step(path):
    """(shape, names). Names are read from the STEP file. A plain brep has none."""
    try:
        shape, names = _read_xcaf(path)
        if shape is not None:
            return shape, names
    except Exception:
        pass
    from OCP.STEPControl import STEPControl_Reader
    reader = STEPControl_Reader()
    reader.ReadFile(path)
    reader.TransferRoots()
    return reader.OneShape(), []


def _read_xcaf(path):
    """Solids in explorer order, each with the product name and its real position.

    A reference (an instance) carries a location. Nested assemblies multiply
    those locations. The shape that is stored on the part is only the prototype,
    so it has to be moved by the whole chain.
    """
    from OCP.BRep import BRep_Builder
    from OCP.IFSelect import IFSelect_ReturnStatus
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDF import TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS_Compound
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
    from OCP.collections import Sequence_TDF_Label

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString('XmlXCAF'))
    app.NewDocument(TCollection_ExtendedString('MDTV-XCAF'), doc)
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        return None, []
    reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    solids = []
    names = []

    def label_name(label):
        attr = TDataStd_Name()
        if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
            return attr.Get().ToExtString()
        return ''

    def add_shape(shape, name):
        if shape is None or shape.IsNull():
            return
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solids.append(explorer.Current())
            names.append(name or '')
            explorer.Next()

    def walk(label, parent, inherited):
        name = label_name(label) or inherited
        if XCAFDoc_ShapeTool.IsReference_s(label):
            referred = TDF_Label()
            if XCAFDoc_ShapeTool.GetReferredShape_s(label, referred):
                inst = XCAFDoc_ShapeTool.GetLocation_s(label)
                walk(referred, parent.Multiplied(inst), name)
            return
        kids = Sequence_TDF_Label()
        if XCAFDoc_ShapeTool.GetComponents_s(label, kids, False) and kids.Length():
            for index in range(1, kids.Length() + 1):
                walk(kids.Value(index), parent, name)
            return
        shape = tool.GetShape_s(label)
        if shape is None or shape.IsNull():
            return
        add_shape(shape.Located(parent), name)

    free = Sequence_TDF_Label()
    tool.GetFreeShapes(free)
    origin = TopLoc_Location()
    for index in range(1, free.Length() + 1):
        walk(free.Value(index), origin, '')
    if not solids:
        return None, []
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for solid in solids:
        builder.Add(compound, solid)
    return compound, names


def _show_tangents(name, tangents):
    """Tangent edges are drawn unless this view asks to hide them."""
    if tangents is None or tangents is True:
        return True
    if tangents is False:
        return False
    if isinstance(tangents, dict):
        return bool(tangents.get(name, True))
    raise ValueError('tangents must be true, false, or a map of view name to true or false')


def _render(step, names, workers=None, mode='exact', tangents=True):
    import time
    import numpy as np
    from sheet2d.project import _basis
    t0 = time.perf_counter()
    shape, read_s, from_step, part_names = load_shape(step)
    # A loose sheet face is not part of a solid. It must not stretch the view.
    shape = _solids(shape)
    lo, hi = _bbox(shape)
    # Depth pixels follow the sheet scale the mesh views would pick, about 0.02 mm on paper.
    scale = _rough_scale(lo, hi, names)
    defl = PAPER_DEFL / max(scale, 1e-6)
    size = float(np.linalg.norm(hi - lo))
    fit = mode != 'quick'
    res = int(min(MAX_RES, max(512, (size * scale) / PAPER_PX)))
    if mode == 'quick':
        res = min(res, 2048)
    step_len = 0.7 * size / res
    t_mesh = time.perf_counter()
    repeated = _repeated_build(shape, defl, step_len, part_names, workers)
    if repeated is None:
        V, F, CN = _mesh_arrays(shape, defl)
        mesh_s = time.perf_counter() - t_mesh
        t_edge = time.perf_counter()
        plain, hardware = _hardware_split(shape, part_names)
        if hardware:
            if plain is None:
                points, counts, tangent, analytic = _empty_edges()
            else:
                points, counts, tangent, analytic = _edges(plain, defl, step_len, workers)
            hardware = [(solid, _edges(solid, defl, step_len, 1), _solid_triangles(solid)) for solid in hardware]
        else:
            points, counts, tangent, analytic = _edges(shape, defl, step_len, workers)
        edge_s = time.perf_counter() - t_edge
        unique_solids = None
    else:
        V, F, CN, points, counts, tangent, analytic, hardware, unique_solids, mesh_s, edge_s = repeated
    depth = _Depth(V, F)
    views = {}
    per = {}
    corners = _corners(lo, hi)
    for name in names:
        tv = time.perf_counter()
        toward, right, up = _basis(name)
        c = np.array(toward, float)
        r = np.array(right, float)
        u = np.array(up, float)
        ext_r = float(np.ptp(corners @ r))
        ext_u = float(np.ptp(corners @ u))
        zb, to_win, dz, px = depth.render(c, r, u, ext_r, ext_u, res)
        use_points, use_counts, use_tangent, use_analytic, masks = _with_hardware_outline(
            points, counts, tangent, analytic, hardware, r, u)
        lines = _view_lines(
            V, F, CN, use_points, use_counts, use_tangent, use_analytic,
            c, r, u, zb, to_win, dz, px, defl, name, fit,
            show_tangents=_show_tangents(name, tangents), masks=masks,
            span=max(ext_r, ext_u))
        us = [p[0] for line in lines for p in _pts_of(line)]
        vs = [p[1] for line in lines for p in _pts_of(line)]
        if not us:
            us = list(corners @ r)
            vs = list(corners @ u)
        views[name] = {
            'name': name,
            'lines': lines,
            'extent': (min(us), max(us), min(vs), max(vs)),
            'seconds': time.perf_counter() - tv,
        }
        per[name] = round(views[name]['seconds'], 3)
    timing = {
        'engine': 'xq',
        'read_s': round(read_s, 3),
        'from_step': from_step,
        'mesh_s': round(mesh_s, 3),
        'edges_s': round(edge_s, 3),
        'views_s': round(sum(v['seconds'] for v in views.values()), 3),
        'total_s': round(time.perf_counter() - t0, 3),
        'per_view': per,
        'res': res,
        'unique_solids': unique_solids,
    }
    return views, timing


def _pts_of(line):
    if line['kind'] == 'poly':
        return line['pts']
    if line['kind'] == 'circle':
        c, r = line['c'], line['r']
        return [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    if line['kind'] == 'ellipse':
        c, rx, ry = line['c'], line['rx'], line['ry']
        return [(c[0] - rx, c[1] - ry), (c[0] + rx, c[1] + ry)]
    if line['kind'] == 'arc':
        from sheet2d.engines.curves import arc_points
        return arc_points(line, 16)
    return []


def _buffer_size(ext_r, ext_u, res):
    """Pixel size of the depth picture. The long side stays within MAX_RES."""
    longest = max(ext_r, ext_u, 1e-6)
    width = max(32, int(res * min(1.0, ext_r / longest)))
    height = max(32, int(res * min(1.0, ext_u / longest)))
    long_side = max(width, height)
    if long_side > MAX_RES:
        shrink = MAX_RES / float(long_side)
        width = max(32, int(width * shrink))
        height = max(32, int(height * shrink))
    return width, height


def _solids(shape):
    """The solids in a file. Loose faces are left out when any solid exists."""
    from OCP.BRep import BRep_Builder
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS_Compound
    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    if not found:
        return shape
    if len(found) == 1 and shape.ShapeType() == TopAbs_SOLID:
        return shape
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for solid in found:
        builder.Add(compound, solid)
    return compound


def _bbox(shape):
    import numpy as np
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, True)
    p, q = box.CornerMin(), box.CornerMax()
    return np.array([p.X(), p.Y(), p.Z()]), np.array([q.X(), q.Y(), q.Z()])


def _corners(lo, hi):
    import numpy as np
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])


def _rough_scale(lo, hi, names):
    """A sheet-like scale so the depth buffer is about 0.02 mm on paper. Not the sheet layout."""
    import numpy as np
    from sheet2d.project import _basis
    corners = _corners(lo, hi)
    span = 1.0
    for name in names:
        _c, right, up = _basis(name)
        r = np.array(right, float)
        u = np.array(up, float)
        span = max(span, float(np.ptp(corners @ r)), float(np.ptp(corners @ u)))
    # Size B has about 380 mm of width for the views.
    return min(1.0, 380.0 / span)


def _mesh(shape, defl):
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    BRepMesh_IncrementalMesh(shape, defl, False, 0.25, True)


def _mesh_arrays(shape, defl):
    import os
    import tempfile
    import numpy as np
    from OCP.StlAPI import StlAPI_Writer
    _mesh(shape, defl)
    path = os.path.join(tempfile.gettempdir(), 'xq_%d.stl' % os.getpid())
    writer = StlAPI_Writer()
    writer.ASCIIMode = False
    writer.Write(shape, path)
    dt = np.dtype([('n', '<f4', 3), ('v', '<f4', (3, 3)), ('a', '<u2')])
    with open(path, 'rb') as handle:
        handle.seek(80)
        n = int(np.frombuffer(handle.read(4), '<u4')[0])
        rec = np.frombuffer(handle.read(n * 50), dt)
    try:
        os.remove(path)
    except OSError:
        pass
    tri = np.ascontiguousarray(rec['v'])
    V = tri.reshape(-1, 3)
    key = np.ascontiguousarray(V).view(np.dtype((np.void, 12))).ravel()
    _uniq, first, inv = np.unique(key, return_index=True, return_inverse=True)
    verts = V[first]
    faces = inv.reshape(-1, 3)
    raw = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]).astype(np.float64)
    return verts, faces, _corner_normals(faces, raw)


def _repeated_build(shape, defl, step, part_names=None, workers=None):
    """Mesh and sample each repeated solid once, then place the copies.

    Returns None when almost every solid is unique, so that path stays the
    single mesh of the whole file.
    """
    import numpy as np
    solids = _solid_list(shape)
    if len(solids) < 2:
        return None
    groups = {}
    order = []
    part_names = list(part_names or [])
    if len(part_names) < len(solids):
        part_names += [''] * (len(solids) - len(part_names))
    for index, solid in enumerate(solids):
        # Same shape with a different kind of name is not the same part.
        key = (_repeat_key(solid), name_is_fastener(part_names[index]))
        if key not in groups:
            groups[key] = []
            order.append(key)
        lo, hi = _bbox(solid)
        groups[key].append((solid, (lo + hi) * 0.5, part_names[index]))
    if len(order) == len(solids):
        return None
    import time
    verts_all, faces_all, cn_all = [], [], []
    plain_pts, plain_counts, plain_tan, plain_an = [], [], [], []
    hardware = []
    vcount = 0
    mesh_s = edge_s = 0.0
    protos = [groups[key][0][0] for key in order]
    t_edge = time.perf_counter()
    sampled = _sample_prototypes(protos, defl, step, workers)
    edge_s += time.perf_counter() - t_edge
    for key, edges in zip(order, sampled):
        proto, origin, proto_name = groups[key][0]
        t_mesh = time.perf_counter()
        verts, faces, cn = _mesh_arrays(proto, defl)
        mesh_s += time.perf_counter() - t_mesh
        fastener = _is_fastener(proto, proto_name)
        for _solid, center, _name in groups[key]:
            delta = center - origin
            moved = verts + delta
            verts_all.append(moved)
            faces_all.append(faces + vcount)
            cn_all.append(cn)
            vcount += len(moved)
            shifted = _shift_edges(edges, delta)
            if fastener:
                hardware.append((_solid, shifted, moved[faces]))
            else:
                hp, hc, ht, ha = shifted
                if len(hc):
                    plain_pts.append(hp)
                    plain_counts.append(hc)
                    plain_tan.append(ht)
                    plain_an.extend(ha)
    if not verts_all:
        return None
    if plain_pts:
        points = np.concatenate(plain_pts)
        counts = np.concatenate(plain_counts).astype(int)
        tangent = np.concatenate(plain_tan).astype(bool)
        analytic = plain_an
    else:
        points, counts, tangent, analytic = _empty_edges()
    return (np.concatenate(verts_all), np.concatenate(faces_all), np.concatenate(cn_all),
            points, counts, tangent, analytic, hardware, len(order), mesh_s, edge_s)


def _shift_edges(edges, delta):
    points, counts, tangent, analytic = edges
    if len(points) == 0:
        return points, counts, tangent, list(analytic)
    moved = points + delta
    shifted = []
    for info in analytic:
        if not info:
            shifted.append(None)
            continue
        copy = dict(info)
        ox, oy, oz = info['o']
        copy['o'] = (ox + float(delta[0]), oy + float(delta[1]), oz + float(delta[2]))
        shifted.append(copy)
    return moved, counts, tangent, shifted


def _repeat_key(solid):
    """Same key for copies that differ only by where they sit."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    lo, hi = _bbox(solid)
    size = tuple(round(float(hi[i] - lo[i]), 3) for i in range(3))
    marks = []
    explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while explorer.More():
        face = _cast(TopoDS, 'Face')(explorer.Current())
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        marks.append((int(BRepAdaptor_Surface(face).GetType()), round(float(props.Mass()), 2)))
        explorer.Next()
    return (size, tuple(sorted(marks)))


def _corner_normals(faces, raw):
    import numpy as np
    unit = raw / (np.linalg.norm(raw, axis=1, keepdims=True) + 1e-30)
    corners = faces.ravel()
    tri = np.repeat(np.arange(len(faces)), 3)
    order = np.argsort(corners, kind='stable')
    corners, tri = corners[order], tri[order]
    starts = np.r_[0, np.nonzero(corners[1:] != corners[:-1])[0] + 1]
    out = np.zeros((len(corners), 3))
    cos_t = np.cos(np.radians(SMOOTH_DEG))
    for begin, end in zip(starts, np.r_[starts[1:], len(corners)]):
        ids = tri[begin:end]
        normals = unit[ids]
        weights = raw[ids]
        near = normals @ normals.T > cos_t
        out[begin:end] = near.astype(float) @ weights
    out /= np.linalg.norm(out, axis=1, keepdims=True) + 1e-30
    cn = np.zeros((len(faces), 3, 3))
    slot = np.tile(np.arange(3), len(faces))[order]
    cn[tri, slot] = out
    return cn


# A screw, nut, washer, standoff, or the other SR Fastener names, and only when
# the part is small and turned. A connector, handle, or rail is not hardware
# even when it is round. Only a recess, chamfer, or cone inside the head is
# left out. The outer silhouette stays.
FASTENER_R_MM = 30.0
FASTENER_L_MM = 200.0
_FASTENER_NAME = re.compile(
    r'\b(screws?|bolts?|nuts?|washers?|standoffs?|inserts?|shcs|bhcs|fhcs|rivets?|fasteners?)\b',
    re.I)
# A part that only names a fastener ("ball nut", "screw plate") is not one.
_NOT_FASTENER = re.compile(
    r'\b(ball ?nuts?|ball ?screws?|lead ?screws?|plates?|housings?|brackets?|carriages?|rails?|pinions?|blocks?)\b',
    re.I)


def name_is_fastener(name):
    """True for a real fastener name. A connector, handle, or rail is not one.

    Uses the same rules as sheet2d.meshparts.is_hardware, so SR Fastener style
    codes (SBH-, SO-, NHX-, FHS-, WSL- ...) count, and connector plugs,
    terminals and USB inserts do not.
    """
    from sheet2d.meshparts import NOT_HARDWARE_RE, is_hardware
    raw = name or ''
    text = raw.lower().replace('stand-off', 'standoff').replace('stand off', 'standoff')
    if not text or _NOT_FASTENER.search(text):
        return False
    if is_hardware(raw):
        return True
    if NOT_HARDWARE_RE.search(text) or re.search(r'\busb\b', text):
        return False
    return _FASTENER_NAME.search(text) is not None


def _empty_edges():
    import numpy as np
    return np.zeros((0, 3)), np.zeros(0, int), np.zeros(0, bool), []


def _solid_list(shape):
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer
    found = []
    explorer = TopExp_Explorer(shape, TopAbs_SOLID)
    while explorer.More():
        found.append(explorer.Current())
        explorer.Next()
    return found


def _hardware_split(shape, part_names=None):
    """(other solids as one shape or None, fastener solids)."""
    solids = _solid_list(shape)
    if not solids:
        return shape, []
    part_names = list(part_names or [])
    if len(part_names) < len(solids):
        part_names += [''] * (len(solids) - len(part_names))
    hard = []
    rest = []
    for solid, name in zip(solids, part_names):
        if _is_fastener(solid, name):
            hard.append(solid)
        else:
            rest.append(solid)
    if not hard:
        return shape, []
    if not rest:
        return None, hard
    return _compound(rest), hard


def _compound(solids):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    builder = BRep_Builder()
    compound = TopoDS_Compound()
    builder.MakeCompound(compound)
    for solid in solids:
        builder.Add(compound, solid)
    return compound


def _is_fastener(solid, name=''):
    """A named fastener that is small and turned. No name means it is not one."""
    if not name_is_fastener(name):
        return False
    import numpy as np
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Cone, GeomAbs_Cylinder
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    axes = []
    explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while explorer.More():
        face = _cast(TopoDS, 'Face')(explorer.Current())
        try:
            surface = BRepAdaptor_Surface(face)
            kind = surface.GetType()
            if kind == GeomAbs_Cylinder:
                axis = surface.Cylinder().Axis()
            elif kind == GeomAbs_Cone:
                axis = surface.Cone().Axis()
            else:
                axis = None
            if axis is not None:
                direction = np.array([axis.Direction().X(), axis.Direction().Y(), axis.Direction().Z()])
                direction = direction / (np.linalg.norm(direction) + 1e-15)
                if direction[2] < 0 or (abs(direction[2]) < 1e-9 and direction[0] < 0):
                    direction = -direction
                origin = np.array([axis.Location().X(), axis.Location().Y(), axis.Location().Z()])
                axes.append((origin, direction))
        except Exception:
            pass
        explorer.Next()
    if not axes:
        return False
    base = axes[0][1]
    if any(abs(float(np.dot(base, direction))) < 0.98 for _origin, direction in axes):
        return False
    origin = axes[0][0]
    lo, hi = _bbox(solid)
    rel = _corners(lo, hi) - origin
    along = rel @ base
    radial = np.linalg.norm(rel - along[:, None] * base, axis=1)
    return float(radial.max()) <= FASTENER_R_MM and float(along.max() - along.min()) <= FASTENER_L_MM


def _solid_triangles(solid):
    """Triangles written onto the solid when the whole file was meshed."""
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    tris = []
    explorer = TopExp_Explorer(solid, TopAbs_FACE)
    while explorer.More():
        face = _cast(TopoDS, 'Face')(explorer.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None and tri.NbTriangles() > 0:
            tr = loc.Transformation()
            nodes = np.zeros((tri.NbNodes(), 3))
            for i in range(1, tri.NbNodes() + 1):
                point = tri.Node(i).Transformed(tr)
                nodes[i - 1] = (point.X(), point.Y(), point.Z())
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                tris.append(nodes[[a - 1, b - 1, c - 1]])
        explorer.Next()
    if not tris:
        return np.zeros((0, 3, 3))
    return np.stack(tris)


def _with_hardware_outline(points, counts, tangent, analytic, hardware, right, up):
    """Add fastener edges, minus socket, chamfer, and cone lines inside the outline.

    Also returns the filled masks, so a silhouette inside a fastener can be
    dropped the same way. Quick and Exact share that test.
    """
    import numpy as np
    chunks = [(points, counts, tangent, list(analytic))]
    masks = []
    for _solid, edges, tris in hardware:
        hp, hc, ht, ha = edges
        if len(hc) == 0 or len(tris) == 0:
            chunks.append((hp, hc, ht, list(ha)))
            continue
        flat = np.c_[hp @ right, hp @ up]
        tri2 = np.stack([tris @ right, tris @ up], axis=-1)
        mask = _fill_mask(tri2)
        if mask is not None:
            masks.append(mask)
        keep = _outline_edges(flat, hc, tri2, list(ha), right, up, mask)
        if not keep.any():
            continue
        kept = np.nonzero(keep)[0]
        chunks.append((_take_edges(hp, hc, keep), hc[keep], ht[keep], [ha[i] for i in kept]))
    chunks = [c for c in chunks if len(c[1])]
    if not chunks:
        return _empty_edges() + (masks,)
    analytic_out = []
    for _p, _c, _t, ha in chunks:
        analytic_out.extend(ha)
    return (np.concatenate([c[0] for c in chunks]),
            np.concatenate([c[1] for c in chunks]).astype(int),
            np.concatenate([c[2] for c in chunks]).astype(bool),
            analytic_out, masks)


def _take_edges(points, counts, keep):
    import numpy as np
    spans = np.cumsum(np.r_[0, counts])
    return np.concatenate([points[spans[i]:spans[i + 1]] for i in np.nonzero(keep)[0]])


def _outline_edges(flat, counts, tri2, analytic=None, right=None, up=None, mask=None):
    """True for edges that sit on the part outline. An inside edge has the part on both sides.

    A round edge uses its real center, so a coarse Quick sample still finds the socket.
    """
    import numpy as np
    if mask is None:
        mask = _fill_mask(tri2)
    if mask is None:
        return np.ones(len(counts), dtype=bool)
    origin, cell, grid = mask
    spans = np.cumsum(np.r_[0, counts])
    keep = np.ones(len(counts), dtype=bool)
    n = grid.shape[0]
    probe = 0.75 * cell

    def inside(point):
        ix = int((point[0] - origin[0]) / cell)
        iy = int((point[1] - origin[1]) / cell)
        return 0 <= ix < n and 0 <= iy < n and grid[iy, ix] == 1

    def both_sides(mid, normal):
        return inside(mid + normal) and inside(mid - normal)

    for i, (a, b) in enumerate(zip(spans[:-1], spans[1:])):
        info = analytic[i] if analytic and i < len(analytic) else None
        mid = flat[min(max(a, (a + b) // 2), b - 1)]
        normal = None
        if info and info.get('o') is not None and right is not None and info.get('r'):
            center = np.array(info['o'], float)
            c2 = np.array([float(center @ right), float(center @ up)])
            radial = mid - c2
            reach = float(np.hypot(radial[0], radial[1]))
            if reach > 0.25 * float(info['r']):
                normal = radial / reach * probe
        if normal is None:
            if b - a < 2:
                continue
            mid_i = (a + b) // 2
            step_i = min(b - 1, mid_i + max(1, (b - a) // 16))
            chord = flat[step_i] - flat[mid_i]
            length = float(np.hypot(chord[0], chord[1]))
            if length < 1e-9:
                continue
            normal = np.array([-chord[1], chord[0]]) / length * probe
            mid = flat[mid_i]
        if both_sides(mid, normal):
            keep[i] = False
    if analytic:
        _keep_outer_silhouette(keep, flat, counts, analytic)
    return keep


def _outer_silhouettes(segs, masks):
    """True for silhouette pieces on the outside of a fastener, not in the head.

    One lookup for every piece. A piece with the head on both sides is the
    recess. A piece with air on one side is the outline, including a handle bar
    that is not a fastener at all.
    """
    import numpy as np
    keep = np.ones(len(segs), dtype=bool)
    if not len(segs) or not masks:
        return keep
    mids = (segs[:, 0] + segs[:, 1]) * 0.5
    chords = segs[:, 1] - segs[:, 0]
    length = np.hypot(chords[:, 0], chords[:, 1])
    scale = np.maximum(length, 1e-12)
    normal = np.stack([-chords[:, 1] / scale, chords[:, 0] / scale], axis=1)
    usable = length > 1e-9
    for origin, cell, grid in masks:
        probe = 0.75 * cell
        side_a = _mask_hits(mids + normal * probe, origin, cell, grid)
        side_b = _mask_hits(mids - normal * probe, origin, cell, grid)
        keep &= ~(usable & side_a & side_b)
    return keep


def _keep_outer_silhouette(keep, flat, counts, analytic):
    """The largest rim and a long edge stay. A smaller cone circle is a chamfer."""
    import numpy as np
    radii = [float(info['r']) for info in analytic if info and info.get('r')]
    outer = max(radii) if radii else 0.0
    spans = np.cumsum(np.r_[0, counts])
    for i, info in enumerate(analytic):
        a, b = int(spans[i]), int(spans[i + 1])
        if b - a >= 2:
            length = float(np.linalg.norm(np.diff(flat[a:b], axis=0), axis=1).sum())
        else:
            length = 0.0
        if info and info.get('r') and outer and float(info['r']) >= 0.92 * outer:
            keep[i] = True
        elif info and info.get('cone') and info.get('r') and outer and float(info['r']) < 0.92 * outer:
            keep[i] = False
        elif not info and length >= max(outer, 1.0) * 2.0:
            keep[i] = True


def _fill_mask(tri2, n=64):
    """Which cells the part covers. Triangles are tested together, not one Python loop each."""
    import numpy as np
    if len(tri2) == 0:
        return None
    flat = tri2.reshape(-1, 2)
    lo = flat.min(0)
    hi = flat.max(0)
    span = float(max(hi[0] - lo[0], hi[1] - lo[1], 1e-6))
    cell = span / n
    xs = lo[0] + (np.arange(n) + 0.5) * cell
    ys = lo[1] + (np.arange(n) + 0.5) * cell
    xx, yy = np.meshgrid(xs, ys)
    pts = np.stack([xx.ravel(), yy.ravel()], axis=1)
    covered = np.zeros(pts.shape[0], np.uint8)
    for start in range(0, len(tri2), 64):
        tris = np.asarray(tri2[start:start + 64], float)
        v0 = tris[:, 2] - tris[:, 0]
        v1 = tris[:, 1] - tris[:, 0]
        den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
        ok = np.abs(den) >= 1e-12
        if not ok.any():
            continue
        tris, v0, v1, den = tris[ok], v0[ok], v1[ok], den[ok]
        rel = pts[None, :, :] - tris[:, None, 0, :]
        alpha = (rel[:, :, 0] * v1[:, None, 1] - v1[:, None, 0] * rel[:, :, 1]) / den[:, None]
        beta = (v0[:, None, 0] * rel[:, :, 1] - rel[:, :, 0] * v0[:, None, 1]) / den[:, None]
        inside = (alpha >= -1e-6) & (beta >= -1e-6) & (alpha + beta <= 1.0 + 1e-6)
        covered[inside.any(axis=0)] = 1
    grid = covered.reshape(n, n)
    return lo, cell, _fill_holes(grid)


def _fill_holes(grid):
    """Fill across each row. A socket hole then counts as inside the head."""
    import numpy as np
    width = grid.shape[1]
    index = np.arange(width)
    present = grid.astype(bool)
    last = np.where(present, index, -1).max(1)
    first = np.where(present, index, width).min(1)
    cols = index[None, :]
    span = (cols >= first[:, None]) & (cols <= last[:, None]) & (last[:, None] >= 0)
    return np.where(span, np.uint8(1), grid)


def _mask_hits(points, origin, cell, grid):
    """Which points land on a filled mask cell. Vectorized."""
    import numpy as np
    n = grid.shape[0]
    ix = np.floor((points[:, 0] - origin[0]) / cell).astype(int)
    iy = np.floor((points[:, 1] - origin[1]) / cell).astype(int)
    ok = (ix >= 0) & (ix < n) & (iy >= 0) & (iy < n)
    inside = np.zeros(len(points), dtype=bool)
    inside[ok] = grid[iy[ok], ix[ok]] == 1
    return inside


def _cpu_workers(requested, jobs):
    """How many processes to use. The default is one less than the machine."""
    if not requested:
        requested = max(1, (os.cpu_count() or 2) - 1)
    return max(1, min(int(requested), max(1, jobs)))


def _process_pool(width):
    """Workers start clean. They import this module; they do not re-run the caller's script.

    Fusion launches a script as the main file. The default pool on Windows
    would start that script again. Spawn starts from this module instead.
    """
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor
    return ProcessPoolExecutor(max_workers=width, mp_context=mp.get_context('spawn'))


def _worker_ping(value):
    """Used to prove a spawned worker can import this module."""
    return value + 1


def _sample_prototypes(shapes, defl, step, workers):
    """Sample every prototype. Several at once when the machine has more than one core."""
    paths = [_write_temp_brep(shape, i) for i, shape in enumerate(shapes)]
    jobs = [(path, 0, 10 ** 12, defl, step) for path in paths]
    width = _cpu_workers(workers, len(jobs))
    try:
        if width > 1 and len(jobs) > 1:
            pool = _process_pool(width)
            parts = list(pool.map(_sample_edges, jobs))
            pool.shutdown()
        else:
            parts = [_sample_edges(job) for job in jobs]
    finally:
        for path in paths:
            try:
                os.remove(path)
            except OSError:
                pass
    return parts


def _edges(shape, defl, step, workers):
    import numpy as np
    count = _edge_count(shape)
    cache = _write_temp_brep(shape)
    workers = _cpu_workers(workers, max(1, count // 400))
    bounds = [int(v) for v in np.linspace(0, count, workers + 1)]
    jobs = [(cache, bounds[i], bounds[i + 1], defl, step) for i in range(workers)]
    if workers > 1:
        pool = _process_pool(workers)
        parts = list(pool.map(_sample_edges, jobs))
        pool.shutdown()
    else:
        parts = [_sample_edges(job) for job in jobs]
    try:
        os.remove(cache)
    except OSError:
        pass
    if not parts or all(len(p[1]) == 0 for p in parts):
        return np.zeros((0, 3)), np.zeros(0, int), np.zeros(0, bool), []
    analytic = []
    for part in parts:
        analytic.extend(part[3])
    return (np.concatenate([p[0] for p in parts]),
            np.concatenate([p[1] for p in parts]).astype(int),
            np.concatenate([p[2] for p in parts]).astype(bool),
            analytic)


def _write_temp_brep(shape, slot=0):
    import tempfile
    from OCP.BinTools import BinTools
    path = os.path.join(tempfile.gettempdir(), 'xq_edges_%d_%d.brep' % (os.getpid(), slot))
    BinTools.Write_s(shape, path)
    return path


def _edge_count(shape):
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.collections import (
        IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as Map,
    )
    mapped = Map()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, mapped)
    return mapped.Extent()


def _cast(mod, name):
    return getattr(mod, name + '_s', None) or getattr(mod, name)


def _sample_edges(args):
    """Worker: sample edges [i0, i1). Tangent edges are flagged, not dashed."""
    import numpy as np
    cache, i0, i1, defl, step = args
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.BRepLib import BRepLib
    from OCP.BinTools import BinTools
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_G1, GeomAbs_Line
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp
    from OCP.TopoDS import TopoDS, TopoDS_Shape
    from OCP.collections import (
        IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as Map,
    )
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, cache)
    mapped = Map()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, mapped)
    pts, counts, tangent, analytic = [], [], [], []
    for index in range(i0 + 1, min(i1, mapped.Extent()) + 1):
        edge = _cast(TopoDS, 'Edge')(mapped.FindKey(index))
        if BRep_Tool.Degenerated_s(edge):
            continue
        faces = [_cast(TopoDS, 'Face')(face) for face in mapped.FindFromIndex(index)]
        if len(faces) == 1 and BRep_Tool.IsClosed_s(edge, faces[0]):
            continue
        is_tan = False
        if len(faces) >= 2:
            if faces[0].IsSame(faces[1]) and BRep_Tool.IsClosed_s(edge, faces[0]):
                continue
            try:
                BRepLib.EncodeRegularity_s(edge, faces[0], faces[1], 0.01)
                is_tan = int(BRep_Tool.Continuity_s(edge, faces[0], faces[1])) >= int(GeomAbs_G1)
            except Exception:
                is_tan = False
        try:
            curve = BRepAdaptor_Curve(edge)
            kind = curve.GetType()
            curve_info = None
            if kind == GeomAbs_Line:
                p = curve.Value(curve.FirstParameter())
                q = curve.Value(curve.LastParameter())
                sampled = np.array([[p.X(), p.Y(), p.Z()], [q.X(), q.Y(), q.Z()]])
            elif kind == GeomAbs_Circle:
                circle = curve.Circle()
                ax = circle.Position()
                origin = np.array([ax.Location().X(), ax.Location().Y(), ax.Location().Z()])
                xd = np.array([ax.XDirection().X(), ax.XDirection().Y(), ax.XDirection().Z()])
                yd = np.array([ax.YDirection().X(), ax.YDirection().Y(), ax.YDirection().Z()])
                radius = circle.Radius()
                u0, u1 = curve.FirstParameter(), curve.LastParameter()
                da = 2 * np.arccos(max(-1.0, 1 - defl / max(radius, 1e-9))) if radius > defl else np.pi / 4
                params = np.linspace(u0, u1, max(3, int(np.ceil(abs(u1 - u0) / max(da, 1e-3))) + 1))
                sampled = origin + radius * (np.cos(params)[:, None] * xd + np.sin(params)[:, None] * yd)
                on_cone = False
                for face in faces:
                    try:
                        if BRepAdaptor_Surface(face).GetType() == GeomAbs_Cone:
                            on_cone = True
                    except Exception:
                        pass
                curve_info = {
                    'u0': float(u0), 'u1': float(u1), 'r': float(radius),
                    'o': (float(origin[0]), float(origin[1]), float(origin[2])),
                    'x': (float(xd[0]), float(xd[1]), float(xd[2])),
                    'y': (float(yd[0]), float(yd[1]), float(yd[2])),
                    'cone': on_cone,
                }
            else:
                deflect = GCPnts_QuasiUniformDeflection(curve, defl)
                if not deflect.IsDone() or deflect.NbPoints() < 2:
                    continue
                sampled = np.array([
                    [deflect.Value(j).X(), deflect.Value(j).Y(), deflect.Value(j).Z()]
                    for j in range(1, deflect.NbPoints() + 1)])
        except Exception:
            continue
        pts.append(sampled)
        counts.append(len(sampled))
        tangent.append(is_tan)
        analytic.append(curve_info)
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, int), np.zeros(0, bool), []
    dense, new_counts = _densify_many(pts, step)
    return dense, new_counts, np.array(tangent), analytic


def _densify_many(chunks, step):
    """Densify every edge at once. The points match densifying each edge alone."""
    import numpy as np
    counts = np.array([len(chunk) for chunk in chunks], int)
    if counts.sum() == 0:
        return np.zeros((0, 3)), counts
    points = np.concatenate(chunks)
    if len(points) < 2:
        return points, counts
    edge_id = np.repeat(np.arange(len(counts)), counts)
    same = edge_id[1:] == edge_id[:-1]
    delta = np.linalg.norm(np.diff(points, axis=0), axis=1)
    pieces = np.where(same, np.maximum(1, np.ceil(delta / max(step, 1e-9)).astype(int)), 1)
    if pieces.max() == 1:
        return points, counts
    index = np.repeat(np.arange(len(pieces)), pieces)
    k = np.arange(pieces.sum()) - np.repeat(np.cumsum(pieces) - pieces, pieces) + 1
    frac = np.where(same[index], k / pieces[index], 1.0)
    dense = np.vstack([points[:1], points[index] + (points[index + 1] - points[index]) * frac[:, None]])
    owners = np.r_[edge_id[0], edge_id[index + 1]]
    return dense, np.bincount(owners, minlength=len(counts)).astype(int)


def _densify(points, step):
    import numpy as np
    if len(points) < 2:
        return points
    delta = np.linalg.norm(np.diff(points, axis=0), axis=1)
    pieces = np.maximum(1, np.ceil(delta / max(step, 1e-9)).astype(int))
    if pieces.max() == 1:
        return points
    index = np.repeat(np.arange(len(pieces)), pieces)
    k = np.arange(pieces.sum()) - np.repeat(np.cumsum(pieces) - pieces, pieces) + 1
    frac = (k / pieces[index])[:, None]
    return np.vstack([points[:1], points[index] + (points[index + 1] - points[index]) * frac])


class _Depth(object):
    def __init__(self, verts, faces):
        import numpy as np
        import vtk
        from vtk.util import numpy_support as ns
        self.vtk = vtk
        self.np = np
        points = vtk.vtkPoints()
        points.SetData(ns.numpy_to_vtk(verts.astype(np.float32), deep=True))
        cells = vtk.vtkCellArray()
        offsets = np.arange(0, 3 * len(faces) + 1, 3, dtype=np.int64)
        cells.SetData(ns.numpy_to_vtkIdTypeArray(offsets, deep=True),
                      ns.numpy_to_vtkIdTypeArray(faces.astype(np.int64).ravel(), deep=True))
        data = vtk.vtkPolyData()
        data.SetPoints(points)
        data.SetPolys(cells)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(data)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        self.ren = vtk.vtkRenderer()
        self.ren.AddActor(actor)
        self.win = _offscreen_window()
        self.win.AddRenderer(self.ren)
        self.center = (verts.min(0) + verts.max(0)) / 2
        self.radius = float(np.linalg.norm(verts.max(0) - verts.min(0)) / 2 + 1e-6)

    def render(self, toward, right, up, ext_r, ext_u, res):
        import numpy as np
        width, height = _buffer_size(ext_r, ext_u, res)
        toward = np.array(toward, float)
        right = np.array(right, float)
        up = np.array(up, float)
        if width <= TILE and height <= TILE:
            image = self._tile(toward, right, up, ext_r, ext_u, width, height, 0, 0, width, height)
        else:
            image = np.ones((height, width), np.float32)
            for y0 in range(0, height, TILE):
                for x0 in range(0, width, TILE):
                    tw = min(TILE, width - x0)
                    th = min(TILE, height - y0)
                    image[y0:y0 + th, x0:x0 + tw] = self._tile(
                        toward, right, up, ext_r, ext_u, width, height, x0, y0, tw, th)
        return image, *self._mapper(toward, right, up, ext_r, ext_u, width, height)

    def _tile(self, toward, right, up, ext_r, ext_u, width, height, x0, y0, tw, th):
        """One depth tile. x0, y0 are pixels from the bottom left of the full view."""
        import numpy as np
        vtk = self.vtk
        scale = max(ext_u, ext_r * height / max(width, 1)) / 2 * 1.04
        half_u = scale
        half_r = scale * width / max(height, 1)
        mid_r = -half_r + (x0 + tw / 2.0) / width * (2 * half_r)
        mid_u = -half_u + (y0 + th / 2.0) / height * (2 * half_u)
        focal = self.center + right * mid_r + up * mid_u
        self.win.SetSize(int(tw), int(th))
        cam = self.ren.GetActiveCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*focal)
        cam.SetPosition(*(focal + toward * 4 * self.radius))
        cam.SetViewUp(*up)
        cam.SetParallelScale(scale * th / max(height, 1))
        cam.SetClippingRange(2 * self.radius, 6 * self.radius)
        _draw_depth(self.win)
        zbuf = vtk.vtkFloatArray()
        self.win.GetZbufferData(0, 0, int(tw) - 1, int(th) - 1, zbuf)
        from vtk.util import numpy_support as ns
        return np.array(ns.vtk_to_numpy(zbuf), copy=True).reshape(int(th), int(tw))

    def _mapper(self, toward, right, up, ext_r, ext_u, width, height):
        import numpy as np
        vtk = self.vtk
        scale = max(ext_u, ext_r * height / max(width, 1)) / 2 * 1.04
        cam = vtk.vtkCamera()
        cam.ParallelProjectionOn()
        cam.SetFocalPoint(*self.center)
        cam.SetPosition(*(self.center + toward * 4 * self.radius))
        cam.SetViewUp(*up)
        cam.SetParallelScale(scale)
        cam.SetClippingRange(2 * self.radius, 6 * self.radius)
        matrix = cam.GetCompositeProjectionTransformMatrix(width / float(height), -1, 1)
        M = np.array([[matrix.GetElement(i, j) for j in range(4)] for i in range(4)])

        def to_win(pts):
            hom = np.c_[pts, np.ones(len(pts))] @ M.T
            ndc = hom[:, :3] / hom[:, 3:4]
            return ((ndc[:, 0] + 1) / 2 * width - 0.5,
                    (ndc[:, 1] + 1) / 2 * height - 0.5,
                    (ndc[:, 2] + 1) / 2)

        dz = 1.0 / (4 * self.radius)
        px = 2 * scale / height
        return to_win, dz, px


def _visible(points, image, to_win, tol):
    import numpy as np
    height, width = image.shape
    x, y, z = to_win(points)
    xi = np.clip(np.rint(x).astype(int), 0, width - 1)
    yi = np.clip(np.rint(y).astype(int), 0, height - 1)
    best = np.zeros(len(points))
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            best = np.maximum(best, image[np.clip(yi + dy, 0, height - 1), np.clip(xi + dx, 0, width - 1)])
    return z <= best + tol


def _runs(points2d, keep, counts):
    """Visible runs. Hidden gaps of up to 8 samples are closed so a line does not break into dashes."""
    import numpy as np
    if not len(counts):
        return []
    edge = np.repeat(np.arange(len(counts)), counts)
    keep = keep.copy()
    change = np.r_[True, (keep[1:] != keep[:-1]) | (edge[1:] != edge[:-1])]
    starts = np.nonzero(change)[0]
    ends = np.r_[starts[1:], len(keep)]
    length = ends - starts
    value = keep[starts]
    which = edge[starts]
    prev_ok = np.r_[False, value[:-1] & (which[:-1] == which[1:])]
    next_ok = np.r_[value[1:] & (which[1:] == which[:-1]), False]
    fill = ~value & (length <= 8) & prev_ok & next_ok
    for a, b in zip(starts[fill], ends[fill]):
        keep[a:b] = True
    change = np.r_[True, (keep[1:] != keep[:-1]) | (edge[1:] != edge[:-1])]
    starts = np.nonzero(change)[0]
    ends = np.r_[starts[1:], len(keep)]
    out = []
    for a, b in zip(starts, ends):
        if keep[a] and b - a >= 2:
            out.append(points2d[a:b])
    return out


def _view_lines(verts, faces, corners, points, counts, tangent, analytic, toward, right, up, image, to_win, dz, px, defl, name, fit, show_tangents=True, masks=None, span=None):
    import numpy as np
    lines = []
    if len(counts):
        tol = dz * (2.5 * px + defl)
        keep = _visible(points, image, to_win, tol)
        flat = np.c_[points @ right, points @ up]
        lines.extend(_analytic_lines(
            flat, keep, counts, tangent, analytic, right, up, px, show_tangents, span))
        for flag, style in ((False, 'vis'), (True, 'thin')):
            if flag and not show_tangents:
                continue
            mask = tangent == flag
            if not mask.any():
                continue
            index = np.nonzero(np.repeat(mask, counts))[0]
            runs = _runs(flat[index], keep[index], counts[mask])
            # Close breaks of about two pixels. Back edges stay out: they were not kept.
            bridged = bridge_gaps([[(float(x), float(y)) for x, y in run] for run in runs], 2.0 * px)
            for poly in bridged:
                if len(poly) < 2:
                    continue
                item = fit_chain(poly, style, ellipses=(fit and name == 'trimetric' and style == 'vis'), curves=fit, max_r=span)
                if item and _length(item) >= 1.5 * px:
                    lines.append(item)
    sil = _silhouettes(verts, faces, corners, toward)
    if len(sil):
        projected = np.stack([sil @ right, sil @ up], axis=-1)
        keep_len = np.linalg.norm(projected[:, 1] - projected[:, 0], axis=1) > 0.5 * px
        sil = sil[keep_len]
        projected = projected[keep_len]
        if masks and len(sil):
            outer = _outer_silhouettes(projected, masks)
            sil = sil[outer]
            projected = projected[outer]
    if len(sil):
        chains = _chain(projected, sil, 0.6 * px)
        for chain in chains:
            if len(chain) < 2:
                continue
            dense = _densify(np.array(chain), max(px, 1e-6))
            vis = _visible(dense, image, to_win, dz * (2.5 * px + defl))
            flat = np.c_[dense @ right, dense @ up]
            for run in _runs(flat, vis, np.array([len(dense)])):
                poly = [(float(x), float(y)) for x, y in run]
                item = fit_chain(poly, 'vis', ellipses=(fit and name == 'trimetric'), curves=fit, max_r=span)
                if item and _length(item) >= 1.5 * px:
                    lines.append(item)
    return lines


def _curve_too_wide(item, span):
    """True when a circle, arc, or ellipse is bigger than the view."""
    if not item or not span:
        return False
    if item.get('kind') in ('circle', 'arc'):
        return item['r'] > span
    if item.get('kind') == 'ellipse':
        return max(item['rx'], item['ry']) > span
    return False


def _analytic_lines(flat, keep, counts, tangent, analytic, right, up, px, show_tangents=True, span=None):
    """Circles and ellipses from the real edge. Those edges are then not fitted from samples."""
    import numpy as np
    if not analytic:
        return []
    spans = np.cumsum(np.r_[0, counts])
    out = []
    for i, info in enumerate(analytic):
        if not info:
            continue
        if tangent[i] and not show_tangents:
            a, b = int(spans[i]), int(spans[i + 1])
            keep[a:b] = False
            continue
        a, b = int(spans[i]), int(spans[i + 1])
        visible = keep[a:b]
        if visible.size < 2 or float(visible.mean()) < 0.45:
            continue
        # One visible run. A full rim that is mostly in view stays a whole circle or ellipse.
        runs = _param_runs(visible)
        if not runs:
            continue
        full = abs(info['u1'] - info['u0']) >= 2.0 * np.pi - 0.25 and float(visible.mean()) >= 0.8
        spans_u = [(info['u0'], info['u1'])] if full else [
            _param_span(info['u0'], info['u1'], b - a, run) for run in runs]
        style = 'thin' if tangent[i] else 'vis'
        for u0, u1 in spans_u:
            item = analytic_curve(info['o'], info['x'], info['y'], info['r'], u0, u1, right, up, style, partial=not full)
            if _curve_too_wide(item, span):
                item = None
            if item and _length(item) >= 1.5 * px:
                out.append(item)
        keep[a:b] = False
    return out


def _param_runs(visible):
    """Inclusive index pairs of contiguous visible samples."""
    import numpy as np
    runs = []
    start = None
    for i, flag in enumerate(visible):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= 2:
                runs.append((start, i - 1))
            start = None
    if start is not None and len(visible) - start >= 2:
        runs.append((start, len(visible) - 1))
    return runs


def _param_span(u0, u1, count, run):
    if count <= 1:
        return u0, u1
    a = u0 + (u1 - u0) * run[0] / (count - 1)
    b = u0 + (u1 - u0) * run[1] / (count - 1)
    return a, b


def _length(line):
    import math
    if line['kind'] == 'circle':
        return 2 * math.pi * line['r']
    if line['kind'] == 'ellipse':
        return 2 * math.pi * max(line['rx'], line['ry'])
    if line['kind'] == 'arc':
        return abs(line['a1'] - line['a0']) * line['r']
    pts = line['pts']
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


def _silhouettes(verts, faces, corners, toward):
    import numpy as np
    g = corners @ toward
    g = np.where(np.abs(g) < 1e-5, 1e-12, g)
    sign = g > 0
    cross = (sign.any(1) & ~sign.all(1)) & (np.abs(g).max(1) > 5e-4)
    if not cross.any():
        return np.zeros((0, 2, 3))
    ft, gt = faces[cross], g[cross]
    pieces = []
    for a, b in ((0, 1), (1, 2), (2, 0)):
        ga, gb = gt[:, a], gt[:, b]
        ok = (ga > 0) != (gb > 0)
        va, vb = ft[:, a], ft[:, b]
        swap = va > vb
        lo = np.where(swap, vb, va)
        hi = np.where(swap, va, vb)
        glo = np.where(swap, gb, ga)
        ghi = np.where(swap, ga, gb)
        t = glo / np.where(ok, glo - ghi, 1.0)
        point = verts[lo].astype(float) + t[:, None] * (verts[hi].astype(float) - verts[lo].astype(float))
        pieces.append((ok, point))
    (o0, p0), (o1, p1), (o2, p2) = pieces
    a = np.where(o0[:, None], p0, p1)
    b = np.where(o0[:, None] & o1[:, None], p1, p2)
    seg = np.stack([a, b], axis=1)
    seg = seg[np.linalg.norm(a - b, axis=1) > 1e-9]
    return seg


def _chain(projected, segs, tol):
    """Join 3-D silhouette segments whose 2-D ends are within tol. Returns 3-D polylines."""
    if not len(segs):
        return []
    links = []
    for i, seg in enumerate(segs):
        a = (float(projected[i, 0, 0]), float(projected[i, 0, 1]))
        b = (float(projected[i, 1, 0]), float(projected[i, 1, 1]))
        links.append((a, b, seg[0], seg[1]))
    # Reuse the 2-D gap joiner on the projected ends, then rebuild 3-D by index.
    polylines = bridge_gaps([[link[0], link[1]] for link in links], tol)
    # Each joined point is one of these ends. The first copy wins, same as argmin.
    flat3 = [p for link in links for p in (link[2], link[3])]
    index = {}
    slot = 0
    for link in links:
        for point in link[:2]:
            index.setdefault(point, slot)
            slot += 1
    out = []
    for poly in polylines:
        chain = []
        for point in poly:
            chain.append(flat3[index[point]])
        out.append(chain)
    return out
