"""Title-block project comes from the document, env, or local.toml, with a neutral default."""
import os

from sheet2d import settings as S


def test_neutral_defaults_without_local_toml(tmp_path):
    assert S.title_defaults(str(tmp_path), environ={}) == {'project': 'PROJECT'}


def test_local_toml_then_env(tmp_path):
    (tmp_path / 'local.toml').write_text('[drawing]\nproject = "ACME RIG"\n')
    assert S.title_defaults(str(tmp_path), environ={}) == {'project': 'ACME RIG'}
    d = S.title_defaults(str(tmp_path), environ={'DRAWING_PROJECT': 'OTHER'})
    assert d == {'project': 'OTHER'}


def test_spec_values_win(tmp_path):
    (tmp_path / 'local.toml').write_text('[drawing]\nproject = "ACME RIG"\n')
    info = S.title_info({'title': 'T', 'project': 'JOB X', 'drawn': None}, str(tmp_path), environ={})
    assert info['project'] == 'JOB X' and ('drawn' not in info or not info['drawn']) and info['title'] == 'T'


def test_sheet2d_has_no_hardcoded_product_names():
    root = os.path.join(os.path.dirname(__file__), '..', 'SRDrawingPDF', 'sheet2d')
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith('.py'):
                continue
            src = open(os.path.join(dirpath, name), encoding='utf-8').read()
            assert 'SteveCAD' not in src and 'ST185' not in src, name
