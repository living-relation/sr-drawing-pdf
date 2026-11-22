"""View captions, dimension tolerances, and the drawing-wide hole tolerance.

Rules (Daniel, Nov 22 2026):

- The sheet scale is set once, in the title block (or the sheet's own scale).
- A view at the sheet scale gets no view label and no scale label.
- Default views (front, top, right, left, back, bottom, iso, trimetric, ...)
  get no label.
- A view gets a subtitle when its scale differs from the sheet scale, or when
  the user asks for one (show_label).
- Detail and section views keep their letter labels. Their scale shows only
  when it differs from the sheet scale.
- Detail views are never added by the engine. It may only suggest one
  (see suggest.py); the engineer decides.
- The block (title-block) tolerance is set by the number of decimals on a
  dimension: X / X.X / X.XX in mm, .X / .XX / .XXX in inches. The tiers are
  configurable and print in their own box in the title block.
- A dimension that follows the block tolerance prints no tolerance text.
  A tolerance set on one annotation prints only when it differs from the
  block tolerance for that dimension's decimals.
- One hole tolerance (size and position) can be set for the whole file. It
  prints (in a hole note, in each hole callout, or both) only where it
  differs from the block tolerance. Hole callouts always carry thread specs.
"""
import math

VIEW_KINDS = ('standard', 'detail', 'section', 'auxiliary')

# Default projected and pictorial views. These never get a name label.
DEFAULT_VIEW_NAMES = frozenset((
    'FRONT', 'TOP', 'BOTTOM', 'LEFT', 'RIGHT', 'BACK', 'REAR', 'SIDE',
    'ISO', 'ISOMETRIC', 'TRIMETRIC', 'DIMETRIC', 'PICTORIAL', 'BASE', 'HOME',
))

TOL_KINDS = ('pm', 'dev', 'limits', 'basic', 'ref')
HOLE_TOL_SHOW = ('note', 'callout', 'both')


DEFAULT_TIERS = {
    'mm': [{'decimals': 0, 'value': 0.5}, {'decimals': 1, 'value': 0.2}, {'decimals': 2, 'value': 0.05}],
    'in': [{'decimals': 1, 'value': 0.1}, {'decimals': 2, 'value': 0.01}, {'decimals': 3, 'value': 0.005}],
}
DEFAULT_ANGLE_TOL = 0.5


def units_key(units):
    u = str(units or 'mm').strip().lower()
    return 'in' if u in ('in', 'inch', 'inches', '"') else 'mm'


def normalize_tiers(tiers):
    """[{'decimals': n, 'value': v}, ...] sorted by decimals. Each decimals once, value > 0."""
    out = {}
    for t in tiers or []:
        d = int(t['decimals'])
        v = float(t['value'])
        if d < 0 or d > 6:
            raise ValueError('tier decimals must be 0 to 6')
        if v <= 0:
            raise ValueError('tier tolerance must be greater than 0')
        if d in out:
            raise ValueError('decimals %d is listed twice' % d)
        out[d] = v
    if not out:
        raise ValueError('give at least one tier')
    return [{'decimals': d, 'value': out[d]} for d in sorted(out)]


def block_tiers(props):
    """The tiers in force for a drawing: its own, else the defaults for its units."""
    tiers = props.get('tol_tiers')
    if tiers:
        return normalize_tiers(tiers)
    return [dict(t) for t in DEFAULT_TIERS[units_key(props.get('units'))]]


def block_value(props, decimals):
    """The block ± tolerance for a dimension shown with `decimals` digits, or None."""
    for t in block_tiers(props):
        if t['decimals'] == decimals:
            return t['value']
    return None


def _tier_pattern(decimals, inch):
    if inch:
        return '.' + 'X' * decimals if decimals else 'X'
    return 'X' + ('.' + 'X' * decimals if decimals else '')


def fmt_tol_value(v, inch):
    s = ('%.6f' % v).rstrip('0').rstrip('.')
    if inch and s.startswith('0.'):
        s = s[1:]
    return s


def block_text(props):
    """The text of the tolerance box in the title block, built from the tiers."""
    inch = units_key(props.get('units')) == 'in'
    tiers = block_tiers(props)
    parts = ['%s \u00b1%s' % (_tier_pattern(t['decimals'], inch), fmt_tol_value(t['value'], inch)) for t in tiers]
    lines = ['DIMENSIONS ARE IN %s' % ('INCHES' if inch else 'MILLIMETERS'), 'TOLERANCES:']
    row = '  '
    for p in parts:
        if len(row) + len(p) > 34 and row.strip():
            lines.append(row.rstrip())
            row = '  '
        row += p + '    '
    if row.strip():
        lines.append(row.rstrip())
    ang = props.get('tol_angle')
    ang = DEFAULT_ANGLE_TOL if ang in (None, '') else float(ang)
    lines.append('  ANGLES \u00b1%s\u00b0' % fmt_tol_value(ang, False))
    lines.append('SURFACE FINISH Ra %s' % ('125 \u00b5in' if inch else '3.2 \u00b5m'))
    lines.append('INTERPRET PER ASME Y14.5-2018')
    return '\n'.join(lines)


