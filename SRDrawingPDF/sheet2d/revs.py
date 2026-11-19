"""Rev letters, clerical decimals, and REVLOG.md.

Letters run A..Z skipping I, L, O, Q, then AA, AB, ... (same skips).
A model change bumps the letter and resets the decimal (C.02 -> D).
A drawing-only change is a clerical rev: C -> C.01 -> C.02.
The rev log lists one row per release. Clerical revs are never listed.
Rev A is always "Initial". Dates are dd/mm/yy.
Drafts are not clerical revs and are not written here.
"""
import datetime
import os
import re
from collections import namedtuple

LETTERS = [c for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' if c not in 'ILOQ']
_IDX = {c: i for i, c in enumerate(LETTERS)}
N = len(LETTERS)

RevEntry = namedtuple('RevEntry', 'rev desc by date')
REVLOG_NAME = 'REVLOG.md'
REVLOG_MAX_ROWS = 6


def index_to_letter(n):
    """0 -> A, 21 -> Z, 22 -> AA (bijective base 22 over the allowed letters)."""
    if n < 0:
        raise ValueError('rev index must be >= 0')
    s = ''
    n += 1
    while n:
        n, r = divmod(n - 1, N)
        s = LETTERS[r] + s
    return s


def letter_to_index(s):
    s = s.strip().upper()
    if not is_valid_letter(s):
        raise ValueError('not a valid rev letter: %r (A-Z, no I/L/O/Q)' % s)
    n = 0
    for c in s:
        n = n * N + _IDX[c] + 1
    return n - 1


def is_valid_letter(s):
    return bool(s) and all(c in _IDX for c in s.strip().upper())


def next_letter(s):
    return index_to_letter(letter_to_index(s) + 1)


def letter_from_release_count(n):
    """1 release -> A, 2 -> B, ..."""
    if n < 1:
        raise ValueError('release count must be >= 1')
    return index_to_letter(n - 1)


_REV_RE = re.compile(r'^\s*([A-Za-z]+)(?:\.(\d{1,3}))?\s*$')


def parse_rev(rev):
    """'C' -> ('C', 0); 'C.01' -> ('C', 1)."""
    m = _REV_RE.match(str(rev))
    if not m or not is_valid_letter(m.group(1)):
        raise ValueError('bad rev %r' % rev)
    return m.group(1).upper(), int(m.group(2) or 0)


def format_rev(letter, clerical=0):
    return letter.upper() if not clerical else '%s.%02d' % (letter.upper(), clerical)


def is_clerical(rev):
    try:
        return parse_rev(rev)[1] > 0
    except ValueError:
        return False


def base_letter(rev):
    return parse_rev(rev)[0]


def bump_clerical(rev):
    """Drawing-only change: C -> C.01, C.01 -> C.02. Not used for drafts."""
    letter, clerical = parse_rev(rev)
    return format_rev(letter, clerical + 1)


def bump_model(rev):
    """Model change: next letter, decimal reset. C.02 -> D, Z -> AA."""
    return next_letter(parse_rev(rev)[0])


def rev_key(rev):
    letter, clerical = parse_rev(rev)
    return (letter_to_index(letter), clerical)


def to_ddmmyy(d):
    """date / datetime / 'YYYY-MM-DD' / 'dd/mm/yy' / 'dd/mm/yyyy' -> 'dd/mm/yy'."""
    if d is None or d == '':
        return ''
    if isinstance(d, (datetime.date, datetime.datetime)):
        return d.strftime('%d/%m/%y')
    s = str(d).strip()
    m = re.match(r'^(\d{4})-(\d{1,2})-(\d{1,2})$', s)
    if m:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).strftime('%d/%m/%y')
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})$', s)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        return datetime.date(y, int(m.group(2)), int(m.group(1))).strftime('%d/%m/%y')
    raise ValueError('unrecognised date %r (use dd/mm/yy)' % d)


HEADER = """# REVLOG{title}

Rev log for this model and its drawing. One row per release, never per edit.
Clerical revs (C.01, C.02 ...) are not listed. Rev A is always "Initial". Date is dd/mm/yy.
The drawing's rev log table (sheet 1, top right) is generated from this file.

| Rev | Description | By | Date |
|-----|-------------|----|------|
"""


def _as_entry(e):
    if isinstance(e, RevEntry):
        return e
    return RevEntry(e['rev'], e.get('desc', ''), e.get('by', ''), e.get('date', ''))


def revlog_candidates(step_path, pn=None):
    """Where a model's rev log may live, in order."""
    d = os.path.dirname(os.path.abspath(step_path))
    stem = os.path.splitext(os.path.basename(step_path))[0]
    c = [os.path.join(d, '%s.%s' % (stem, REVLOG_NAME))]
    if pn:
        c.append(os.path.join(d, '%s.%s' % (pn, REVLOG_NAME)))
    steps = [f for f in os.listdir(d) if f.lower().endswith(('.step', '.stp'))] if os.path.isdir(d) else []
    if len(steps) <= 1:
        c.append(os.path.join(d, REVLOG_NAME))
    return c


