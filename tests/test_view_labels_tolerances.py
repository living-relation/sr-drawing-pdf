"""View captions follow the sheet scale; dimensions and holes carry tolerances."""
import json

import pytest

from sheet2d import annotate as A
from sheet2d.canvas import Sheet, draw_dimension, draw_view_box
from sheet2d.commands import execute
from sheet2d.render import render_sheets
from sheet2d.model import DrawingDocument
from sheet2d.sample import build_sample


def _go(doc, command, **args):
    out = execute(doc, command, args)
    return out['document'], out['result']


def _base(scale='1:2'):
    doc, _r = _go(None, 'add_sheet', id='s1')
    doc, _r = _go(doc, 'set_title', field='scale', value=scale)
    return doc


def _texts(doc):
    sheets = render_sheets(DrawingDocument.from_dict(doc))
    return [[it[3] for it in sh.items if it[0] == 'tx'] for sh in sheets]


def test_scale_values():
    assert A.scale_value('1:2') == 0.5
    assert A.scale_value('SCALE 2 : 1') == 2.0
    assert A.scale_value('1/4') == 0.25
    assert A.scale_value('AS SHOWN') is None
    assert A.same_scale(None, '1:2')
    assert A.same_scale('1:2', '1:2') and A.same_scale('2:4', '1:2')
    assert not A.same_scale('1:1', '1:2')
    assert not A.same_scale('1:2', 'AS SHOWN')


@pytest.mark.parametrize('name', ['FRONT', 'TOP', 'RIGHT', 'LEFT', 'BACK', 'TRIMETRIC', 'ISOMETRIC', 'Front View'])
def test_default_views_at_sheet_scale_have_no_caption(name):
    doc = _base()
    doc, res = _go(doc, 'place_view', id='v1', sheet='s1', x=20, y=100, w=80, h=50, label=name)
    assert res['caption'] == []
    doc, res = _go(doc, 'place_view', id='v1', scale='1:2')
    assert res['caption'] == []


def test_named_view_at_sheet_scale_has_no_caption_unless_asked():
    doc = _base()
    doc, res = _go(doc, 'place_view', id='v1', sheet='s1', x=20, y=100, w=80, h=50, label='MOUNTING FACE')
    assert res['caption'] == []
    doc, res = _go(doc, 'place_view', id='v1', show_label=True)
    assert res['caption'] == ['MOUNTING FACE']


def test_view_at_other_scale_gets_a_subtitle():
    doc = _base()
    doc, res = _go(doc, 'place_view', id='v1', sheet='s1', x=20, y=100, w=80, h=50, label='FRONT', scale='1:1')
    assert res['caption'] == ['SCALE 1:1']
    doc, res = _go(doc, 'place_view', id='v2', sheet='s1', x=120, y=100, w=80, h=50, label='PORT FACE', scale='1:1')
    assert res['caption'] == ['PORT FACE', 'SCALE 1:1']
    doc, res = _go(doc, 'place_view', id='v1', show_label=True)
    assert res['caption'] == ['FRONT', 'SCALE 1:1']


def test_detail_and_section_keep_letters_and_show_scale_only_when_different():
    doc = _base()
    doc, res = _go(doc, 'place_view', id='d', sheet='s1', x=20, y=100, w=40, h=40, kind='detail', letter='b')
    assert res['caption'] == ['DETAIL B']
    doc, res = _go(doc, 'place_view', id='d', scale='2:1')
    assert res['caption'] == ['DETAIL B', 'SCALE 2:1']
    doc, res = _go(doc, 'place_view', id='s', sheet='s1', x=80, y=100, w=40, h=40, kind='section', letter='A')
    assert res['caption'] == ['SECTION A-A']
    doc, res = _go(doc, 'place_view', id='s', scale='1:2')
    assert res['caption'] == ['SECTION A-A']


def test_sheet_scale_override_and_as_shown():
    doc = _base()
    doc, _r = _go(doc, 'add_sheet', id='s2', scale='1:1')
    doc, res = _go(doc, 'place_view', id='v', sheet='s2', x=20, y=100, w=40, h=40, label='TOP', scale='1:1')
    assert res['caption'] == []
    doc, _r = _go(doc, 'add_sheet', id='s3', scale='AS SHOWN')
    doc, res = _go(doc, 'place_view', id='w', sheet='s3', x=20, y=100, w=40, h=40, label='TOP', scale='1:2')
    assert res['caption'] == ['SCALE 1:2']
    assert execute(doc, 'view_caption', {'id': 'w'})['result']['sheet_scale'] == 'AS SHOWN'


def test_render_draws_no_view_label_or_scale_at_sheet_scale():
    doc = _base()
    doc, _r = _go(doc, 'place_view', id='v1', sheet='s1', x=20, y=100, w=80, h=50, label='FRONT', scale='1:2')
    texts = _texts(doc)[0]
    assert 'FRONT' not in texts and not any(t.startswith('SCALE ') for t in texts)
    assert 'VIEW FRAME' not in texts