def tol_matches_block(tol, props, decimals):
    """True when a tolerance is the same as the block tolerance for these decimals."""
    tol = normalize_tol(tol)
    if tol is None:
        return True
    bv = block_value(props, decimals)
    if bv is None:
        return False
    if tol['kind'] == 'pm':
        return abs(tol['value'] - bv) < 1e-9
    if tol['kind'] == 'dev' and abs(tol['plus'] - tol['minus']) < 1e-9:
        return abs(tol['plus'] - bv) < 1e-9
    return False


def scale_value(text):
    """A ratio like '1:2' or '2:1' as a number (0.5, 2.0). None if not a ratio."""
    if text in (None, ''):
        return None
    if isinstance(text, (int, float)) and not isinstance(text, bool):
        return float(text) if text > 0 else None
    s = str(text).strip().upper().replace('SCALE', '').replace(' ', '')
    for sep in (':', '/'):
        if sep in s:
            a, _, b = s.partition(sep)
            try:
                a, b = float(a), float(b)
            except ValueError:
                return None
            return a / b if a > 0 and b > 0 else None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


def same_scale(view_scale, sheet_scale):
    """True when the view has no scale of its own or it matches the sheet scale."""
    if view_scale in (None, ''):
        return True
    a = scale_value(view_scale)
    b = scale_value(sheet_scale)
    if a is None or b is None:
        return str(view_scale).strip().upper() == str(sheet_scale or '').strip().upper()
    return abs(a - b) <= 1e-9 * max(a, b)


def is_default_name(label):
    s = str(label or '').strip().upper()
    for tail in (' VIEW',):
        if s.endswith(tail):
            s = s[:-len(tail)].strip()
    return s in DEFAULT_VIEW_NAMES


def view_caption(el, sheet_scale):
    """The caption lines drawn under a view. [] means no caption."""
    kind = el.get('kind') or 'standard'
    scale = el.get('scale')
    differs = not same_scale(scale, sheet_scale)
    scale_line = ('SCALE %s' % str(scale).strip().upper()) if differs else None
    letter = str(el.get('letter') or '').strip().upper()
    label = str(el.get('label') or '').strip().upper()
    if kind == 'detail':
        head = 'DETAIL %s' % letter if letter else (label or 'DETAIL')
        return [head] + ([scale_line] if scale_line else [])
    if kind == 'section':
        head = 'SECTION %s-%s' % (letter, letter) if letter else (label or 'SECTION')
        return [head] + ([scale_line] if scale_line else [])
    want = bool(el.get('show_label'))
    lines = []
    if want and label:
        lines.append(label)
    elif differs and label and not is_default_name(label):
        lines.append(label)
    elif kind == 'auxiliary' and letter:
        lines.append('VIEW %s' % letter)
    if scale_line:
        lines.append(scale_line)
    return lines


def _num(v):
    if v is None or v == '':
        return None
    return float(v)


def normalize_tol(tol):
    """Check a tolerance dict and return a clean copy. None means general tolerance.

    {'kind': 'pm', 'value': 0.05}               25.00 ±0.05
    {'kind': 'dev', 'plus': 0.05, 'minus': 0}    25.00 +0.05/-0
    {'kind': 'limits', 'plus': 0.05, 'minus': 0.02}  stacked limits from the nominal
    {'kind': 'limits', 'upper': 25.05, 'lower': 24.98}
    {'kind': 'basic'}   boxed basic dimension (position comes from a frame)
    {'kind': 'ref'}     (25.00) reference
    Optional 'decimals' sets the digits shown.
    """
    if tol in (None, '', 'general'):
        return None
    if not isinstance(tol, dict):
        raise ValueError('tol must be a dict or null')
    kind = tol.get('kind') or ('pm' if 'value' in tol else 'dev' if ('plus' in tol or 'minus' in tol) else None)
    if kind not in TOL_KINDS:
        raise ValueError('tol kind must be one of %s' % ', '.join(TOL_KINDS))
    out = {'kind': kind}
    if tol.get('decimals') is not None:
        out['decimals'] = int(tol['decimals'])
    if kind == 'pm':
        v = _num(tol.get('value'))
        if v is None or v <= 0:
            raise ValueError('a ± tolerance needs a value greater than 0')
        out['value'] = v
    elif kind in ('dev', 'limits'):
        if kind == 'limits' and ('upper' in tol or 'lower' in tol):
            up, lo = _num(tol.get('upper')), _num(tol.get('lower'))
            if up is None or lo is None or up <= lo:
                raise ValueError('limits need upper greater than lower')
            out['upper'], out['lower'] = up, lo
        else:
            plus, minus = _num(tol.get('plus')) or 0.0, _num(tol.get('minus')) or 0.0
            if plus < 0 or minus < 0:
                raise ValueError('plus and minus are sizes; give both as 0 or more')
            if plus == 0 and minus == 0:
                raise ValueError('plus and minus cannot both be 0')
            out['plus'], out['minus'] = plus, minus
    return out


