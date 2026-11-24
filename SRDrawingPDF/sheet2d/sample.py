"""A short two-sheet sample built only through the command API.

The parts are stand-ins so the public repo does not copy a filed package.
The sheet chrome (border, zones, title block, rev table, BOM, notes, balloons)
is what the sample is for. View frames are empty; the dimensions and hole
callouts sit on stand-in points to show the tolerance rules.
"""
from urllib.parse import quote

from .commands import execute

_THUMB_COLORS = (
    '#8aa2b2', '#c4a574', '#7d9a78', '#b07d7d', '#8e8aa8', '#c48b5a', '#6f8f8a',
    '#a3a06a', '#7f93a8', '#b08968', '#9a7f8e', '#6e8b74', '#a67c52', '#7a8494',
)


def _thumb(pn, color):
    """A small stand-in picture for the editor. Not a photo of the part."""
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='160' height='110' viewBox='0 0 160 110'>"
        "<rect width='160' height='110' fill='#fbf9f4'/>"
        "<rect x='30' y='16' width='100' height='56' fill='%s' stroke='#222' stroke-width='3'/>"
        "<text x='80' y='96' text-anchor='middle' font-size='14' font-family='sans-serif' fill='#222'>%s</text>"
        "</svg>"
    ) % (color, pn)
    return 'data:image/svg+xml,' + quote(svg)


def _run(doc, command, **args):
    out = execute(doc, command, args)
    return out['document'], out['result']


