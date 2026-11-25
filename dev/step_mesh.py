"""Read a STEP assembly into mesh parts for sheet2d.project. Dev only: needs OCP (cadquery-ocp).

Each solid becomes one ('mesh', ...) part. Shared shapes (repeated hardware) are
tessellated once by OCCT and placed by their location. Feature edges come from the
B-rep edges, not from the triangles: sharp edges are 'vis', tangent edges are 'thin',
seam edges are skipped. Curved faces keep their inner mesh edges with both normals so
each view can find its own silhouette.
"""
import gc
import math
import time


def load_step(path, deflection=None, angle=0.5):
    """(parts, info). deflection is in model units; None picks 0.2 % of the assembly size."""
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader

    t0 = time.perf_counter()
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_RetDone:
        raise ValueError('could not read %s' % path)
    reader.TransferRoots()
    shape = reader.OneShape()
    t_read = time.perf_counter() - t0

    t1 = time.perf_counter()
    size = _size(shape, False)
    if deflection is None:
        deflection = max(0.05, size * 0.002)
        BRepMesh_IncrementalMesh(shape, deflection, False, angle, True)
        # Surface bounds can be far larger than the parts. Re-mesh finer from the mesh bounds.
        fine = _size(shape, True)
        if fine < size * 0.7:
            size = fine
            deflection = max(0.05, size * 0.002)
    BRepMesh_IncrementalMesh(shape, deflection, False, angle, True)
    # Millions of small tuples: the cyclic garbage collector would rescan them over and over.
    was = gc.isenabled()
    gc.disable()
    try:
        parts = shape_parts(shape)
    finally:
        if was:
            gc.enable()
    t_mesh = time.perf_counter() - t1
    tris = sum(len(p[2]) for p in parts)
    return parts, {
        'read_s': t_read, 'mesh_s': t_mesh, 'solids': len(parts), 'triangles': tris,
        'size': size, 'deflection': deflection,
    }


def _size(shape, use_mesh):
    from OCP.BRepBndLib import BRepBndLib
    from OCP.Bnd import Bnd_Box
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, use_mesh)
    x0, y0, z0, x1, y1, z1 = box.Get()
    return max(x1 - x0, y1 - y0, z1 - z0)


def shape_parts(shape):
    from OCP.BRep import BRep_Tool
    from OCP.BRepLib import BRepLib
    from OCP.GeomAbs import GeomAbs_C0, GeomAbs_Plane
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED, TopAbs_SOLID, TopAbs_SHELL
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape, TopTools_IndexedMapOfShape
    from OCP.TopoDS import TopoDS

    solids = []
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()
    # Loose shells (surface bodies) are kept too.
    exp = TopExp_Explorer(shape, TopAbs_SHELL, TopAbs_SOLID)
    while exp.More():
        solids.append(exp.Current())
        exp.Next()

    parts = []
    for solid in solids:
        try:
            BRepLib.EncodeRegularity_s(solid, 1e-3)
        except Exception:
            pass
        pts = []
        tris = []
        smooth = []
        face_tri = {}
        fmap = TopTools_IndexedMapOfShape()
        TopExp.MapShapes_s(solid, TopAbs_FACE, fmap)
        fexp = TopExp_Explorer(solid, TopAbs_FACE)
        while fexp.More():
            face = TopoDS.Face_s(fexp.Current())
            fexp.Next()
            loc = TopLoc_Location()
            tri = BRep_Tool.Triangulation_s(face, loc)
            if tri is None:
                continue
            trsf = loc.Transformation()
            base = len(pts)
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                pts.append((p.X(), p.Y(), p.Z()))
            rev = face.Orientation() == TopAbs_REVERSED
            local = []
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                if rev:
                    b, c = c, b
                t = (base + a - 1, base + b - 1, base + c - 1)
                tris.append(t)
                local.append(t)
            face_tri[fmap.FindIndex(face)] = (tri, loc, base)
            if BRepAdaptor_Surface(face, False).GetType() != GeomAbs_Plane:
                smooth.extend(_inner_edges(pts, local))
        edges = []
        emap = TopTools_IndexedDataMapOfShapeListOfShape()
        TopExp.MapShapesAndAncestors_s(solid, TopAbs_EDGE, TopAbs_FACE, emap)
        for ei in range(1, emap.Extent() + 1):
            edge = TopoDS.Edge_s(emap.FindKey(ei))
            # Python iteration over an OCCT list is slow; First/Last cover a manifold edge.
            owners = emap.FindFromIndex(ei)
            count = owners.Size()
            faces = []
            if count:
                faces.append(TopoDS.Face_s(owners.First()))
            if count >= 2:
                faces.append(TopoDS.Face_s(owners.Last()))
            if not faces or BRep_Tool.Degenerated_s(edge):
                continue
            f0 = faces[0]
            if BRep_Tool.IsClosed_s(edge, f0):
                continue  # seam
            style = 'vis'
            if len(faces) >= 2:
                try:
                    if BRep_Tool.Continuity_s(edge, faces[0], faces[1]) != GeomAbs_C0:
                        style = 'thin'
                except Exception:
                    pass
            poly = _edge_poly(edge, f0, face_tri.get(fmap.FindIndex(f0)))
            if poly and len(poly) >= 2:
                edges.append((poly, style))
        if tris:
            parts.append(('mesh', pts, tris, edges, smooth))
    return parts


def _edge_poly(edge, face, info):
    from OCP.BRep import BRep_Tool
    if info is None:
        return None
    tri, loc, base = info
    poly = BRep_Tool.PolygonOnTriangulation_s(edge, tri, loc)
    if poly is None:
        return None
    nodes = poly.Nodes()
    trsf = loc.Transformation()
    out = []
    for i in range(nodes.Lower(), nodes.Upper() + 1):
        p = tri.Node(nodes.Value(i)).Transformed(trsf)
        out.append((p.X(), p.Y(), p.Z()))
    return out


def _inner_edges(pts, tris):
    """Edges shared by two triangles of one curved face: (a, b, n1, n2) for silhouettes."""
    seen = {}
    out = []
    for t in tris:
        a, b, c = (pts[i] for i in t)
        n = _tri_normal(a, b, c)
        for i, j in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            key = (i, j) if i < j else (j, i)
            other = seen.pop(key, None)
            if other is None:
                seen[key] = n
            else:
                out.append((pts[key[0]], pts[key[1]], other, n))
    return out


def _tri_normal(a, b, c):
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
    length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
    return (n[0] / length, n[1] / length, n[2] / length)