def _decimals_of(tol, nominal_text):
    if tol and tol.get('decimals') is not None:
        return tol['decimals']
    if '.' in nominal_text:
        return len(nominal_text.split('.', 1)[1])
    return 0


def _f(v, d):
    return ('%.' + str(d) + 'f') % v


def _t(v, d):
    """A deviation: at least the nominal's digits, more when needed. 0 stays 0."""
    if v == 0:
        return '0'
    for extra in range(d, 5):
        s = _f(v, extra)
        if abs(float(s) - v) < 1e-9:
            return s
    return _f(v, 4)


def dim_text(value, tol, prefix='', decimals=None, props=None):
    """Dimension text as one or two lines. value may be a number or text.

    With props (the drawing properties), a tolerance equal to the block
    tolerance for the shown decimals is dropped, and inch values lose the
    leading zero.
    """
    tol = normalize_tol(tol)
    inch = props is not None and units_key(props.get('units')) == 'in'
    if props is not None and tol is not None and tol['kind'] in ('pm', 'dev'):
        shown = _shown_decimals(value, tol, decimals)
        if tol_matches_block(tol, props, shown):
            tol = None
    text = _dim_text(value, tol, prefix, decimals)
    if inch:
        text = '\n'.join(_strip_lead(line, prefix) for line in text.split('\n'))
    return text


def _shown_decimals(value, tol, decimals):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if decimals is not None:
            return decimals
        if tol and tol.get('decimals') is not None:
            return tol['decimals']
        return 2 if value != int(value) else 0
    s = str(value)
    return len(s.split('.', 1)[1]) if '.' in s else 0


def _strip_lead(line, prefix):
    out = []
    for word in line.split(' '):
        w = word
        for lead in (prefix + '0.', '\u00b10.', '+0.', '-0.', '(0.', '0.'):
            if lead and w.startswith(lead):
                w = lead[:-2] + '.' + w[len(lead):]
                break
        out.append(w)
    line = ' '.join(out)
    return line.replace('/-0.', '/-.')


def _dim_text(value, tol, prefix='', decimals=None):
    tol = normalize_tol(tol)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        d = decimals if decimals is not None else (tol or {}).get('decimals', 2 if value != int(value) else 0)
        nominal = float(value)
        ntext = _f(nominal, d)
    else:
        ntext = str(value)
        try:
            nominal = float(ntext)
        except ValueError:
            nominal = None
        d = _decimals_of(tol, ntext)
    base = prefix + ntext
    if tol is None:
        return base
    kind = tol['kind']
    if kind == 'pm':
        return '%s \u00b1%s' % (base, _t(tol['value'], d))
    if kind == 'dev':
        if tol['plus'] == tol['minus']:
            return '%s \u00b1%s' % (base, _t(tol['plus'], d))
        return '%s +%s/-%s' % (base, _t(tol['plus'], d), _t(tol['minus'], d))
    if kind == 'limits':
        if 'upper' in tol:
            up, lo = tol['upper'], tol['lower']
        else:
            if nominal is None:
                raise ValueError('limits from plus/minus need a numeric value')
            up, lo = nominal + tol['plus'], nominal - tol['minus']
        return '%s%s\n%s%s' % (prefix, _f(up, d), prefix, _f(lo, d))
    if kind == 'ref':
        return '(%s)' % base
    return base  # basic: the caller draws the box


def normalize_hole_tol(args, current=None):
    """The drawing-wide hole tolerance. size and position are tolerance dicts or null."""
    out = dict(current or {})
    if 'size' in args:
        out['size'] = normalize_tol(args.get('size'))
    if 'position' in args:
        out['position'] = normalize_tol(args.get('position'))
    if 'show' in args and args['show'] is not None:
        if args['show'] not in HOLE_TOL_SHOW:
            raise ValueError('show must be one of %s' % ', '.join(HOLE_TOL_SHOW))
        out['show'] = args['show']
    out.setdefault('show', 'note')
    if 'note' in args:
        out['note'] = args.get('note') or ''
    if not out.get('size') and not out.get('position'):
        return None
    return out