def find_revlog(step_path, explicit=None, pn=None):
    """Explicit path, else the first existing revlog_candidates(). Returns path or None."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    if not step_path:
        return None
    for p in revlog_candidates(step_path, pn):
        if os.path.exists(p):
            return p
    return None


def read_revlog(path):
    """All rows in file order (oldest first). Header and separator rows are skipped."""
    out = []
    with open(path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if not s.startswith('|'):
                continue
            cells = [c.strip() for c in s.strip('|').split('|')]
            if len(cells) < 4:
                continue
            if cells[0].lower() == 'rev' or set(cells[0]) <= set('-: '):
                continue
            out.append(RevEntry(cells[0].upper(), cells[1], cells[2], cells[3]))
    return out


def write_revlog(path, entries, title=''):
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(HEADER.format(title=(' - %s' % title) if title else ''))
        for e in entries:
            e = _as_entry(e)
            f.write('| %s | %s | %s | %s |\n' % (e.rev, e.desc.replace('|', '/'), e.by, to_ddmmyy(e.date)))


def release_entries(entries, rev, desc, by, date):
    """Return a new RevEntry list with one release applied.

    `by` must already be valid initials. Clerical revs and a letter older than
    the latest logged letter raise ValueError. The same letter updates its row.
    """
    letter, clerical = parse_rev(rev)
    if clerical:
        raise ValueError('%s is a clerical rev; clerical revs are not listed in the rev log' % rev)
    entries = [_as_entry(e) for e in entries]
    if letter == 'A':
        desc = 'Initial'
    date = to_ddmmyy(date or datetime.date.today())
    made = RevEntry(letter, desc, by, date)
    logged = [x.rev for x in entries if not is_clerical(x.rev)]
    latest = max(logged, key=letter_to_index) if logged else None
    if latest and letter_to_index(letter) < letter_to_index(latest):
        raise ValueError('rev %s is older than the latest logged rev %s' % (letter, latest))
    if letter == latest:
        i = max(k for k, x in enumerate(entries) if x.rev == letter)
        entries[i] = made
    else:
        entries.append(made)
    return entries


def add_release(path, rev, desc, by=None, date=None, title=''):
    """Record one release in a REVLOG.md file. Clerical revs are refused."""
    from .settings import check_initials, requester_initials
    by = check_initials(by) if by else requester_initials()
    entries = read_revlog(path) if os.path.exists(path) else []
    entries = release_entries(entries, rev, desc, by, date)
    write_revlog(path, entries, title)
    return entries


def table_rows(entries, max_rows=REVLOG_MAX_ROWS):
    """Rows for the drawing table.

    Clerical revs dropped, one row per letter (latest wins), oldest to newest,
    Rev A forced to 'Initial', only the newest max_rows kept.
    """
    by_letter = {}
    for e in entries:
        e = _as_entry(e)
        try:
            letter, clerical = parse_rev(e.rev)
        except ValueError:
            continue
        if clerical:
            continue
        by_letter[letter] = RevEntry(letter, 'Initial' if letter == 'A' else e.desc, e.by, to_ddmmyy(e.date))
    rows = sorted(by_letter.values(), key=lambda e: letter_to_index(e.rev))
    return rows[-max_rows:] if max_rows else rows


def drawn_by(entries):
    """DRAWN is the BY of Rev A. None when the log has no Rev A row."""
    a = []
    for e in entries:
        e = _as_entry(e)
        if e.rev.strip().upper() == 'A':
            a.append(e)
    return a[0].by.strip() if a else None


def initials_problems(entries):
    """Blank or agent names in BY, and a log with no Rev A row."""
    from .settings import bad_initials
    out = []
    for e in entries:
        e = _as_entry(e)
        why = bad_initials(e.by)
        if why:
            out.append('rev %s: BY %s' % (e.rev, why))
    if entries and drawn_by(entries) is None:
        out.append('no Rev A row, so DRAWN is unknown')
    return out


def from_spec_revs(revs):
    """Legacy (rev, desc, date, by) tuples -> RevEntry list."""
    return [RevEntry(r[0], r[1], r[3] if len(r) > 3 else '', r[2] if len(r) > 2 else '') for r in (revs or [])]


def check_letter_matches(drawing_rev, rows):
    """Title-block letter (ignoring a clerical decimal) must equal the newest log letter."""
    if not rows or drawing_rev in (None, ''):
        return
    dl = base_letter(drawing_rev)
    ml = _as_entry(rows[-1]).rev
    if dl != ml:
        raise ValueError(
            'title block rev %s does not match the newest rev log entry %s; '
            'the model drives the letter - update REVLOG.md or the spec rev' % (drawing_rev, ml))
