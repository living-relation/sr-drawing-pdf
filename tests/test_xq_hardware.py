"""A named screw draws its outline. A connector with the same shape does not."""
import pytest

pytest.importorskip('OCP')
pytest.importorskip('vtk')

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_DocumentTool
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

from sheet2d.engines import get_engine
from vieweng.xq import _is_fastener, name_is_fastener


def _write_named(path, parts):
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString('XmlXCAF'))
    app.NewDocument(TCollection_ExtendedString('MDTV-XCAF'), doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    for shape, name in parts:
        label = tool.AddShape(shape, False)
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
    writer = STEPCAFControl_Writer()
    writer.Transfer(doc, STEPControl_AsIs)
    assert writer.Write(path) == IFSelect_ReturnStatus.IFSelect_RetDone


def _holed(x):
    axis = gp_Ax2(gp_Pnt(x, 0, 0), gp_Dir(0, 0, 1))
    head = BRepPrimAPI_MakeCylinder(axis, 5.0, 8.0).Shape()
    socket = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(x, 0, 5), gp_Dir(0, 0, 1)), 2.0, 4.0).Shape()
    return BRepAlgoAPI_Cut(head, socket).Shape()


def test_fastener_names_are_screws_not_connectors():
    assert name_is_fastener('M3 SHCS')
    assert name_is_fastener('M5 socket head cap screw')
    assert name_is_fastener('hex nut')
    assert name_is_fastener('washer')
    assert name_is_fastener('standoff')
    assert name_is_fastener('stand-off')
    assert not name_is_fastener('USB connector')
    assert not name_is_fastener('handle bar')
    assert not name_is_fastener('DIN rail')
    assert not name_is_fastener('right rail')
    assert not name_is_fastener('')


def test_sr_fastener_style_codes_are_fasteners():
    for name in ('SBH-M3-0.5 x 8', 'SO-M3-6ZI', 'FHS-M3-8', 'NHX-M3', 'NTN-M4', 'WSL-M2',
                 'M3x06_ISO7045 v1', 'M4x10 phillips'):
        assert name_is_fastener(name), name
    for name in ('Screw Plug', 'USB insert', 'jam nut connector', 'terminal screw',
                 'Z carriage plate', 'pinion', 'ball nut housing plate', 'ball nut', 'lead screw'):
        assert not name_is_fastener(name), name


def test_a_screw_is_hardware_and_a_box_is_not():
    screw = _holed(0)
    assert _is_fastener(screw, 'M3 SHCS')
    assert not _is_fastener(screw, 'USB connector')
    assert not _is_fastener(screw, '')
    assert not _is_fastener(BRepPrimAPI_MakeBox(80, 60, 8).Shape(), 'M3 screw')


def test_the_socket_circle_is_left_out_of_a_screw_but_not_a_connector(tmp_path):
    step = tmp_path / 'parts.step'
    _write_named(str(step), [(_holed(0), 'USB connector'), (_holed(40), 'M3 SHCS')])
    views, _timing = get_engine('xq').project_views(('top',), step=str(step), mode='exact')
    circles = [line for line in views['top']['lines'] if line['kind'] == 'circle']
    usb = [line for line in circles if line['c'][0] < 20]
    screw = [line for line in circles if line['c'][0] > 20]
    assert usb and any(line['r'] < 3.5 for line in usb)
    assert any(line['r'] > 4.0 for line in usb)
    assert screw and all(line['r'] > 3.5 for line in screw)
    assert any(line['r'] > 4.0 for line in screw)


def _radii(view):
    return sorted(round(line['r'], 2) for line in view['lines'] if line['kind'] in ('circle', 'arc') and line['r'] < 30)


def test_quick_outline_matches_exact_on_a_screw(tmp_path):
    step = tmp_path / 'wide.step'
    plate = BRepPrimAPI_MakeBox(gp_Pnt(-40, -40, -80), gp_Pnt(500, 300, 0)).Shape()
    _write_named(str(step), [(_holed(0), 'M3 SHCS'), (plate, 'plate')])
    engine = get_engine('xq')
    exact, _t = engine.project_views(('top',), step=str(step), mode='exact')
    quick, _t = engine.project_views(('top',), step=str(step), mode='quick')
    assert _radii(exact['top']) == _radii(quick['top'])
    assert _radii(quick['top']) and all(r > 3.5 for r in _radii(quick['top']))


def _poly_length(line):
    pts = line.get('pts') or []
    total = 0.0
    for a, b in zip(pts, pts[1:]):
        total += ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
    return total


def test_a_handle_bar_keeps_its_side_lines(tmp_path):
    axis = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(1, 0, 0))
    bar = BRepPrimAPI_MakeCylinder(axis, 4.0, 80.0).Shape()
    step = tmp_path / 'bar.step'
    _write_named(str(step), [(bar, 'handle bar')])
    for mode in ('exact', 'quick'):
        views, _timing = get_engine('xq').project_views(('front',), step=str(step), mode=mode)
        long = [line for line in views['front']['lines'] if line['kind'] == 'poly' and _poly_length(line) > 40]
        assert long, mode


def test_the_silhouette_test_does_not_loop_every_screw():
    import time
    import numpy as np
    from vieweng.xq import _outer_silhouettes
    grid = np.zeros((64, 64), np.uint8)
    grid[16:48, 16:48] = 1
    masks = [(np.array([i * 20.0, 0.0]), 0.2, grid) for i in range(40)]
    segs = np.random.default_rng(0).random((20000, 2, 2)) * 800
    started = time.perf_counter()
    keep = _outer_silhouettes(segs, masks)
    elapsed = time.perf_counter() - started
    assert keep.shape == (20000,)
    assert elapsed < 0.5