def build_sample():
    """Return a drawing dict for a two-sheet size B sample."""
    doc, _result = _run(None, 'add_sheet', id='s1', name='Sheet 1')
    doc, _result = _run(doc, 'add_sheet', id='s2', name='Sheet 2', scale='AS SHOWN')
    fields = (
        ('project', 'SPARK ROBOTIC'),
        ('title', 'SAMPLE BRACKET ASSEMBLY'),
        ('pn', 'SR-SAMPLE-100'),
        ('material', 'SEE BOM'),
        ('scale', '1:2'),
        ('units', 'mm'),
        ('date', '2026-11-19'),
        ('source', 'SR-SAMPLE-100.step'),
    )
    for field, value in fields:
        doc, _result = _run(doc, 'set_title', field=field, value=value)
    doc, _result = _run(
        doc, 'add_revision', rev='A', desc='Initial', by='DG', date='2026-11-01')
    doc, _result = _run(
        doc, 'add_revision', rev='B',
        desc='Bracket width updated and the note list added', by='DG', date='2026-11-09')
    doc, _result = _run(
        doc, 'add_revision', rev='C',
        desc='Sample release for the sheet editor', by='DG', date='2026-11-19')

    rows = [
        ('p1', 1, 1, 'SR-S-101', 'BRACKET', '6061-T6 AL', True),
        ('p2', 2, 1, 'SR-S-102', 'PLATE', '6061-T6 AL', True),
        ('p3', 3, 2, 'SR-S-103', 'PIN', 'A2 STAINLESS', True),
        ('p4', 4, 4, 'SR-S-104', 'SCREW, M4 x 10', 'A2 STAINLESS', True),
        ('p5', 5, 4, 'SR-S-105', 'WASHER, M4', 'A2 STAINLESS', False),
        ('p6', 6, 1, 'SR-S-106', 'COVER, SEE NOTE 2', 'ABS', True),
        ('p7', 7, 1, 'SR-S-107', 'GASKET', 'NBR 70', True),
        ('p8', 8, 2, 'SR-S-108', 'STANDOFF', 'NYLON', True),
        ('p9', 9, 1, 'SR-S-109', 'LABEL', 'POLYESTER', True),
        ('p10', 10, 6, 'SR-S-110', 'RIVET', 'ALUMINIUM', True),
        ('p11', 11, 1, 'SR-S-111', 'CLIP', 'A2 STAINLESS', True),
        ('p12', 12, 2, 'SR-S-112', 'SPACER', 'NYLON', True),
        ('p13', 13, 1, 'SR-S-113', 'PLUG', 'BRASS', True),
        ('p14', 14, 1, 'SR-S-114', 'CAP', 'ABS', True),
    ]
    for key, item, qty, pn, desc, mat, shown in rows:
        doc, _result = _run(
            doc, 'add_bom_row', key=key, item=item, qty=qty, pn=pn, desc=desc, mat=mat, shown=shown,
            component=key, thumbnail=_thumb(pn, _THUMB_COLORS[item - 1]))

    # Default anchor: bottom-left corner of the frame. The table is split below
    # item 8 and the second piece sits on the other anchor, right corner above
    # the title block. Each piece keeps its header.
    doc, _result = _run(doc, 'place_bom', id='bom1', sheet='s1', anchor='bottom_left')
    doc, _result = _run(doc, 'split_table', id='bom2', row='p8', where='below', anchor='above_title')

    notes = (
        ('n1', 'SAMPLE PACKAGE FOR THE SHEET EDITOR. THE VIEW FRAMES ARE EMPTY.'),
        ('n2', 'AN ITEM MARKED NOT SHOWN HAS NO ITEM BALLOON.'),
        ('n3', 'A NOTE FLAG USES THE NOTE NUMBER.'),
    )
    for key, text in notes:
        doc, _result = _run(doc, 'add_note', key=key, text=text)
    doc, _result = _run(doc, 'place_notes', id='notes1', sheet='s1', x=18, y=104, width=120)

    # Views at the sheet scale (1:2 in the title block) get no label. Default
    # views (front, top, right, trimetric) get no label either. The section at
    # the sheet scale shows only its letters. No detail view is added: the
    # engine only suggests one (see suggest_details below).
    views = (
        ('v1', 's1', 18, 175, 90, 52, {'label': 'FRONT', 'components': ['p1', 'p4']}),
        ('v2', 's1', 116, 175, 90, 52, {'label': 'TOP', 'components': ['p2']}),
        ('v3', 's1', 18, 112, 90, 52, {'label': 'RIGHT', 'components': ['p3']}),
        ('v4', 's1', 116, 108, 100, 58, {'label': 'TRIMETRIC', 'components': ['p1', 'p6']}),
        ('v6', 's1', 300, 112, 70, 48, {'kind': 'section', 'letter': 'A', 'components': ['p7']}),
        ('v5', 's2', 22, 130, 150, 90, {'label': 'BUILD VIEW', 'show_label': True}),
        ('v8', 's2', 200, 130, 90, 60, {'label': 'FRONT', 'scale': '1:1'}),
    )
    for vid, sheet, x, y, w, h, extra in views:
        doc, _result = _run(doc, 'place_view', id=vid, sheet=sheet, x=x, y=y, w=w, h=h, **extra)

    # One hole tolerance for the file. Only the part that differs from the block
    # tolerance prints: the size (+0.1/-0) does, the position (±0.05, the same
    # as X.XX) does not.
    doc, _result = _run(
        doc, 'set_hole_tolerance', size={'kind': 'dev', 'plus': 0.1, 'minus': 0},
        position={'kind': 'pm', 'value': 0.05}, show='both')
    dims = (
        ('d1', dict(x1=28, y1=183, x2=98, y2=183, orient='h', offset=-6)),
        ('d2', dict(x1=38, y1=205, x2=88, y2=205, orient='h', offset=14, role='hole_position', decimals=2)),
        ('d3', dict(x1=98, y1=183, x2=98, y2=215, orient='v', offset=-8, decimals=1,
                    tol={'kind': 'pm', 'value': 0.1})),
        ('d4', dict(x1=126, y1=185, x2=196, y2=185, orient='h', offset=-6, decimals=2)),
    )
    for did, extra in dims:
        doc, _result = _run(doc, 'place_dimension', id=did, sheet='s1', **extra)
    doc, _result = _run(
        doc, 'place_hole_callout', id='h1', sheet='s1', count=4, dia=6.6, depth='THRU',
        x=44, y=234, ax=38, ay=205)
    doc, _result = _run(
        doc, 'place_hole_callout', id='h2', sheet='s1', count=2, thread='M4x0.7 - 6H', tap_drill=3.3,
        drill_depth=12, thread_depth=10, x=150, y=234, ax=160, ay=205)

    balloons = (
        ('b1', 'p1', 210, 155, 190, 145),
        ('b2', 'p2', 230, 130, 200, 125),
        ('b3', 'p3', 200, 96, 175, 118),
        ('b4', 'p6', 200, 175, 185, 155),
    )
    for bid, key, x, y, ax, ay in balloons:
        doc, _result = _run(
            doc, 'place_balloon', id=bid, sheet='s1', bom_key=key, x=x, y=y, ax=ax, ay=ay)
    doc, _result = _run(
        doc, 'place_note_flag', id='f1', sheet='s1', note_key='n1', x=168, y=90, ax=140, ay=100)
    # Suggestions for the engineer. They show in the status bar, not on the sheet.
    doc, _result = _run(doc, 'suggest_details', features=[
        {'id': 'groove1', 'view': 'v6', 'x': 335, 'y': 136, 'size': 2.4, 'kind': 'o_ring_groove'},
        {'id': 'c1', 'view': 'v2', 'x': 180, 'y': 200, 'size': 1.0, 'kind': 'hole'},
        {'id': 'c2', 'view': 'v2', 'x': 184, 'y': 203, 'size': 1.0, 'kind': 'hole'},
        {'id': 'c3', 'view': 'v2', 'x': 188, 'y': 200, 'size': 0.8, 'kind': 'chamfer'},
    ])
    return doc