def test_view_box_caption_goes_under_the_frame():
    sh = Sheet()
    draw_view_box(sh, {'x': 10, 'y': 50, 'w': 40, 'h': 30, 'kind': 'detail', 'letter': 'B'}, ['DETAIL B', 'SCALE 2:1'])
    caps = [it for it in sh.items if it[0] == 'tx' and it[3] in ('DETAIL B', 'SCALE 2:1')]
    assert len(caps) == 2 and all(it[2] < 50 for it in caps)
    assert caps[0][8] is True and caps[1][8] is False


def test_bad_view_kind_rejected_and_letter_warnings():
    doc = _base()
    with pytest.raises(ValueError):
        _go(doc, 'place_view', sheet='s1', x=1, y=1, w=1, h=1, kind='exploded')
    doc, _r = _go(doc, 'place_view', id='a', sheet='s1', x=20, y=100, w=40, h=40, kind='detail')
    doc, _r = _go(doc, 'place_view', id='b', sheet='s1', x=80, y=100, w=40, h=40, kind='detail', letter='C')
    doc, _r = _go(doc, 'place_view', id='c', sheet='s1', x=140, y=100, w=40, h=40, kind='section', letter='C')
    warnings = execute(doc, 'check', {})['result']['warnings']
    assert any('detail view a has no letter' in w for w in warnings)
    assert any('view letter C is used more than once' in w for w in warnings)


def test_missing_sheet_scale_warns():
    doc, _r = _go(None, 'add_sheet', id='s1')
    doc, _r = _go(doc, 'place_view', id='v', sheet='s1', x=20, y=100, w=40, h=40)
    assert any('no scale' in w for w in execute(doc, 'check', {})['result']['warnings'])


@pytest.mark.parametrize('value,tol,expected', [
    (25, None, '25'),
    (25.4, None, '25.40'),
    ('25.00', {'kind': 'pm', 'value': 0.05}, '25.00 \u00b10.05'),
    ('25.0', {'kind': 'pm', 'value': 0.1}, '25.0 \u00b10.1'),
    ('6.6', {'kind': 'dev', 'plus': 0.1, 'minus': 0}, '6.6 +0.1/-0'),
    ('10.00', {'kind': 'dev', 'plus': 0.02, 'minus': 0.02}, '10.00 \u00b10.02'),
    ('140.00', {'kind': 'limits', 'plus': 0.05, 'minus': 0}, '140.05\n140.00'),
    ('20', {'kind': 'limits', 'upper': 20.1, 'lower': 19.9, 'decimals': 2}, '20.10\n19.90'),
    ('50.00', {'kind': 'ref'}, '(50.00)'),
    ('50.00', {'kind': 'basic'}, '50.00'),
])
def test_dimension_text(value, tol, expected):
    assert A.dim_text(value, tol) == expected


@pytest.mark.parametrize('tol', [
    {'kind': 'pm', 'value': 0}, {'kind': 'dev', 'plus': -1, 'minus': 0}, {'kind': 'dev', 'plus': 0, 'minus': 0},
    {'kind': 'limits', 'upper': 1, 'lower': 2}, {'kind': 'nope'}, 'tight',
])
def test_bad_tolerances_rejected(tol):
    with pytest.raises(ValueError):
        A.normalize_tol(tol)


def test_every_dimension_takes_an_optional_tolerance():
    doc = _base()
    doc, res = _go(doc, 'place_dimension', id='d1', sheet='s1', x1=20, y1=50, x2=70, y2=50, orient='h')
    assert res['text'] == '100' and res['tol'] is None
    doc, res = _go(doc, 'move_dimension', id='d1', tol={'kind': 'pm', 'value': 0.1}, decimals=1)
    assert res['text'] == '100.0 \u00b10.1'
    doc, res = _go(doc, 'move_dimension', id='d1', tol=None)
    assert res['tol'] is None and res['text'] == '100.0'
    doc, res = _go(doc, 'place_dimension', id='d2', sheet='s1', x1=20, y1=50, x2=20, y2=80, orient='v', value='12.70',
                   tol={'kind': 'dev', 'plus': 0.05, 'minus': 0})
    assert res['text'] == '12.70 +0.05/-0'
    assert json.loads(json.dumps(doc))['sheets'][0]['elements'][1]['tol']['kind'] == 'dev'


def test_dimension_uses_its_view_scale():
    doc = _base()
    doc, _r = _go(doc, 'place_view', id='det', sheet='s1', x=20, y=100, w=40, h=40, kind='detail', letter='B', scale='2:1')
    doc, res = _go(doc, 'place_dimension', id='d', sheet='s1', x1=20, y1=110, x2=40, y2=110, orient='h', view='det')
    assert res['text'] == '10'