def tol_phrase(tol):
    """Short tolerance text with no nominal: '±0.05', '+0.05/-0'."""
    tol = normalize_tol(tol)
    if tol is None:
        return ''
    d = tol.get('decimals', 0)
    if tol['kind'] == 'pm':
        return '\u00b1%s' % _t(tol['value'], d)
    if tol['kind'] in ('dev', 'limits') and 'plus' in tol:
        if tol['plus'] == tol['minus']:
            return '\u00b1%s' % _t(tol['plus'], d)
        return '+%s/-%s' % (_t(tol['plus'], d), _t(tol['minus'], d))
    if tol['kind'] == 'limits':
        d = tol.get('decimals', 2)
        return '%s/%s' % (_f(tol['upper'], d), _f(tol['lower'], d))
    return tol['kind'].upper()


def _own_decimals(tol):
    """Digits a tolerance is written with (0.05 -> 2), used to pick its block tier."""
    tol = normalize_tol(tol)
    if tol is None:
        return 0
    if tol.get('decimals') is not None:
        return tol['decimals']
    vals = [tol.get(k) for k in ('value', 'plus', 'minus', 'upper', 'lower') if tol.get(k)]
    best = 0
    for v in vals:
        s = ('%.6f' % v).rstrip('0').rstrip('.')
        best = max(best, len(s.split('.', 1)[1]) if '.' in s else 0)
    return best


def hole_differs(hole_tol, props, which, decimals=None):
    """The hole size or position tolerance when it differs from the block, else None."""
    if not hole_tol or not hole_tol.get(which):
        return None
    tol = hole_tol[which]
    if props is None:
        return tol
    d = _own_decimals(tol) if decimals is None else decimals
    return None if tol_matches_block(tol, props, d) else tol


def hole_note_text(hole_tol, props=None):
    """The hole note, or '' when nothing differs from the block or it shows in callouts only."""
    if not hole_tol or hole_tol.get('show', 'note') == 'callout':
        return ''
    if hole_tol.get('note'):
        return str(hole_tol['note'])
    parts = []
    size = hole_differs(hole_tol, props, 'size')
    pos = hole_differs(hole_tol, props, 'position')
    if size:
        parts.append('HOLE SIZE %s' % tol_phrase(size))
    if pos:
        parts.append('HOLE POSITION %s' % tol_phrase(pos))
    if not parts:
        return ''
    return 'ALL HOLES UNLESS OTHERWISE SPECIFIED: %s.' % ', '.join(parts)


def hole_callout_lines(el, hole_tol, props=None):
    """Lines of a hole callout. Thread specs always print. The hole size
    tolerance is added when the drawing shows it in callouts (or both) and it
    differs from the block tolerance, unless the callout has its own."""
    lines = []
    count = int(el.get('count') or 1)
    lead = ('%dX ' % count) if count > 1 else ''
    own = el.get('tol')
    show_in_callout = bool(hole_tol) and hole_tol.get('show') in ('callout', 'both')
    size_tol = own if own else (hole_tol.get('size') if show_in_callout else None)
    thread = (el.get('thread') or '').strip()
    if thread:
        tap = el.get('tap_drill')
        if tap not in (None, ''):
            lines.append('%s\u2300%s TAP DRILL%s' % (lead, _fmt_mm(tap), _depth(el.get('drill_depth'))))
            lines.append('%s%s' % (thread, _depth(el.get('thread_depth') or el.get('depth'))))
        else:
            lines.append('%s%s%s' % (lead, thread, _depth(el.get('thread_depth') or el.get('depth'))))
    else:
        dia = el.get('dia')
        body = dim_text(_fmt_mm(dia), size_tol, prefix='\u2300', props=props) if dia not in (None, '') else ''
        body = body.replace('\n', ' / ')
        lines.append('%s%s%s' % (lead, body, _depth(el.get('depth'))))
    for extra in el.get('extra') or []:
        lines.append(str(extra))
    pos = hole_differs(hole_tol, props, 'position') if show_in_callout else None
    if pos and not el.get('position_tol_off'):
        lines.append('POSITION %s' % tol_phrase(pos))
    return lines


def _fmt_mm(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return ('%.2f' % v).rstrip('0').rstrip('.') if v != int(v) else '%d' % v
    return str(v)


def _depth(depth):
    if depth in (None, ''):
        return ''
    if str(depth).strip().upper() == 'THRU':
        return ' THRU'
    return ' \u21a7 %s' % _fmt_mm(depth)


def dim_measure(el):
    """Measured length in sheet mm between the two points, along the dimension direction."""
    x1, y1, x2, y2 = (float(el[k]) for k in ('x1', 'y1', 'x2', 'y2'))
    orient = el.get('orient') or 'aligned'
    if orient == 'h':
        return abs(x2 - x1)
    if orient == 'v':
        return abs(y2 - y1)
    return math.hypot(x2 - x1, y2 - y1)
