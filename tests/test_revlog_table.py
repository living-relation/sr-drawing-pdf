from sheet2d import canvas as D
from sheet2d import revs as R

LONG = 'Lug machined integral with the flange (N6 option 2), M5 screws + dowels deleted; first drawing issued (#279)'


def _texts(sh):
    return [it[3] for it in sh.items if it[0] == 'tx']


def test_long_text_wraps_never_truncates():
    rows = [R.RevEntry('A', 'Initial', 'DG', '14/10/26'), R.RevEntry('G', LONG, 'DG', '17/10/26')]
    sh = D.Sheet()
    x0, y0, x1, y1 = D.revlog_table(sh, rows)
    tx = _texts(sh)
    assert not any('...' in t for t in tx)
    assert ' '.join(tx).replace('  ', ' ').count('dowels') == 1
    assert round(x1 - x0, 6) == sum(D.REVLOG_COLS) and x1 == D.PW - 10 and y1 == D.PH - 10
    assert (y1 - y0) > D.REVLOG_RH * 4
    assert D.revlog_rect(rows) == (x0, y0, x1, y1)


def test_cap_counts_releases_and_font_shrinks_before_growing():
    rows = [R.RevEntry(letter, LONG * 2, 'DG', '17/10/26') for letter in 'BCDEFG']
    cells, hts, (hd, ho), tot = D.revlog_layout(rows)
    assert len(cells) == 6
    assert hd < D.REVLOG_H[0]
    assert tot <= D.REVLOG_MAX_H or hd == D.REVLOG_HMIN


def test_description_uses_the_column_width():
    from sheet2d.font import text_width_mm
    text = 'Added the bracket and updated the note list today'
    old_count = int((D.REVLOG_COLS[1] - 1.5) / (D.REVLOG_H[0] * 0.82))
    assert len(text) > old_count
    assert text_width_mm(text, D.REVLOG_H[0]) <= D.REVLOG_COLS[1] - 1.0
    cells, _hts, _fonts, _tot = D.revlog_layout([R.RevEntry('B', text, 'DG', '01/11/26')])
    assert cells[0][1] == [text]


def test_short_rows_keep_old_height():
    rows = [R.RevEntry('A', 'Initial', 'DG', '17/10/26')]
    assert D.revlog_rect(rows)[1] == D.PH - 10 - 3 * D.REVLOG_RH
