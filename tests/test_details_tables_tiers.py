"""Block tolerance tiers, engineer-added detail views, suggestions, BOM anchors and splits."""
import pytest

from sheet2d import annotate as A
from sheet2d import canvas as D
from sheet2d.commands import execute
from sheet2d.detail import next_letter
from sheet2d.model import DrawingDocument
from sheet2d.render import render_sheets
from sheet2d.sample import build_sample


def _go(doc, command, **args):
    out = execute(doc, command, args)
    return out['document'], out['result']


def _base(scale='1:2', units='mm'):
    doc, _r = _go(None, 'add_sheet', id='s1')
    doc, _r = _go(doc, 'set_title', field='scale', value=scale)
    doc, _r = _go(doc, 'set_title', field='units', value=units)
    return doc


def _texts(doc, n=0):
    return [it[3] for it in render_sheets(DrawingDocument.from_dict(doc))[n].items if it[0] == 'tx']


# --- block tolerance tiers -------------------------------------------------

def test_default_tiers_by_units():
    assert A.block_tiers({'units': 'mm'}) == [
        {'decimals': 0, 'value': 0.5}, {'decimals': 1, 'value': 0.2}, {'decimals': 2, 'value': 0.05}]
    assert [t['decimals'] for t in A.block_tiers({'units': 'in'})] == [1, 2, 3]
    assert 'X.XX \u00b10.05' in A.block_text({'units': 'mm'})
    text = A.block_text({'units': 'in'})
    assert '.XXX \u00b1.005' in text and 'INCHES' in text


def test_tiers_are_configurable_and_print_in_the_title_block():
    doc = _base()
    doc, res = _go(doc, 'set_tolerance_tiers', tiers=[{'decimals': 1, 'value': 0.3}, {'decimals': 3, 'value': 0.01}],
                   angle=1)
    assert res['tiers'] == [{'decimals': 1, 'value': 0.3}, {'decimals': 3, 'value': 0.01}]
    block = execute(doc, 'title_block', {'sheet': 's1'})['result']
    assert 'X.X \u00b10.3' in block['tol_block'] and 'X.XXX \u00b10.01' in block['tol_block']
    assert 'ANGLES \u00b11\u00b0' in block['tol_block']
    texts = ' '.join(_texts(doc))
    assert 'X.XXX \u00b10.01' in texts and 'BLOCK TOLERANCE' in texts
    with pytest.raises(ValueError):
        _go(doc, 'set_tolerance_tiers', tiers=[{'decimals': 1, 'value': 0}])
    with pytest.raises(ValueError):
        _go(doc, 'set_tolerance_tiers', tiers=[{'decimals': 1, 'value': 0.1}, {'decimals': 1, 'value': 0.2}])
    doc, res = _go(doc, 'set_tolerance_tiers', clear=True)
    assert res['tiers'][0] == {'decimals': 0, 'value': 0.5}


def test_size_has_its_own_box():
    doc = _base()
    texts = _texts(doc)
    assert 'B' in texts and 'B (11x17)' not in texts and 'SIZE' in texts


def test_dimension_following_block_shows_no_tolerance():
    doc = _base()
    for decimals, value in ((0, 0.5), (1, 0.2), (2, 0.05)):
        doc, res = _go(doc, 'place_dimension', id='d%d' % decimals, sheet='s1', x1=20, y1=50, x2=70, y2=50,
                       orient='h', decimals=decimals, tol={'kind': 'pm', 'value': value})
        assert '\u00b1' not in res['text']
    doc, res = _go(doc, 'place_dimension', id='t', sheet='s1', x1=20, y1=50, x2=70, y2=50, orient='h',
                   decimals=2, tol={'kind': 'pm', 'value': 0.02})
    assert res['text'] == '100.00 \u00b10.02'
    doc, res = _go(doc, 'place_dimension', id='u', sheet='s1', x1=20, y1=50, x2=70, y2=50, orient='h',
                   decimals=2, tol={'kind': 'dev', 'plus': 0.05, 'minus': 0})
    assert res['text'] == '100.00 +0.05/-0'


def test_inch_dimensions_drop_the_leading_zero():
    doc = _base(scale='1:1', units='in')
    doc, res = _go(doc, 'place_dimension', id='d', sheet='s1', x1=0, y1=0, x2=10, y2=0, orient='h',
                   value='0.500', tol={'kind': 'pm', 'value': 0.001})
    assert res['text'] == '.500 \u00b1.001'
    doc, res = _go(doc, 'place_dimension', id='e', sheet='s1', x1=0, y1=0, x2=10, y2=0, orient='h',
                   value='1.250', tol={'kind': 'pm', 'value': 0.005})
    assert res['text'] == '1.250'


def test_sample_has_no_redundant_or_stacked_tolerance():
    texts = ' '.join(_texts(build_sample()))
    assert '100.00 \u00b10.05' not in texts and '140.05' not in texts
    assert '140.00' in texts and '64.0 \u00b10.1' in texts and 'POSITION' not in texts


# --- detail views ------------------------------------------------------------

