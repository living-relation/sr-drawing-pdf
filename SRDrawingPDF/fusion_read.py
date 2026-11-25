"""Read the open Fusion design for the fast views, in short steps.

Fusion's hang detector fires when one call runs too long, so the work is split:

  step 'list'  - visible bodies, their component and their placement (fast).
  step 'mesh'  - meshes for the next unique bodies, until the time budget is used.
                 Call again with the returned 'next' until 'done' is true.

Each unique body is meshed once, in its own component's coordinates, and every
occurrence reuses it through its placement. Only visible bodies are listed.
Nothing in the design is changed. Results go to files in out_dir so that the
drawing work can run outside Fusion (sheet2d.meshparts.load_fusion_dump).

Never sleeps or polls. Fusion units are centimetres; the files keep them.
"""
import array
import json
import os
import struct
import time

QUALITY = {
    'low': 'LowQualityTriangleMesh',
    'normal': 'NormalQualityTriangleMesh',
    'high': 'HighQualityTriangleMesh',
}


def _design():
    import adsk.core
    import adsk.fusion
    app = adsk.core.Application.get()
    doc = app.activeDocument
    if doc is None:
        raise RuntimeError('no open document')
    design = adsk.fusion.Design.cast(doc.products.itemByProductType('DesignProductType'))
    if design is None:
        raise RuntimeError('the active document has no design')
    return doc, design


def _visible_bodies(component):
    out = []
    for i in range(component.bRepBodies.count):
        body = component.bRepBodies.item(i)
        if body.isLightBulbOn and body.isVisible:
            out.append(i)
    return out


def list_step(out_dir):
    """Write occurrences.json: unique bodies and every visible placement."""
    t0 = time.perf_counter()
    doc, design = _design()
    root = design.rootComponent
    uniques = {}
    placements = []

    def add(component, occ_key, matrix):
        for index in _visible_bodies(component):
            key = '%s#%d' % (component.id, index)
            if key not in uniques:
                uniques[key] = {'key': key, 'comp': component.id, 'body': index, 'name': component.name}
            placements.append({'key': key, 'occ': occ_key, 'xf': matrix})

    identity = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]
    add(root, '', identity)
    occs = root.allOccurrences
    for i in range(occs.count):
        occ = occs.item(i)
        if not occ.isLightBulbOn or not occ.isVisible:
            continue
        add(occ.component, occ.fullPathName, list(occ.transform2.asArray()))
    data = {
        'document': doc.name,
        'units': 'cm',
        'bodies': list(uniques.values()),
        'placements': placements,
    }
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'occurrences.json'), 'w', encoding='utf-8') as handle:
        json.dump(data, handle)
    return {'bodies': len(uniques), 'placements': len(placements), 'seconds': time.perf_counter() - t0}


def mesh_step(out_dir, start=0, budget=3.0, quality='low'):
    """Mesh unique bodies from `start` until `budget` seconds pass. Writes mesh_<start>.bin."""
    import adsk.fusion
    t0 = time.perf_counter()
    _doc, design = _design()
    with open(os.path.join(out_dir, 'occurrences.json'), encoding='utf-8') as handle:
        bodies = json.load(handle)['bodies']
    comps = {}
    for i in range(design.allComponents.count):
        c = design.allComponents.item(i)
        comps[c.id] = c
    level = getattr(adsk.fusion.TriangleMeshQualityOptions, QUALITY.get(quality, QUALITY['low']))
    index = start
    tris = 0
    path = os.path.join(out_dir, 'mesh_%05d.bin' % start)
    with open(path, 'wb') as handle:
        while index < len(bodies) and time.perf_counter() - t0 < budget:
            item = bodies[index]
            index += 1
            comp = comps.get(item['comp'])
            if comp is None or item['body'] >= comp.bRepBodies.count:
                continue
            calc = comp.bRepBodies.item(item['body']).meshManager.createMeshCalculator()
            calc.setQuality(level)
            mesh = calc.calculate()
            nodes = array.array('f', mesh.nodeCoordinatesAsFloat)
            idx = array.array('i', mesh.nodeIndices)
            key = item['key'].encode('utf-8')
            handle.write(struct.pack('<I', len(key)))
            handle.write(key)
            handle.write(struct.pack('<II', len(nodes), len(idx)))
            nodes.tofile(handle)
            idx.tofile(handle)
            tris += len(idx) // 3
    return {
        'next': index, 'done': index >= len(bodies), 'total': len(bodies),
        'triangles': tris, 'file': os.path.basename(path), 'seconds': time.perf_counter() - t0,
    }