def test_hole_tolerance_applies_to_every_hole_and_position_dimension():
    doc = _base()
    doc, res = _go(doc, 'set_hole_tolerance', size={'kind': 'dev', 'plus': 0.1, 'minus': 0},
                   position={'kind': 'pm', 'value': 0.05})
    assert res['hole_tol']['show'] == 'note'
    assert res['note'] == 'ALL HOLES UNLESS OTHERWISE SPECIFIED: HOLE SIZE +0.1/-0, HOLE POSITION \u00b10.05.'
    doc, res = _go(doc, 'place_hole_callout', id='h1', sheet='s1', count=4, dia=6.6, depth='THRU',
                   x=50, y=60, ax=40, ay=50)
    assert res['lines'] == ['4X \u23006.6 THRU']
    doc, res = _go(doc, 'set_hole_tolerance', show='callout')
    assert res['note'] == ''
    doc, res = _go(doc, 'move_hole_callout', id='h1')
    assert res['lines'] == ['4X \u23006.6 +0.1/-0 THRU', 'POSITION \u00b10.05']
    doc, res = _go(doc, 'place_hole_callout', id='h2', sheet='s1', dia=3, tol={'kind': 'pm', 'value': 0.02},
                   x=50, y=60, ax=40, ay=50)
    assert res['lines'][0] == '\u23003 \u00b10.02'
    doc, res = _go(doc, 'place_dimension', id='p', sheet='s1', x1=20, y1=50, x2=70, y2=50, orient='h',
                   role='hole_position', decimals=2)
    assert res['text'] == '100.00 \u00b10.05'
    doc, res = _go(doc, 'move_dimension', id='p', tol={'kind': 'pm', 'value': 0.2})
    assert res['text'] == '100.00 \u00b10.20'


def test_tapped_hole_callout_has_tap_drill_and_thread():
    doc = _base()
    doc, res = _go(doc, 'place_hole_callout', id='t', sheet='s1', count=2, thread='M4x0.7 - 6H', tap_drill=3.3,
                   drill_depth=12, thread_depth=10, x=50, y=60, ax=40, ay=50)
    assert res['lines'] == ['2X \u23003.3 TAP DRILL \u21a7 12', 'M4x0.7 - 6H \u21a7 10']
    with pytest.raises(ValueError):
        _go(doc, 'place_hole_callout', sheet='s1', x=1, y=1, ax=2, ay=2)


def test_hole_note_prints_last_in_the_notes_block():
    doc = _base()
    doc, _r = _go(doc, 'add_note', key='n1', text='FIRST NOTE')
    doc, _r = _go(doc, 'set_hole_tolerance', position={'kind': 'pm', 'value': 0.05})
    warnings = execute(doc, 'check', {})['result']['warnings']
    assert any('no notes block' in w for w in warnings)
    doc, _r = _go(doc, 'place_notes', id='nb', sheet='s1', x=20, y=90)
    texts = ' '.join(_texts(doc)[0])
    assert '2.' in texts and 'HOLE POSITION \u00b10.05' in texts
    doc, _r = _go(doc, 'set_hole_tolerance', clear=True)
    assert 'HOLE POSITION' not in ' '.join(_texts(doc)[0])


def test_hole_warnings():
    doc = _base()
    doc, _r = _go(doc, 'place_hole_callout', id='h', sheet='s1', dia=5, x=50, y=60, ax=40, ay=50)
    doc, _r = _go(doc, 'place_dimension', id='p', sheet='s1', x1=20, y1=50, x2=70, y2=50, role='hole_position')
    warnings = execute(doc, 'check', {})['result']['warnings']
    assert any('set_hole_tolerance' in w for w in warnings)
    assert any('hole position dimension p' in w for w in warnings)


def test_dimension_arrows_and_rotated_text():
    sh = Sheet()
    draw_dimension(sh, {'x1': 10, 'y1': 10, 'x2': 10, 'y2': 50, 'orient': 'v', 'offset': 8}, '40')
    assert sum(1 for it in sh.items if it[0] == 'tri') == 2
    text = [it for it in sh.items if it[0] == 'tx'][0]
    assert text[7] == 90.0 and text[1] < 2.0


def test_sample_follows_the_rules(tmp_path):
    doc = build_sample()
    caps = {v: execute(doc, 'view_caption', {'id': v})['result']['caption']
            for v in ('v1', 'v2', 'v3', 'v4', 'v5', 'v6', 'v7', 'v8')}
    assert caps['v1'] == caps['v2'] == caps['v3'] == caps['v4'] == []
    assert caps['v6'] == ['SECTION A-A'] and caps['v7'] == ['DETAIL B', 'SCALE 2:1']
    assert caps['v5'] == ['BUILD VIEW'] and caps['v8'] == ['SCALE 1:1']
    result = execute(doc, 'export_pdf', {'path': str(tmp_path / 's.pdf')})['result']
    assert result['warnings'] == []