def _with_parent():
    doc = _base()
    doc, _r = _go(doc, 'place_view', id='front', sheet='s1', x=20, y=120, w=100, h=60, label='FRONT')
    return doc


def test_next_letter_skips_i_o_q():
    assert next_letter([]) == 'A'
    assert next_letter(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']) == 'J'
    assert next_letter([chr(c) for c in range(65, 91)]) == 'AA'


def test_detail_view_options_follow_solidworks():
    doc = _with_parent()
    doc, res = _go(doc, 'add_detail_view', id='det', sheet='s1', parent='front', x=200, y=120, w=60, h=60,
                   cx=60, cy=150, r=8)
    assert res['letter'] == 'A' and res['scale'] == '1:1'          # custom default: 2x the parent scale
    assert res['caption'] == ['DETAIL A', 'SCALE 1:1']
    d = res['detail']
    assert (d['style'], d['outline'], d['boundary'], d['scale_mode']) == ('per_standard', 'full', 'circle', 'custom')
    assert d['pin_position'] is False and d['scale_hatch'] is False
    doc, res = _go(doc, 'add_detail_view', id='det', scale_mode='sheet')
    assert res['caption'] == ['DETAIL A']
    doc, res = _go(doc, 'add_detail_view', id='det', scale_mode='custom', scale='4:1', style='broken_circle',
                   outline='jagged', jagged_intensity=5, pin_position=True, scale_hatch=True, letter='c')
    assert res['caption'] == ['DETAIL C', 'SCALE 4:1'] and res['detail']['jagged_intensity'] == 5
    for bad in ({'style': 'fancy'}, {'outline': 'dotted'}, {'scale_mode': 'auto'}, {'jagged_intensity': 9},
                {'scale': 'big'}):
        with pytest.raises(ValueError):
            _go(doc, 'add_detail_view', id='det', **bad)
    with pytest.raises(ValueError):
        _go(doc, 'add_detail_view', sheet='s1', parent='front', x=1, y=1, w=9, h=9, boundary='profile',
            points=[[1, 1], [5, 1], [3, 4]], style='broken_circle')
    with pytest.raises(ValueError):
        _go(doc, 'add_detail_view', sheet='s1', parent='nope', x=1, y=1, w=9, h=9, cx=1, cy=1, r=1)


@pytest.mark.parametrize('style', ['per_standard', 'broken_circle', 'with_leader', 'no_leader', 'connected'])
def test_detail_styles_draw_the_letter_on_the_parent(style):
    doc = _with_parent()
    doc, _r = _go(doc, 'add_detail_view', id='det', sheet='s1', parent='front', x=200, y=120, w=60, h=60,
                  cx=60, cy=150, r=8, style=style, letter='K', outline='jagged')
    sheet = render_sheets(DrawingDocument.from_dict(doc))[0]
    assert sum(1 for it in sheet.items if it[0] == 'tx' and it[3] == 'K') == 1
    assert any(it[0] == 'pl' and it[2] == 'detail' for it in sheet.items)


def test_profile_detail_and_parent_scale_mode():
    doc = _with_parent()
    doc, res = _go(doc, 'add_detail_view', sheet='s1', parent='front', x=200, y=120, w=60, h=60,
                   boundary='profile', points=[[50, 140], [70, 140], [70, 160], [50, 160]],
                   scale_mode='parent', style='connected')
    assert res['caption'] == ['DETAIL A']


def test_engine_never_adds_a_detail_view():
    doc = _with_parent()
    doc, res = _go(doc, 'suggest_details', features=[
        {'id': 'g', 'view': 'front', 'x': 60, 'y': 150, 'size': 2.4, 'kind': 'o_ring_groove'},
        {'id': 'a', 'view': 'front', 'x': 90, 'y': 150, 'size': 1.0},
        {'id': 'b', 'view': 'front', 'x': 93, 'y': 152, 'size': 1.0},
        {'id': 'c', 'view': 'front', 'x': 96, 'y': 150, 'size': 1.0},
        {'id': 'far', 'view': 'front', 'x': 20, 'y': 125, 'size': 1.0},
    ])
    reasons = sorted(s['reason'] for s in res['added'])
    assert reasons == ['crowded_small_features', 'section_feature']
    crowded = [s for s in res['added'] if s['reason'] == 'crowded_small_features'][0]
    assert sorted(crowded['features']) == ['a', 'b', 'c'] and crowded['scale'] == '5:1'
    assert res['status_bar']['indicator'] == {'symbol': '!', 'color': 'yellow'}
    kinds = [el.get('kind') for el in doc['sheets'][0]['elements']]
    assert 'detail' not in kinds
    doc, again = _go(doc, 'suggest_details', features=[
        {'id': 'g', 'view': 'front', 'x': 60, 'y': 150, 'size': 2.4, 'kind': 'o_ring_groove'}])
    assert again['added'] == []
    doc, res = _go(doc, 'accept_suggestion', id=crowded['id'], sheet='s1', x=200, y=120, w=60, h=60)
    assert res['view']['caption'] == ['DETAIL A', 'SCALE 5:1']
    assert res['status_bar']['open'] == 1
    groove = [s for s in execute(doc, 'list_suggestions', {})['result']['suggestions'] if s['status'] == 'open'][0]
    doc, res = _go(doc, 'dismiss_suggestion', id=groove['id'])
    assert res['status_bar'] == {'indicator': None, 'open': 0, 'items': []}
    with pytest.raises(ValueError):
        _go(doc, 'accept_suggestion', id=groove['id'], sheet='s1', x=1, y=1, w=9, h=9)
    texts = _texts(doc)
    assert not any('crowded' in t or 'groove' in t for t in texts)


def test_outside_ai_can_add_a_suggestion():
    doc = _with_parent()
    doc, res = _go(doc, 'add_suggestion', view='front', text='thread relief needs a detail', cx=50, cy=140, r=6,
                   scale='4:1')
    assert res['status_bar']['open'] == 1
    with pytest.raises(ValueError):
        _go(doc, 'add_suggestion', view='front')


# --- BOM anchors, split, merge, row selection ----------------------------------

def _bom(n=12):
    doc = _base()
    for i in range(1, n + 1):
        doc, _r = _go(doc, 'add_bom_row', key='k%d' % i, pn='P-%d' % i, desc='PART', mat='AL',
                      thumbnail='thumbs/k%d.png' % i if i == 1 else None, component='tok%d' % i)
    return doc


def test_default_anchor_is_bottom_left_and_alt_is_above_title():
    doc = _bom(3)
    doc, res = _go(doc, 'place_bom', id='t', sheet='s1')
    seg = res['segment']
    assert seg['anchor'] == 'bottom_left' and abs(seg['bottom'] - 10.0) < 1e-6
    assert abs(seg['x1'] - (10 + sum(D.BOM_COLS_COMPACT))) < 1e-6
    doc, res = _go(doc, 'move_bom', id='t', anchor='above_title')
    seg = res['segment']
    assert abs(seg['bottom'] - 62.0) < 1e-6 and abs(seg['x1'] - 421.8) < 1e-6
    assert execute(doc, 'check', {})['result']['warnings'] == []


def test_split_above_and_below_keeps_headers_and_pieces_move():
    doc = _bom(12)
    doc, _r = _go(doc, 'place_bom', id='t1', sheet='s1')
    doc, res = _go(doc, 'split_table', id='t2', row='k5', where='below')
    rows = {s['id']: s['rows'] for s in res['segments']}
    assert rows['t1'] == ['k%d' % i for i in range(1, 6)] and rows['t2'] == ['k%d' % i for i in range(6, 13)]
    assert res['segments'][1]['continued'] is True and res['segments'][1]['anchor'] == 'above_title'
    doc, res = _go(doc, 'split_table', id='t3', row='k9', where='above', anchor='free', x1=300, ytop=250,
                   max_height=60)
    rows = {s['id']: s['rows'] for s in res['segments']}
    assert rows['t2'] == ['k6', 'k7', 'k8'] and rows['t3'][0] == 'k9'
    doc, res = _go(doc, 'move_bom', id='t3', x1=320, ytop=240)
    assert res['segment']['x1'] == 320 and res['segment']['rows'][0] == 'k9'
    texts = _texts(doc)
    assert texts.count('PART NUMBER') == 3 and texts.count('BILL OF MATERIALS (CONT.)') == 2
    doc, res = _go(doc, 'merge_tables', id='t2')
    rows = {s['id']: s['rows'] for s in res['segments']}
    assert rows['t1'] == ['k%d' % i for i in range(1, 9)]
    with pytest.raises(ValueError):
        _go(doc, 'merge_tables', id='t1')
    with pytest.raises(ValueError):
        _go(doc, 'split_table', row='k1', where='above')
    with pytest.raises(ValueError):
        _go(doc, 'split_table', row='nope')


def test_select_row_gives_thumbnail_and_highlights():
    doc = _bom(3)
    doc, _r = _go(doc, 'place_bom', id='t1', sheet='s1')
    doc, _r = _go(doc, 'place_view', id='v1', sheet='s1', x=200, y=150, w=50, h=40, components=['tok1', 'tok2'])
    doc, _r = _go(doc, 'place_view', id='v2', sheet='s1', x=260, y=150, w=50, h=40, components=['k2'])
    doc, _r = _go(doc, 'place_balloon', id='b1', sheet='s1', bom_key='k1', x=210, y=200, ax=220, ay=180)
    res = execute(doc, 'select_bom_row', {'key': 'k1'})['result']
    assert res['thumbnail'] == 'thumbs/k1.png' and res['table_piece'] == 't1'
    assert {(h['type'], h['element']) for h in res['highlight']} == {('view', 'v1'), ('balloon', 'b1')}
    res = execute(doc, 'select_bom_row', {'key': 'k2'})['result']
    assert res['thumbnail'] is None
    assert {h['element'] for h in res['highlight']} == {'v1', 'v2'}
