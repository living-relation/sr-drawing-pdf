"""editor_api finds the command module already loaded in this process."""
import importlib.util
import os
import sys
import types

ADDIN = os.path.join(os.path.dirname(__file__), '..', 'SRDrawingPDF')


def _load_addin(path=None, name='srdp_editor_api_under_test'):
    adsk = sys.modules.get('adsk')
    if adsk is None:
        adsk = types.ModuleType('adsk')
        sys.modules['adsk'] = adsk
    for name in ('core', 'fusion', 'drawing'):
        if not hasattr(adsk, name):
            sub = types.ModuleType('adsk.' + name)
            setattr(adsk, name, sub)
            sys.modules['adsk.' + name] = sub

    class _H:
        def __init__(self, *a):
            pass

    adsk.core.CommandCreatedEventHandler = adsk.core.InputChangedEventHandler = _H
    adsk.core.CommandEventHandler = adsk.core.DocumentEventHandler = adsk.core.CustomEventHandler = _H
    spec = importlib.util.spec_from_file_location(name, path or os.path.join(ADDIN, 'SRDrawingPDF.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_editor_api_reuses_sys_modules():
    from sheet2d import commands as commands
    mod = _load_addin()
    before = list(sys.path)
    first = mod.editor_api()
    second = mod.editor_api()
    assert first is commands
    assert second is first
    assert sys.modules['sheet2d.commands'] is commands
    assert sys.path == before


def test_editor_api_follows_a_symlinked_addin_folder(tmp_path):
    """A junction (or symlink) and the real folder are the same add-in."""
    link = tmp_path / 'junction'
    link.symlink_to(ADDIN, target_is_directory=True)
    linked = str(link / 'SRDrawingPDF.py')
    real = os.path.join(ADDIN, 'SRDrawingPDF.py')
    assert os.path.abspath(linked) != os.path.abspath(real)
    assert os.path.realpath(linked) == os.path.realpath(real)
    from sheet2d import commands as commands
    mod = _load_addin(linked, 'srdp_via_junction')
    before = list(sys.path)
    api = mod.editor_api()
    assert api is commands
    assert os.path.realpath(api.__file__) == os.path.realpath(commands.__file__)
    assert sys.path == before


def test_button_module_does_not_import_sheet2d_at_load():
    src = open(os.path.join(ADDIN, 'SRDrawingPDF.py'), encoding='utf-8').read()
    head = src.split('def run(', 1)[0]
    assert 'import sheet2d' not in head
    assert 'def editor_api(' in src
    assert 'def start_export(' in src
