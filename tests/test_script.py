"""Checks for the SR Drawing PDF add-in that do not need Fusion."""
import json
import os
import re
import struct

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDIN = os.path.join(ROOT, 'SRDrawingPDF')


def test_manifest_valid():
    with open(os.path.join(ADDIN, 'SRDrawingPDF.manifest'), encoding='utf-8') as f:
        m = json.load(f)
    assert m['type'] == 'addin' and m['autodeskProduct'] == 'Fusion'
    assert m['author'] == 'Spark Robotic'
    assert 'SR Drawing PDF' in m['description']['']
    assert m.get('runOnStartup') is True


def test_script_is_cleaned_and_renamed():
    src = open(os.path.join(ADDIN, 'SRDrawingPDF.py'), encoding='utf-8').read()
    assert src.count('def run(') == 1
    assert 'is the active Document.' not in src
    assert 'ActiveDesignToPDF' not in src
    assert 'SR Drawing PDF' in src
    assert 'def setup_drawing(' in src
    assert 'def add_dimensions(' in src
    assert 'def start_export(' in src
    assert "CMD_ID = 'srDrawingPdfCmd'" in src
    assert 'Your code goes here' not in src


def test_no_machine_paths_in_script_tree():
    banned = re.compile(r'[A-Za-z]:\\?Users\\?[A-Za-z]', re.I)
    for dirpath, _, files in os.walk(ADDIN):
        for name in files:
            if name.endswith(('.png', '.svg', '.pyc', '.pyo')) or name == '.DS_Store':
                continue
            try:
                text = open(os.path.join(dirpath, name), encoding='utf-8').read()
            except UnicodeDecodeError:
                continue
            assert not banned.search(text), name


def _png_size(path):
    with open(path, 'rb') as f:
        assert f.read(8) == b'\x89PNG\r\n\x1a\n'
        length, typ = struct.unpack('>I4s', f.read(8))
        assert typ == b'IHDR'
        w, h = struct.unpack('>II', f.read(8))
        return w, h


def test_icons_present():
    d = os.path.join(ADDIN, 'resources', 'icon')
    for name, n in (('16x16', 16), ('32x32', 32)):
        assert _png_size(os.path.join(d, name + '.png')) == (n, n)


def test_fail_safe_drawing_flow():
    """The old flow called itemByProductType('DrawingProductType') on every activated document, which raises
    'failed to find product' for a design, and showed message boxes / slept inside documentActivated, which
    locked Fusion up. The handler must only use product_of(), never show UI and hand off to a custom event."""
    src = open(os.path.join(ADDIN, 'SRDrawingPDF.py'), encoding='utf-8').read()
    assert 'itemByProductType(' not in src.replace("itemByProductType throws", '').replace(
        'never call itemByProductType', '')
    assert 'def product_of(' in src
    h = src[src.index('class DrawingActivatedHandler'):src.index('class _SetupHandler')]
    assert 'messageBox' not in h and 'time.sleep' not in h and not re.search(r'^\s+raise\b', h, re.M)
    assert 'fireCustomEvent(SETUP_EVENT' in h and 'LISTEN_SECONDS' in h
    assert 'time.sleep' not in src
    start = src[src.index('def start_export('):src.index('class DrawingActivatedHandler')]
    assert 'is %s.' in start and "'DesignProductType'" in start


def test_product_of_never_raises():
    import importlib.util
    import sys
    import types
    adsk = types.ModuleType('adsk')
    for name in ('core', 'fusion', 'drawing'):
        m = types.ModuleType('adsk.' + name)
        setattr(adsk, name, m)
        sys.modules['adsk.' + name] = m
    sys.modules['adsk'] = adsk

    class _H:
        def __init__(self, *a):
            pass
    adsk.core.CommandCreatedEventHandler = adsk.core.InputChangedEventHandler = _H
    adsk.core.CommandEventHandler = adsk.core.DocumentEventHandler = adsk.core.CustomEventHandler = _H
    sys.path.insert(0, ADDIN)
    spec = importlib.util.spec_from_file_location('srdp_under_test', os.path.join(ADDIN, 'SRDrawingPDF.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    class P:
        def __init__(self, t):
            self.productType = t

    class Prods:
        def __init__(self, ts):
            self.items = [P(t) for t in ts]
            self.count = len(self.items)

        def item(self, i):
            return self.items[i]

    class Doc:
        def __init__(self, ts):
            self.products = Prods(ts)

    design = Doc(['DesignProductType', 'CAMProductType'])
    assert mod.product_of(design, 'DrawingProductType') is None
    assert mod.product_of(design, 'DesignProductType').productType == 'DesignProductType'
    assert mod.product_of(object(), 'DrawingProductType') is None  # broken document: still no exception
